#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
polish_recent.py —— 自动「完善」最近若干天日报：回填缺失正文 + 清理网页残留噪声。

背景：
  定时同步 sync_cron.sh 只跑 generate_archive.py（增量：已生成的日期跳过、不回抓），
  因此某条目初次抓取时若正文失败/为空、或 trafilatura 残留站点导航/页脚噪声，
  之后便永远不会被修正 —— 用户看到「今天/昨天内容没完善好」（缺正文、排版乱、原始网页残留）。

  本脚本把已被验证的三段逻辑（refetch_aihot / refill_empty / deepclean_trafilatura）组装成
  「一次遍历、一处写盘」的完善流程，仅作用于最近 N 天（默认 10，可用 --since/--dates/--all 调整）：

    1) 离线更强清洗 deep_clean_extra：剥离站点页脚/导航墙、图片署名、广告/Markdown 图片行、
       零宽字符（幂等，干净条目为 no-op）。
    2) 若清洗后仍缺正文(<120字)或仍带噪声 → 回源补全：
         a. 优先 AI HOT 已清洗正文（fetch_aihot_body，干净无 chrome）；
         b. 旧条目无 permalink 时按标题匹配 AI HOT item id；
         c. 仍无 → trafilatura 直抓源站（refill_empty.fetch_content）。
       仅当新正文「更完整/更干净」且不会把已译中文退化成英文时才采用。
    3) 按语言置 zh：中文 → zh=True（保留）；英文 → zh=False（交给 generate_archive 重译）。

  安全护栏（绝不丢内容 / 不退化翻译）：
    - 不改动范围外日期；写盘前自动备份 archive.json -> archive.json.bak；
    - deep_clean_extra 内置「删后 < 原长50% 且原长>200 则回退」护栏；
    - 已有干净中文译文且 AI HOT 返回英文时，保留旧译文。

用法：
  python polish_recent.py                 # 完善最近 10 天并写盘
  python polish_recent.py --since 15      # 完善最近 15 天
  python polish_recent.py --dates 2026-08-04,2026-08-03
  python polish_recent.py --all           # 完善全库
  python polish_recent.py --dry-run       # 只统计将改多少条，不联网、不写盘

