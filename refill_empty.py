#!/usr/bin/env python3
"""
refill_empty.py —— 为 archive.json 中「正文为空/过短」的条目回填源站正文。

背景：generate_archive.fetch_content 原先对「原始 HTML 含 captcha/cf-chl 等字样」就判为反爬墙，
      而真实文章页 <head> 常嵌 bot 防护脚本，trafilatura 已正确抽出 <body> 正文却被误杀成空，
      导致大量空正文缺口。本脚本复刻「修复后」的 fetch_content 逻辑：trafilatura 成功抽出正文即
      信任，不再被 raw-HTML 反爬标记误杀；仅正则降级路径保留反爬/登录墙判定。

用法：
    python refill_empty.py            # 正式回填并写盘（写盘前自动备份 archive.json.bak）
    python refill_empty.py --dry-run  # 只统计可回填条数，不改动

注意：
    - 自包含，不 import generate_archive.py（避免无 __main__ 守卫触发全量构建污染 archive.json）。
    - 需联网抓取源站（运行环境需放开网络沙箱）。
    - X/Twitter 等无法抓取的源会被跳过，正文保持空（属正常）。
"""
import json, re, ssl, sys, os, shutil, urllib.request

ARCHIVE_PATH = "archive.json"
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

try:
    import trafilatura
    _HAVE_TRAF = True
except Exception:
    _HAVE_TRAF = False

# 反爬/登录墙识别（仅用于「正则降级路径」，trafilatura 成功时不使用）
_BLOCK_HTML = ["EO_Bot_Ssid", "__tst_status", "location.href=location.href.replace",
               "Just a moment", "Checking your browser before accessing",
               "Verify you are human", "enable JavaScript and cookies to continue",
               "DDoS-Guard", "cf-chl", "captcha", "are you a robot"]
_BLOCK_TEXT_STRONG = ["您已在另一个标签页或窗口中登录", "请重新加载以刷新会话",
                      "请启用 javascript 和 cookie", "请输入验证码", "安全验证", "请完成安全验证",
                      # GitHub 登录墙（英文挑战页，trafilatura 抽正文时会混入这些驻留提示）
                      "you signed in with another tab or window",
                      "reload to refresh your session",
                      "you signed out in another tab or window"]
_BLOCK_TEXT_WEAK = ["confirm you are human", "checking your browser",
                    "enable javascript and cookies", "access denied", "verify you are human"]


def _is_blocked_text(text):
    """文本级反爬/登录墙判定（恒生效，不依赖 trafilatura 是否成功）。
    强标记(含中文登录墙与 GitHub 英文登录墙)无视长度直接判废；弱标记仅在正文偏短时判废。"""
    t = (text or "").strip()
    tl = t.lower()
    for m in _BLOCK_TEXT_STRONG:
        if m.lower() in tl:
            return True
    if len(t) < 600:
        for m in _BLOCK_TEXT_WEAK:
            if m.lower() in tl:
                return True
    return False


def _html_has_block_marker(h):
    """原始 HTML 级反爬标记（仅当 trafilatura 失败、走正则降级时使用）。
    真实文章页 <head> 常嵌 bot 防护脚本含 captcha/cf-chl 字样，trafilatura 已正确抽出
    <body> 正文；故该原始 HTML 判定不可在 trafilatura 成功时使用，否则会误杀干净正文。"""
    low = (h or "").lower()
    for m in _BLOCK_HTML:
        if m.lower() in low:
            return True
    return False


def traolid(p):
    if not p:
        return None
    m = re.search(r"/items/([^/?]+)", p)
    return m.group(1) if m else p


def fetch_aihot_body(pid):
    """绕过反爬墙取 AI HOT 已清洗正文（命中挑战页返回 None）。"""
    if not pid or not re.match(r"^[A-Za-z0-9]+$", pid):
        return None
    url = f"https://aihot.virxact.com/items/{pid}"
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Cookie": "__tst_status=3086345129#; EO_Bot_Ssid=1406074880;",
        "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        raw = urllib.request.urlopen(req, timeout=30, context=_SSL_CTX).read().decode("utf-8", "ignore")
    except Exception:
        return None
    if "EO_Bot_Ssid" in raw and "__next_f" not in raw:
        return None
    return None  # 简化：本脚本正文以「回源 trafilatura」为主，AI HOT RSC 交由主流程负责


