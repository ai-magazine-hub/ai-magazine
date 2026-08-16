#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性刷新模型评分缓存（综合对话榜 + 编码榜），不 import generate_archive.py
（避免触发全量构建）。逻辑与 generate_archive.py 内 _fetch_* / fetch_live_* 一致，
仅 copy 必要常量与函数。任何网络失败都回退到已有缓存，绝不写空。
"""
import json, os, re, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
RATINGS_CACHE_FILE = os.path.join(BASE, "ratings_cache.json")
CODE_CACHE_FILE = os.path.join(BASE, "ratings_code_cache.json")

RATINGS_API = "https://docs.cherryai.com.cn/other/model_rank/text.md"
CODE_LATEST_URL = "https://raw.githubusercontent.com/oolong-tea-2026/arena-ai-leaderboards/main/data/latest.json"
CODE_API_URL = "https://api.wulong.dev/arena-ai-leaderboards/v1/leaderboard?name=code"

# 家族 → LMArena 模型名匹配规则（copy from generate_archive.py LM_MAP，务必保持一致）
LM_MAP = [
    ("GPT",              ["gpt"],                  [],            []),
    ("OpenAI o 系列",     ["o1", "o3", "o4", "o2"],  [],            ["gpt"]),
    ("Claude",           ["claude"],               [],            []),
    ("Gemini",           ["gemini"],               [],            []),
    ("Gemma",            ["gemma"],                [],            []),
    ("Llama",            ["llama"],                [],            []),
    ("Grok",             ["grok"],                 [],            []),
    ("DeepSeek 系列",     ["deepseek"],             [],            []),
    ("文心 ERNIE",        ["ernie"],                [],            []),
    ("通义千问 Qwen",      ["qwen"],                 [],            []),
    ("智谱 GLM",          ["glm"],                  [],            []),
    ("混元",              ["hunyuan"],              [],            []),
    ("Seed",              ["doubao", "seed"],        [],            ["seedance", "seedream"]),
    ("Coze 扣子",          ["coze"],                 [],            []),
    ("Kimi",             ["kimi"],                 [],            []),
    ("Mistral 系列",       ["mistral"],              [],            []),
    ("Baichuan",         ["baichuan"],             [],            []),
    ("MiniMax 系列",       ["minimax", "minmax", "abab"], [],       []),
    ("星火",              ["iflytek", "spark"],     [],            ["muse"]),
]

def _fetch_cherry_leaderboard():
    try:
        req = urllib.request.Request(RATINGS_API, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode("utf-8", "replace")
    except Exception as e:
        print("  [chat] fetch failed:", e)
        return []
    out = []
    for line in raw.splitlines():
        s = line.strip()
        if not s.startswith("|") or "---" in s:
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 5:
            continue
        if cells[0] == "Rank" or cells[2] == "模型":
            continue
        m = re.search(r"(\d{3,4})", cells[3])
        if not m:
            continue
        elo = int(m.group(1))
        if elo < 1000 or elo > 1800:
            continue
        out.append((cells[2], elo))
    return out

def fetch_live_ratings():
    rows = _fetch_cherry_leaderboard()
    if not rows:
        rows = _fetch_text_arena()
    if not rows:
        return {}
    out = {}
    for fam, name_pats, vend_pats, excl_pats in LM_MAP:
        best = None
        for model, elo in rows:
            ml = model.lower()
            if not any(p in ml for p in name_pats):
                continue
            if excl_pats and any(p in ml for p in excl_pats):
                continue
            if vend_pats and not any(v in ml for v in vend_pats):
                continue
            if best is None or elo > best:
                best = elo
        if best is not None:
            out[fam] = best
    return out

def _fetch_text_arena():
    """兜底：从 oolong-tea 归档的 Arena.ai 文本榜（text.json）取 {模型名, Elo}；失败返回 []。"""
    rows = []
    try:
        req = urllib.request.Request(CODE_LATEST_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            latest = json.loads(r.read().decode("utf-8", "replace"))
        date = latest.get("date")
        if date:
            url = f"https://raw.githubusercontent.com/oolong-tea-2026/arena-ai-leaderboards/main/data/{date}/text.json"
            req2 = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req2, timeout=25) as r2:
                data = json.loads(r2.read().decode("utf-8", "replace"))
            for m in data.get("models", []):
                sc = m.get("score")
                if isinstance(sc, (int, float)) and 1000 <= sc <= 1900:
                    rows.append((str(m.get("model", "")), int(sc)))
    except Exception:
        pass
    return rows

def _fetch_code_arena():
    rows = []
    try:
        req = urllib.request.Request(CODE_LATEST_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            latest = json.loads(r.read().decode("utf-8", "replace"))
        date = latest.get("date")
        if date:
            url = f"https://raw.githubusercontent.com/oolong-tea-2026/arena-ai-leaderboards/main/data/{date}/code.json"
            req2 = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req2, timeout=25) as r2:
                data = json.loads(r2.read().decode("utf-8", "replace"))
            for m in data.get("models", []):
                sc = m.get("score")
                if isinstance(sc, (int, float)) and 1000 <= sc <= 1900:
                    rows.append((str(m.get("model", "")), int(sc)))
    except Exception as e:
        print("  [code] github raw failed:", e)
    if not rows:
        try:
            req = urllib.request.Request(CODE_API_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            for m in data.get("models", []):
                sc = m.get("score")
                if isinstance(sc, (int, float)) and 1000 <= sc <= 1900:
                    rows.append((str(m.get("model", "")), int(sc)))
        except Exception as e:
            print("  [code] fallback api failed:", e)
    return rows

def fetch_live_code_ratings():
    rows = _fetch_code_arena()
    if not rows:
        return {}
    out = {}
    for fam, name_pats, vend_pats, excl_pats in LM_MAP:
        best = None
        for model, elo in rows:
            ml = model.lower()
            if not any(p in ml for p in name_pats):
                continue
            if excl_pats and any(p in ml for p in excl_pats):
                continue
            if vend_pats and not any(v in ml for v in vend_pats):
                continue
            if best is None or elo > best:
                best = elo
        if best is not None:
            out[fam] = best
    return out

def load_cache(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("ratings", {}) if isinstance(d, dict) else {}
    except Exception:
        return {}

def save_cache(path, ratings):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": int(time.time()), "ratings": ratings}, f, ensure_ascii=False, indent=2)

def diff_report(name, old, new):
    print(f"\n=== {name} 变更 ===")
    changed = False
    for k in sorted(set(list(old.keys()) + list(new.keys()))):
        ov, nv = old.get(k), new.get(k)
        if ov != nv:
            changed = True
            mark = "NEW" if ov is None else ("DEL" if nv is None else "UPD")
            print(f"  [{mark}] {k}: {ov} -> {nv}")
    if not changed:
        print("  (无变化)")

def main():
    # 综合对话榜
    old_chat = load_cache(RATINGS_CACHE_FILE)
    live_chat = fetch_live_ratings()
    print(f"[chat] 拉到 {len(live_chat)} 个家族评分")
    if live_chat:
        new_chat = {**old_chat, **live_chat}
        save_cache(RATINGS_CACHE_FILE, new_chat)
        diff_report("综合对话榜", old_chat, new_chat)
    else:
        print("[chat] 拉取为空，保留原缓存（不覆盖）")

    # 编码榜
    old_code = load_cache(CODE_CACHE_FILE)
    live_code = fetch_live_code_ratings()
    print(f"[code] 拉到 {len(live_code)} 个家族评分")
    if live_code:
        new_code = {**old_code, **live_code}
        save_cache(CODE_CACHE_FILE, new_code)
        diff_report("编码榜", old_code, new_code)
    else:
        print("[code] 拉取为空，保留原缓存（不覆盖）")

    print("\n完成。缓存时间戳已更新。")

if __name__ == "__main__":
    main()