写盘后请（脚本外层 polish_recent.sh 已自动）再跑一次 generate_archive.py 完成：
英文新正文重译 + 全量重新渲染。
"""
import sys, os, re, json, ssl, argparse, datetime, urllib.request, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ARCH_PATH = os.path.join(HERE, "archive.json")

# ── 复用已被验证的「自包含」模块（均带 __main__ 守卫，import 无副作用）──
from refetch_aihot import (
    traolid, fetch_aihot_body, build_title_pid_map, ratio_en, has_chrome_noise,
)
from deepclean_trafilatura import deep_clean_extra
from refill_empty import fetch_content as traf_fetch_content

# 正文长度阈值：< 该值视为「缺失/过短」需要补全
MIN_BODY = 120


def fetch_best_body(it, title_map):
    """回源取最优正文：AI HOT 已清洗正文 > trafilatura 源站。返回 >=MIN_BODY 的字符串或 ''。"""
    pid = traolid(it.get("permalink"))
    if pid:
        aihot = fetch_aihot_body(pid)
        if aihot and len(aihot.strip()) >= MIN_BODY:
            return aihot
    # 旧条目无 permalink → 按标题匹配 AI HOT item id
    if not pid:
        pid = title_map.get((it.get("title") or "").strip())
        if pid:
            aihot = fetch_aihot_body(pid)
            if aihot and len(aihot.strip()) >= MIN_BODY:
                return aihot
    # 最后手段：trafilatura 直抓源站
    src = traf_fetch_content(it.get("url"), it.get("permalink"))
    if src and len(src.strip()) >= MIN_BODY:
        return src
    return ""


def polish_item(it, date, title_cache):
    """完善单条。返回 True 表示内容有改动。"""
    old = (it.get("content") or "").strip()
    if not old:
        # 完全无正文：直接尝试补全
        if date not in title_cache:
            title_cache[date] = build_title_pid_map(date)
        fresh = fetch_best_body(it, title_cache[date])
        if fresh and len(fresh.strip()) >= MIN_BODY:
            it["content"] = deep_clean_extra(fresh)
            it["zh"] = (ratio_en(it["content"]) <= 0.45)
            return True
        return False

    # 已有正文：先离线清洗（幂等）
    cleaned = deep_clean_extra(old)
    need_fetch = (len(cleaned.strip()) < MIN_BODY) or has_chrome_noise(cleaned)
    if need_fetch:
        if date not in title_cache:
            title_cache[date] = build_title_pid_map(date)
        fresh = fetch_best_body(it, title_cache[date])
        if fresh and len(fresh.strip()) >= MIN_BODY:
            cand = deep_clean_extra(fresh)
            adopt = False
            if len(cleaned.strip()) < MIN_BODY:
                adopt = True
            elif has_chrome_noise(cleaned) and not has_chrome_noise(cand):
                adopt = True
            # 绝不把已译中文退化成英文
            old_is_cn = ratio_en(old) <= 0.45
            cand_is_cn = ratio_en(cand) <= 0.45
            if old_is_cn and not cand_is_cn:
                adopt = False
            if adopt:
                cleaned = cand
    if cleaned != old:
        it["content"] = cleaned
        it["zh"] = (ratio_en(cleaned) <= 0.45)
        return True
    return False


def beijing_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)


def main():
    ap = argparse.ArgumentParser(description="完善最近若干天日报（回填正文 + 清理网页残留）")
    ap.add_argument("--all", action="store_true", help="完善全库所有日期")
    ap.add_argument("--since", type=int, default=10, help="完善最近 N 天（默认 10）")
    ap.add_argument("--dates", type=str, default="", help="逗号分隔日期 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="只统计将改多少条，不联网、不写盘")
    args = ap.parse_args()

    arch = json.load(open(ARCH_PATH, encoding="utf-8"))
    print(f"载入 archive.json：{len(arch)} 期")

    if args.all:
        target = sorted(arch.keys(), reverse=True)
    elif args.dates:
        target = [d.strip() for d in args.dates.split(",") if d.strip()]
    else:
        cutoff = (beijing_now() - datetime.timedelta(days=args.since)).strftime("%Y-%m-%d")
        target = [d for d in sorted(arch.keys(), reverse=True) if d >= cutoff]
    print(f"目标日期（{len(target)} 个）：{target[0]} ... {target[-1]}"
          + ("  [dry-run]" if args.dry_run else ""))

    stats = {"checked": 0, "refilled": 0, "cleaned": 0, "examples": []}
    title_cache = {}
    for date in target:
        rec = arch.get(date)
        if not rec:
            continue
        for sec in rec.get("sections", []):
            for it in sec.get("items", []):
                old = (it.get("content") or "").strip()
                if not old:
                    stats["checked"] += 1
                    if args.dry_run:
                        stats["refilled"] += 1
                        if len(stats["examples"]) < 30:
                            stats["examples"].append(
                                (date, sec.get("label", ""), it.get("title", "")[:40], 0, "需补全正文"))
                        continue
                    if polish_item(it, date, title_cache):
                        stats["refilled"] += 1
                        if len(stats["examples"]) < 30:
                            stats["examples"].append(
                                (date, sec.get("label", ""), it.get("title", "")[:40], 0,
                                 len(it.get("content") or "")))
                    continue
                # 已有正文：离线清洗 + （必要时）补全
                cleaned = deep_clean_extra(old)
                need_fetch = (len(cleaned.strip()) < MIN_BODY) or has_chrome_noise(cleaned)
                if args.dry_run:
                    stats["checked"] += 1
                    if cleaned != old:
                        stats["cleaned"] += 1
                        if len(stats["examples"]) < 30:
                            stats["examples"].append(
                                (date, sec.get("label", ""), it.get("title", "")[:40],
                                 len(old), "清理残噪"))
                    elif need_fetch:
                        stats["refilled"] += 1
                        if len(stats["examples"]) < 30:
                            stats["examples"].append(
                                (date, sec.get("label", ""), it.get("title", "")[:40],
                                 len(old), "可能补全正文"))
                    continue
                # 正式：polish_item 内部已含清洗+补全逻辑
                if polish_item(it, date, title_cache):
                    new_len = len(it.get("content") or "")
                    if new_len >= MIN_BODY and old and len(old) < MIN_BODY:
                        stats["refilled"] += 1
                        tag = f"补全正文->{new_len}"
                    elif new_len < MIN_BODY and (len(cleaned.strip()) < MIN_BODY):
                        stats["refilled"] += 1
                        tag = "尝试补全"
                    else:
                        stats["cleaned"] += 1
                        tag = f"清理残噪 {len(old)}->{new_len}"
                    stats["checked"] += 1
                    if len(stats["examples"]) < 30:
                        stats["examples"].append(
                            (date, sec.get("label", ""), it.get("title", "")[:40], len(old), tag))

    print(f"[完善] 检查 {stats['checked']} | 补全正文 {stats['refilled']} | "
          f"清理残噪 {stats['cleaned']}")
    for d, lab, t, lo, tag in stats["examples"]:
        print(f"    · {d} [{lab}] {t}  ({tag})")

    if args.dry_run:
        print("[dry-run] 未联网、未写盘。")
        return

    if stats["refilled"] == 0 and stats["cleaned"] == 0:
        print("无需完善，archive.json 未改动")
        return

    bak = ARCH_PATH + ".bak"
    shutil.copy2(ARCH_PATH, bak)
    print(f"已备份 -> {bak}")
    json.dump(arch, open(ARCH_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写回 archive.json")
    print("下一步：运行 `python generate_archive.py` 完成英文新正文重译 + 全量重新渲染。")


if __name__ == "__main__":
    main()
