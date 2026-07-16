#!/usr/bin/env python3
# 本地独立翻译脚本（不依赖 generate_archive.py，避免 import 触发其网络抓取主流程）
# 作用：本机直连 Google 免费端点，把 archive.json 中未译(英文)正文翻成中文。
# 针对本机实测返回的 429 限流做「指数退避(封顶120s) + 双镜像」重试；
# 全局限速 2s/请求降低触发限流概率；断点续传(已 zh=True 跳过)，每 25 条落盘一次。
import json, re, os, sys, time, threading
import urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_PATH = os.path.join(HERE, "archive.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_lock = threading.Lock()
_last = {"t": 0.0}
_MIN_INTERVAL = 2.0  # 相邻请求最小间隔(秒)，降低触发 429 的概率


def ratio_en(s):
    if not s:
        return 0
    letters = [c for c in s if c.isascii() and c.isalpha()]
    return len(letters) / max(1, len(s))


def _gtrans_one(text):
    """单段翻译；遇 429 指数退避重试(封顶120s)，双镜像容错；彻底失败返回 None。"""
    body = urllib.parse.urlencode(
        {"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": text}).encode()
    backoff = 5
    for host in ("translate.googleapis.com", "clients5.google.com"):
        for _ in range(8):
            try:
                with _lock:
                    now = time.time()
                    wait = _MIN_INTERVAL - (now - _last["t"])
                    if wait > 0:
                        time.sleep(wait)
                    _last["t"] = time.time()
                req = urllib.request.Request(
                    f"https://{host}/translate_a/single", data=body,
                    headers={"User-Agent": UA,
                             "Content-Type": "application/x-www-form-urlencoded"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read().decode("utf-8"))
                out = "".join(seg[0] for seg in data[0] if seg and seg[0])
                if out.strip():
                    return out
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 120)
                else:
                    time.sleep(2)
            except Exception:
                time.sleep(2)
    return None


def _gtrans(text):
    if len(text) <= 1800:
        return _gtrans_one(text) or text
    parts = re.split(r'(?<=[.!?])\s+', text)
    out, buf = [], ""
    for s in parts:
        if buf and len(buf) + len(s) >= 1800:
            out.append(_gtrans_one(buf) or buf)
            buf = ""
        buf = (buf + " " + s) if buf else s
    if buf:
        out.append(_gtrans_one(buf) or buf)
    return " ".join(out)


_IMG_RE = re.compile(r'^\s*!\[[^\]]*\]\([^)]*\)\s*$')


def translate_en_zh(text):
    """段落级翻译：图片标记行、纯中文行原样保留；含拉丁字母的段落送翻。"""
    paras = re.split(r'\n{1,}', text)
    out = []
    for p in paras:
        if not p.strip():
            out.append(p)
            continue
        if _IMG_RE.match(p):
            out.append(p)
            continue
        if not re.search(r'[A-Za-z]', p):
            out.append(p)
            continue
        out.append(_gtrans(p))
    return "\n".join(out)


def load_archive():
    if os.path.exists(ARCHIVE_PATH):
        try:
            with open(ARCHIVE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_archive(arch):
    with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
        json.dump(arch, f, ensure_ascii=False)


def main():
    arch = load_archive()
    print(f"[载入] 共 {len(arch)} 期", flush=True)
    todos, skipped = [], 0
    for d, rec in arch.items():
        for s in rec.get("sections", []):
            for it in s.get("items", []):
                if it.get("zh"):
                    skipped += 1
                    continue
                c = it.get("content") or ""
                if len(c) < 120 or ratio_en(c) <= 0.45:
                    it["zh"] = True
                    skipped += 1
                    continue
                todos.append(it)
    total = len(todos)
    print(f"[待翻] {total} 条 | [跳过/已译/短/中文] {skipped} 条", flush=True)
    done = failed = 0
    for i, it in enumerate(todos, 1):
        c = it.get("content") or ""
        new = translate_en_zh(c)
        if new and ratio_en(new) <= 0.45:
            it["content"] = new
            it["zh"] = True
            done += 1
        else:
            it["zh"] = False
            failed += 1
        if i % 25 == 0:
            save_archive(arch)
            print(f"[进度] {i}/{total} 完成 {done} 失败 {failed}", flush=True)
    save_archive(arch)
    print(f"[结束] 完成 {done} / 失败 {failed} / 总 {total}", flush=True)


if __name__ == "__main__":
    main()
