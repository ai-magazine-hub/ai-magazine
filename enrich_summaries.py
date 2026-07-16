#!/usr/bin/env python3
"""从 AI HOT 日报接口回填「完整中文摘要」到 archive.json。

- 只更新每条新闻的 summary 字段（用feed里的完整摘要替换原先被截断的60字摘要）
- 绝不触碰 content（已镜像的全文）及其他字段
- 按 url 精确匹配；feed 不可达的日期跳过（保留原样）
- 礼貌限速；原子写盘
"""
import json, os, sys, time, urllib.request, ssl

BASE = "https://aihot.virxact.com/api/public"
OUT = os.path.dirname(os.path.abspath(__file__))
ARCH = os.path.join(OUT, "archive.json")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

def fetch(date):
    url = f"{BASE}/daily/{date}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))

def feed_map(daily):
    """url -> 完整 summary"""
    m = {}
    for sec in daily.get("sections", []):
        for it in sec.get("items", []):
            u = (it.get("sourceUrl") or it.get("permalink") or "").strip()
            s = (it.get("summary") or "").strip()
            if u and s:
                m[u] = s
    return m

def main():
    arch = json.load(open(ARCH, encoding="utf-8"))
    dates = sorted(arch.keys(), reverse=True)
    updated = 0
    skipped_feed = 0
    for i, date in enumerate(dates):
        try:
            fm = feed_map(fetch(date))
        except Exception as e:
            skipped_feed += 1
            print(f"  · {date} feed 不可达，跳过 ({type(e).__name__})")
            continue
        rec = arch[date]
        for sec in rec.get("sections", []):
            for it in sec.get("items", []):
                u = (it.get("url") or "").strip()
                fs = fm.get(u)
                if not fs:
                    continue
                cur = (it.get("summary") or "").strip()
                # 仅当 feed 摘要更长（即更完整）时替换
                if len(fs) > len(cur):
                    it["summary"] = fs
                    updated += 1
        if (i + 1) % 15 == 0:
            print(f"  进度 {i+1}/{len(dates)} · 已更新摘要 {updated} 条")
        time.sleep(0.12)

    tmp = ARCH + ".tmp"
    json.dump(arch, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, ARCH)
    print(f"[完成] 共更新 {updated} 条摘要；{skipped_feed} 个日期 feed 不可达已跳过。")

if __name__ == "__main__":
    main()