def fetch_content(url, permalink=None, cap=15000):
    """修复版：优先 trafilatura 抽正文（成功即信任）；失败才走正则降级并判反爬墙。"""
    pid = traolid(permalink) if permalink else None
    if pid:
        aihot = fetch_aihot_body(pid)
        if aihot and len(aihot.strip()) >= 80:
            return aihot[:cap]
    if not url:
        return ""
    html = ""
    last_err = ""
    for _attempt in range(2):  # 重试一次，规避瞬时网络超时导致的漏抓
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"})
            with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as r:
                raw = r.read(5_000_000)
                html = raw.decode("utf-8", "ignore")
            break
        except Exception as e:
            last_err = repr(e)
            html = ""
    if not html:
        return ""
    text = ""
    traf_ok = False
    if _HAVE_TRAF:
        try:
            res = trafilatura.extract(html, output_format="json", include_images=False, url=url)
            if res:
                d = json.loads(res)
                text = d.get("text") or ""
                traf_ok = bool(text)
        except Exception:
            text = ""
    if not text:
        h2 = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", h2)
        text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    # 文本级强标记(含 GitHub 登录墙)恒判废；raw-HTML 标记仅在 trafilatura 失败(走正则降级)时判废，
    # 避免真实文章页 <head> 的 bot 防护脚本(captcha 等)误杀 trafilatura 已抽出的干净正文。
    if _is_blocked_text(text) or (not traf_ok and _html_has_block_marker(html)):
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    return text[:cap]


def ratio_en(s):
    if not s:
        return 0.0
    L = len([c for c in s if c.isascii() and c.isalpha()])
    N = len([c for c in s if not c.isspace()])
    return (L / N) if N else 0.0


def main():
    dry = "--dry-run" in sys.argv
    if not os.path.exists(ARCHIVE_PATH):
        print(f"! 找不到 {ARCHIVE_PATH}（请在 ai-daily 目录下运行）")
        sys.exit(1)
    arch = json.load(open(ARCHIVE_PATH, encoding="utf-8"))
    targets = []
    for dk, rec in arch.items():
        for s in rec.get("sections", []):
            for it in s.get("items", []):
                c = (it.get("content") or "").strip()
                if len(c) >= 80:
                    continue
                u = it.get("url") or ""
                if not u.startswith("http"):
                    continue
                if "x.com" in u or "twitter.com" in u:
                    continue  # 社交平台源不可抓，跳过
                targets.append((dk, it))
    print(f"trafilatura 可用: {_HAVE_TRAF}")
    print(f"候选回填: {len(targets)} 条（content<80 且有可抓 http 源，已排除 X/Twitter）\n")
    filled = 0
    skipped = 0
    for dk, it in targets:
        u = it["url"]
        new = fetch_content(u, it.get("permalink"))
        if new and len(new) >= 80:
            if dry:
                filled += 1
                print(f"  [dry] 可填 {len(new)} 字 | {dk} | {it.get('title', '')[:38]}")
                continue
            it["content"] = new
            # 英文正文需翻译 → zh=False 进队列；中文/混杂 → zh=True
            it["zh"] = (ratio_en(new) <= 0.45)
            filled += 1
            print(f"  已填 {len(new)} 字 | {dk} | {it.get('title', '')[:38]}")
        else:
            skipped += 1
            print(f"  跳过(仍抓不到) | {dk} | {it.get('title', '')[:38]}")
    if dry:
        print(f"\n[dry-run] 未改动 {ARCHIVE_PATH}；预计可回填 {filled} 条，跳过 {skipped} 条")
        return
    if filled == 0:
        print("\n无需回填，archive.json 未改动")
        return
    if not os.path.exists(ARCHIVE_PATH + ".bak"):
        shutil.copy(ARCHIVE_PATH, ARCHIVE_PATH + ".bak")
    json.dump(arch, open(ARCHIVE_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n=== 已回填 {filled} 条，archive.json 已写盘（备份 {ARCHIVE_PATH}.bak）===")


if __name__ == "__main__":
    main()
