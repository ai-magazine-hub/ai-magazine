#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性把 archive.json 中误归它栏的「纯基础模型发布」纠正回「模型发布/更新」。
与 generate_archive.py 内 reroute_model_release_items 逻辑保持一致（独立副本，避免 import 触发全量构建）。
用法：
  python3 reroute_model_releases.py            # 实际执行
  python3 reroute_model_releases.py --dry-run  # 仅预览
"""
import json, re, sys, os

ARCH = "archive.json"
MODEL_LABEL = "模型发布/更新"
MODEL_COLOR = "#4f46e5"

# ── 复用 generate_archive.py 的判定常量（保持一致）──
_GANT_SKIP_KW = ["融资", "收购", "并购", "财报", "上市", "诉讼", "监管", "处罚",
                 "招聘", "离职", "人事变动", "获奖", "榜单", "排名", "论坛", "大会", "协会"]
_MODEL_RELEASE_ACT = ["发布", "推出", "开源", "上线", "首发", "正式可用", "ga", "release"]
_MODEL_RELEASE_HARD = [
    "登录", "登陆", "上架", "接入", "落地", "技术报告", "研究报告", "论文",
    "白皮书", "合作", "联合", "评测", "基准", "benchmark", "榜单", "排名",
    "融资", "收购", "获奖", "大会", "论坛", "开源周", "直播", "教程",
]
_MODEL_VERSION_RE = re.compile(
    r"(?:v|V)?\d+\.\d+(?:\.\d+)?|\d+\.\d+\s*(?:版本|版)|"
    r"(?:gpt|claude|gemini|llama|grok|glm|kimi|qwen|ernie|mixtral|mistral|nova|titan|abab|baichuan|spark|deepseek)[- ]?\d", re.I)
_MODEL_TYPE_KW = ["大模型", "模型", "moE", "moe", "基座", "多模态", "推理模型", "语言模型",
                  "开源模型", "视频模型", "图像模型", "声音模型", "语音模型", "文生", "图生"]
_MODEL_RELEASE_BLACKLIST = ["chatgpt work", "最强模型与最佳博文", "最佳博文",
                            "app 上线", "app上线", "智能体 app", "agent app"]
# 仅匹配「模型族前缀 + 版本」，不含裸版本号（工具版本），避免产品/工具误判
_MODEL_FAM_VER_RE = re.compile(
    r"(?:gpt|claude|gemini|llama|grok|glm|kimi|qwen|ernie|mixtral|mistral|nova|titan|"
    r"abab|baichuan|spark|deepseek|seedance|veo|imagen|flux|midjourney|nemotron|mimo|"
    r"sensenova|hunyuan|kling|wan|runway|luma|hailuo|vidu|elevenlabs|cartesia|yi|step)"
    r"[- ]?v?\d", re.I)
_MODEL_RELEASE_TYPE_STRICT = ["大模型", "moE", "moe", "基座", "多模态模型", "推理模型",
                              "语言模型", "视频模型", "图像模型", "语音模型", "开源模型",
                              "文生", "图生"]
_RELEASE_NOT_KW = [
    "支持", "提供", "训练", "技术", "算子", "分词", "优化", "整合", "框架", "引擎",
    "基础设施", "数据库", "协议", "范式", "方案", "方法", "修复", "基准", "排行榜", "bench",
    "阐述", "游说", "面临", "考验", "路径", "助力", "课程", "指南", "访谈", "周年",
    "复盘", "展望", "预测", "分析", "解读", "评论", "思考", "市场", "功能",
    "计划", "批准", "暂缓", "延缓", "限制", "监管", "曝", "下月", "研讨会", "峰会",
]
_PRODUCT_TOOL_KW = [
    "code", "cli", "app", "桌面端", "平台", "插件", "版本说明", "mcp", "gateway",
    "功能上新", "框架", "sdk", "插件市场", "office", "玩法", "盘点", "教程",
    "研究", "agent platform", "api gateway", "市场通配符", "机器人",
]
_REROUTE_ACT = ["发布", "推出", "上线", "首发", "正式可用", "ga", "release"]


def is_base_model_release(title):
    t = title or ""
    tl = t.lower()
    if not any(a in tl for a in _REROUTE_ACT):
        return False
    if any(k in tl for k in _RELEASE_NOT_KW):
        return False
    if any(k in tl for k in _PRODUCT_TOOL_KW):
        return False
    if _MODEL_FAM_VER_RE.search(tl):
        return True
    if any(k in tl for k in _MODEL_RELEASE_TYPE_STRICT):
        return True
    return False


def reroute_model_release_items(rec):
    if not rec or "sections" not in rec:
        return []
    moved = []
    for sec in list(rec.get("sections", [])):
        if sec.get("label") == MODEL_LABEL:
            continue
        keep = []
        for it in sec.get("items", []):
            if isinstance(it, dict) and is_base_model_release(it.get("title") or ""):
                target = next((s for s in rec["sections"] if s.get("label") == MODEL_LABEL), None)
                if target is None:
                    target = {"label": MODEL_LABEL, "color": MODEL_COLOR, "items": []}
                    rec["sections"].append(target)
                target["items"].append(it)
                moved.append((sec.get("label"), it.get("title")))
            else:
                keep.append(it)
        sec["items"] = keep
    for sec in rec.get("sections", []):
        for i, it in enumerate(sec.get("items", []), 1):
            if isinstance(it, dict):
                it["seq"] = i
    if rec.get("meta") is not None:
        rec["meta"]["total"] = sum(len(s.get("items", [])) for s in rec.get("sections", []))
    return moved


def main():
    dry = "--dry-run" in sys.argv
    arch = json.load(open(ARCH, encoding="utf-8"))
    total_moved = 0
    report = []
    for date in sorted(arch.keys()):
        rec = arch[date]
        moved = reroute_model_release_items(rec)
        if moved:
            total_moved += len(moved)
            for old_label, title in moved:
                report.append((date, old_label, title))
    if dry:
        print(f"[DRY-RUN] 将移动 {total_moved} 条：")
        for date, old_label, title in report:
            print(f"  {date}  [{old_label}] -> {MODEL_LABEL}  {title}")
        return
    # 备份（格式对齐 generate_archive.save_archive：ensure_ascii=False、默认分隔符，避免整文件重写造成巨大 diff）
    bak = ARCH + ".bak_reroute"
    json.dump(json.load(open(ARCH, encoding="utf-8")), open(bak, "w", encoding="utf-8"),
              ensure_ascii=False)
    json.dump(arch, open(ARCH, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"已移动 {total_moved} 条；原文件备份于 {bak}")
    for date, old_label, title in report:
        print(f"  {date}  [{old_label}] -> {MODEL_LABEL}  {title}")


if __name__ == "__main__":
    main()
