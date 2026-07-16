#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地用 DeepSeek API 把英文详情页全文翻译为简体中文。
断点续传：已 zh=True 的条目跳过；每 20 条落盘一次；顺序调用 + 429/5xx 退避重试。
key 从 /tmp/dskey 读取（不写入仓库）。
"""
import json, os, time, sys, ssl, urllib.request, urllib.parse

ARCHIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive.json")
KEY_FILE = "/tmp/dskey"
LOG = "/tmp/deepseek_translate.log"
API = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

def log(*a):
    msg = " ".join(str(x) for x in a)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg, flush=True)

def ratio_en(s):
    if not s: return 0
    L = [c for c in s if c.isascii() and c.isalpha()]
    return len(L) / max(1, len(s))

def load_key():
    with open(KEY_FILE, encoding="utf-8") as f:
        return f.read().strip()

def chunk_text(text, limit=3500):
    """按段落切分，尽量凑满 limit 字符，避免单条过长导致截断。"""
    paras = [p for p in text.split("\n") if p.strip() != ""]
    if not paras:
        return [text] if text.strip() else []
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 1 <= limit:
            cur = (cur + "\n" + p) if cur else p
        else:
            if cur:
                chunks.append(cur)
            # 单段超长则硬切
            if len(p) > limit:
                for i in range(0, len(p), limit):
                    chunks.append(p[i:i+limit])
                cur = ""
            else:
                cur = p
    if cur:
        chunks.append(cur)
    return chunks

def translate(text, key):
    chunks = chunk_text(text)
    out_parts = []
    for ch in chunks:
        if not ch.strip():
            continue
        body = json.dumps({
            "model": MODEL,
            "messages": [
                {"role": "system", "content":
                 "You are a professional Chinese translator for AI and technology news. "
                 "Translate the user's English text into fluent Simplified Chinese. "
                 "Keep all brand names, model names, product names, technical terms, code, "
                 "URLs, and numbers exactly as in the original. Preserve paragraph breaks. "
                 "Output only the translated text, with no extra commentary."},
                {"role": "user", "content": ch}
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
        }).encode("utf-8")
        last_err = None
        for attempt in range(6):
            try:
                req = urllib.request.Request(
                    API, data=body,
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
                    d = json.loads(r.read().decode("utf-8"))
                out_parts.append(d["choices"][0]["message"]["content"])
                break
            except Exception as e:
                last_err = e
                # 429 / 5xx / 超时 -> 退避
                wait = min(2 ** attempt, 30) + 1
                time.sleep(wait)
        else:
            # 全失败：保留原文该段，避免丢内容
            out_parts.append(ch)
            log(f"  ! 翻译单段失败(保留原文): {repr(last_err)[:80]}")
        time.sleep(1.0)  # 限速，降低触发限流
    return "\n\n".join(out_parts).strip()

def main():
    key = load_key()
    limit = int(os.environ.get("DS_LIMIT", "0") or "0")  # 0=全部；>0=本轮最多翻译多少条
    arch = json.load(open(ARCHIVE, encoding="utf-8"))
    log(f"[启动] 载入 {len(arch)} 期；本轮上限 DS_LIMIT={limit}")
    total = done0 = pending = skip = 0
    for d, rec in arch.items():
        for s in rec.get("sections", []):
            for it in s.get("items", []):
                total += 1
                if it.get("zh"):
                    done0 += 1
                    continue
                c = (it.get("content") or "").strip()
                if not c or len(c) < 120 or ratio_en(c) <= 0.45:
                    it["zh"] = True
                    skip += 1
                    continue
                pending += 1
    log(f"[统计] 总{total} 已译{done0} 待翻{pending} 跳过(无英文){skip}")
    done = 0
    for d, rec in arch.items():
        for s in rec.get("sections", []):
            for it in s.get("items", []):
                if it.get("zh"):
                    continue
                c = (it.get("content") or "").strip()
                if not c or len(c) < 120 or ratio_en(c) <= 0.45:
                    it["zh"] = True
                    skip += 1
                    continue
                try:
                    zh = translate(c, key)
                    if zh:
                        it["content"] = zh
                        it["zh"] = True
                        done += 1
                    else:
                        it["zh"] = True  # 空结果也标记，避免死循环
                except Exception as e:
                    log(f"  ! 条目异常 {d}: {repr(e)[:80]}")
                    it["zh"] = True
                if done % 10 == 0:
                    json.dump(arch, open(ARCHIVE, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1)
                    log(f"  ... 已译 {done}/{pending}")
                if limit and done >= limit:
                    log(f"[达到本轮上限 {limit}] 暂停，下次继续")
                    json.dump(arch, open(ARCHIVE, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1)
                    log(f"[完成] 本轮新译 {done} 条；累计已译 {done0+done}；跳过 {skip}")
                    return
    json.dump(arch, open(ARCHIVE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    log(f"[完成] 本轮新译 {done} 条；累计已译 {done0+done}；跳过 {skip}")

if __name__ == "__main__":
    main()
