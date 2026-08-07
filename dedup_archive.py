#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dedup_archive.py — 跨日期同源重复条目去重（离线、幂等、安全）。

问题：AI HOT 的「当日快照」与「实时 feed」会把同一篇报道同时落入相邻两天，
导致同一新闻在两天都出现（已核实全库 65 组、均为相邻两天、同源 permalink/url）。
但 permalink 在两天的格式不一致（相对路径 /items/xxx vs 绝对路径 https://.../items/xxx），
直接用 permalink 字符串比对会漏判，必须用「AI HOT item id」或「source url」做规范化 key。

策略：
- 规范化 key = 提取 permalink 里的 /items/<id>；无则回退 source url（归一小写、去尾斜杠）。
  仅对「有 id 或 url」的条目去重，避免按标题误并不同报道。
- 对每个重复组：保留【最早日期】的那条为权威条目，但用组内【最优正文】
  （优先 zh=True，其次正文最长）升级其内容/summary/zh，保证不丢翻译与更完整正文；
  删除其余（较新日期）的重复出现。
- 幂等：已无重复时 no-op，不写盘。

用法：
  python3 dedup_archive.py            # 实际去重并写盘
  python3 dedup_archive.py --dry-run  # 仅统计，不写盘
"""
import json, re, sys, os

ARCH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive.json")


def _norm_list(v):
    """确保 items 是 list（兼容历史字符串化形式），就地转为 list。"""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    return v or []


def _dedup_key(it):
    """规范化去重键：AI HOT item id > source url。两者皆无则返回 None（不参与去重）。"""
    p = it.get("permalink") or ""
    m = re.search(r"/items/([A-Za-z0-9]+)", p)
    if m:
        return "ID:" + m.group(1)
    u = (it.get("url") or "").strip().lower().rstrip("/")
    if u:
        return "U:" + u
    return None


def _zh(it):
    return str(it.get("zh")) == "True"


def _best(it):
    """评分：优先已译，其次正文更长。"""
    return (1 if _zh(it) else 0, len(it.get("content") or ""))


def iter_sections(arch):
    for date in arch:
        rec = arch[date]
        if not isinstance(rec, dict):
            continue
        for sec in rec.get("sections", []):
            yield date, sec


def dedup(arch, dry_run=False):
    # 把历史字符串化 items 就地转为 list，便于后续按引用删除
    for _date, sec in iter_sections(arch):
        sec["items"] = _norm_list(sec.get("items"))

    # 收集每个 key 的所有出现 (date, sec, item_dict 引用)
    groups = {}
    for date, sec in iter_sections(arch):
        for it in sec["items"]:
            if not isinstance(it, dict):
                continue
            k = _dedup_key(it)
            if not k:
                continue
            groups.setdefault(k, []).append((date, sec, it))

    multi = {k: v for k, v in groups.items() if len(v) > 1}
    if not multi:
        print("无跨日期同源重复，无需去重。")
        return 0

    removed = 0
    for k, occ in multi.items():
        occ_sorted = sorted(occ, key=lambda t: t[0])  # 按日期升序
        canon = occ_sorted[0][2]                       # 权威条目（最早日期，字典引用）
        best = max(occ, key=lambda t: _best(t[2]))    # 组内最优正文
        # 升级权威条目（若当前不如最优）
        if _best(best[2]) > _best(canon):
            if not _zh(canon) and _zh(best[2]):
                canon["zh"] = "True"
            if len(best[2].get("content") or "") > len(canon.get("content") or ""):
                canon["content"] = best[2]["content"]
            if not (canon.get("summary") or "").strip() and (best[2].get("summary") or "").strip():
                canon["summary"] = best[2]["summary"]
        # 删除其余（较新日期）出现，用引用删除，避免索引错位
        for _date, sec, it in occ_sorted[1:]:
            if it in sec["items"]:
                sec["items"].remove(it)
                removed += 1

    print(f"同源重复组 {len(multi)} 组，移除重复条目 {removed} 条（保留最早日期并升级最优正文）。")
    if not dry_run:
        with open(ARCH_PATH, "w", encoding="utf-8") as f:
            json.dump(arch, f, ensure_ascii=False)
        print("已写盘 archive.json。")
    return removed


def main():
    dry = "--dry-run" in sys.argv
    arch = json.load(open(ARCH_PATH, encoding="utf-8"))
    print(f"载入 archive.json：{len(arch)} 期")
    if dry:
        print("[dry-run] 仅统计，不写盘。")
    dedup(arch, dry_run=dry)


if __name__ == "__main__":
    main()
