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

# 翻译 key：优先 ~/.dskey（持久，家目录不会被系统清理）；回退 /tmp/dskey（可能已被 /tmp 清理机制删除）；
# 两者皆无 -> 退化为不翻译（CI 会用 GitHub secret 补全）。
if [ -f "$HOME/.dskey" ]; then
  export DEEPSEEK_API_KEY="$(cat "$HOME/.dskey" 2>/dev/null)"
  TRANS_ARGS=""
elif [ -f /tmp/dskey ]; then
  export DEEPSEEK_API_KEY="$(cat /tmp/dskey 2>/dev/null)"
  TRANS_ARGS=""
else
  TRANS_ARGS="--no-translate"
fi

echo "$(date) === sync start ===" >> "$LOG"

# 0) 清理上次可能遗留的 autostash（rebase 卡死的根因：autostash 把冲突标记写进 archive.json 并随 commit 入库）
git stash drop 2>/dev/null || true
# 1) 直接对齐干净远端，丢弃任何本地独有提交/未提交 diff（根治「本地偏离 origin 导致 rebase 冲突」）。
#    远端 CI 与本机会重新生成，丢弃本地内容不影响最终数据，仅用于彻底对齐 origin。
git reset --hard origin/main >> "$LOG" 2>&1 || true
# 2) 再拉最新（此时本地已等于 origin，fast-forward，不再冲突）
git pull --rebase --autostash origin main >> "$LOG" 2>&1 || true

# 2b) 安全护栏：若 archive.json 期数异常偏少（疑为加载损坏被静默重建），从 .bak 恢复并跳过本轮推送，避免冲掉历史
BEFORE_N=$(grep -o '"2026' archive.json 2>/dev/null | wc -l | tr -d ' ')
if [ "$BEFORE_N" -lt 30 ] && [ -f archive.json.bak ]; then
  cp archive.json.bak archive.json 2>/dev/null
  echo "$(date) archive 期数异常($BEFORE_N)，已从 .bak 恢复，跳过本轮" >> "$LOG"
  echo "$(date) === sync done (recovered) ===" >> "$LOG"
  exit 0
fi

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
  # 工作区可能残留 html/archive/ratings 重渲染 diff，全部丢弃以保持干净
  # （否则这些整文件重写的残留改动会在下次 pull 时与 origin 冲突，重演 rebase 卡死）
  git checkout -- "ai-daily-*.html" index.html ai-daily.html archive.json ratings_cache.json ratings_code_cache.json 2>/dev/null || true
  echo "$(date) no change, skip push" >> "$LOG"
fi
echo "$(date) === sync done ===" >> "$LOG"
