#!/bin/bash
# AI HOT 日报本地定时同步（launchd 触发，每小时 :07 跑一次）
# 作用：彻底绕开 GitHub Actions schedule 不可靠的问题——由本机主动增量抓取并推送。
# 行为：仅当 archive.json 真变化（新增日期/条目/时间补全）才提交推送；
#       推送会触发 GitHub Actions 用官方 DEEPSEEK_API_KEY 补全翻译，故本脚本无需持有 key。
set -u

REPO=/Users/xiaosongguo/ai-daily
PY=/Users/xiaosongguo/.workbuddy/binaries/python/versions/3.13.12/bin/python3
LOG="$REPO/sync_cron.log"

# launchd 默认 PATH 很精简，显式补全以保证 git/python 等可用
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

cd "$REPO" || { echo "$(date) cd $REPO fail" >> "$LOG"; exit 1; }

# —— 文件锁：防止与手动重翻译任务并发写 archive.json ——
# 取代原先「unload 暂停定时」的做法：mkdir 原子创建锁目录，持有即独占；
# 另一实例检测到锁目录存在则直接跳过，从机制上杜绝「unload 后忘 reload」导致定时停摆。
# 手动做全库翻译时无需再 unload，launchd 到点触发会自动让行。
LOCKDIR="$REPO/.sync.lock"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "$(date) another sync instance running, skip" >> "$LOG"
  exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT INT TERM

# 翻译 key：优先 /tmp/dskey；macOS 重启后 /tmp 会被清空 -> 退化为不翻译（CI 会补全）
if [ -f /tmp/dskey ]; then
  export DEEPSEEK_API_KEY="$(cat /tmp/dskey 2>/dev/null)"
  TRANS_ARGS=""
else
  TRANS_ARGS="--no-translate"
fi

echo "$(date) === sync start ===" >> "$LOG"

# 1) 先拉最新，避免长期落后导致 rebase 冲突
git pull --rebase --autostash origin main >> "$LOG" 2>&1 || true

# 2) 记录 archive 内容基线（hash-object 只看内容，不受工作区其他 diff 干扰）
BEFORE=$(git hash-object archive.json 2>/dev/null)

# 3) 增量生成（已生成的日期跳过；无 key 时自动跳过翻译）
"$PY" generate_archive.py $TRANS_ARGS >> "$LOG" 2>&1 || true

# 4) 仅当 archive 真变化才提交推送（避免 html 里相对时间字段造成无意义 diff 刷屏）
AFTER=$(git hash-object archive.json 2>/dev/null)
if [ "$BEFORE" != "$AFTER" ]; then
  git add archive.json index.html ai-daily.html "ai-daily-*.html" ratings_cache.json ratings_code_cache.json
  git commit -m "chore: 定时同步 AI HOT 日报（$(date -u +%Y-%m-%dT%H:%M:%SZ)）" >> "$LOG" 2>&1 || true
  if ! git push origin main >> "$LOG" 2>&1; then
    git pull --rebase --autostash origin main >> "$LOG" 2>&1
    git push origin main >> "$LOG" 2>&1
  fi
  echo "$(date) synced (archive changed)" >> "$LOG"
else
  # 工作区可能残留 html 重渲染的相对时间 diff，丢弃以保持干净（代码改动走 push 触发 CI 重渲染）
  git checkout -- "ai-daily-*.html" index.html ai-daily.html 2>/dev/null || true
  echo "$(date) no change, skip push" >> "$LOG"
fi
echo "$(date) === sync done ===" >> "$LOG"
