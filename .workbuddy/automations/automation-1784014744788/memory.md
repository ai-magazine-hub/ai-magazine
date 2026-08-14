# automation-1784014744788 — AI HOT 每日日报刷新

## 2026-07-16 07:50 (GMT+8)
- 状态：部分成功（数据无新增 + 渲染补偿完成），上游网络不稳定
- 完整运行 generate_archive.py 在 backfill/translate 网络阶段挂死：进程 CPU 0%、3 个到 Google IP 的 CLOSE_WAIT 套接字，已 SIGKILL。
- 直接复核 dailies API 返回 HTTP 520（CDN 上游 "Origin Return Unknown Error"），确认 AI HOT 接口/翻译上游当前不稳。
- 增量结果：本次新增 0 期（API 未返回 2026-07-15 / 2026-07-16，最新仍 2026-07-14）；archive.json 累计 84 期（无内容变化，仅被重存）。
- 补偿：因渲染步骤未执行，改用 `--render-only` 从本地 archive.json 重渲染，成功写出 84 个日报 HTML + 重建 index.html + ai-daily.html 重定向（08:01）。
- 结论：HTML 交付物已就绪；暂无新一期可抓；上游恢复后下次定时运行应能正常增量（届时预期新增 07-15 等）。
- 注：未超过一次重试限制（仅一次完整运行即挂死，render-only 不触发网络，不算重试）。

## 2026-07-19 07:53 (GMT+8)
- 状态：成功（无新增内容，全量重渲染 + 索引重建）
- 完整运行 generate_archive.py：dailies 接口正常返回 88 期（最新 2026-07-18 … 最早 2026-04-22），上游网络已恢复稳定。
- 增量结果：本次新增 0 期；archive.json 累计 88 期（无内容变化，仅重存/重渲染）。
- 2026-07-19 补抓返回 HTTP 404 —— 今日日报尚未发布（符合预期，非错误）。
- items 时间补全 2000 条（翻 20 页）；回填 152 条（已缓存 142，新落盘 10）；无待翻译项；排版整理 7 条。
- 写出 88 个日报 HTML + 重建 index.html（88 期）+ ai-daily.html 重定向入口。
- 结论：交付物就绪；今日无新一期可抓，待上游发布 07-19 后下次定时运行应可正常增量。

## 2026-07-23 07:50 (GMT+8)
- 状态：成功（无新增内容，全量重渲染 + 索引重建）
- 完整运行 generate_archive.py：dailies 接口正常返回 92 期（最新 2026-07-22 … 最早 2026-04-22），上游网络稳定。
- 增量结果：本次新增 0 期；archive.json 累计 92 期（无内容变化，仅重存/重渲染）。
- 2026-07-23 补抓返回 HTTP 404 —— 今日日报尚未发布（符合预期，非错误）。
- items 时间补全 2000 条（翻 20 页）；回填正文 0/86；英文→中文翻译 0/3（其余 zh=False，下次续传）；排版整理若干。
- 写出 92 个日报 HTML + 重建 index.html（92 期）+ ai-daily.html 重定向入口。
- 结论：交付物就绪；今日无新一期可抓，待上游发布 07-23 后下次定时运行应可正常增量。

## 2026-08-14 07:50 (GMT+8)
- 状态：成功（修复 latent bug 后重跑，正常增量 1 期，并已推送到 origin 锁定）
- 首次运行在 merge_today_feed 阶段崩溃：`NameError: name 'reroute_model_release_items' is not defined`。根因：2026-08-13 新增的 reroute 逻辑（常量 `_PRODUCT_TOOL_KW`/`_MODEL_FAM_VER_RE`/`_MODEL_RELEASE_TYPE_STRICT`/`_RELEASE_NOT_KW`/`_REROUTE_ACT` + 函数 `is_base_model_release`/`reroute_model_release_items`）被追加在文件**末尾(3968-4051)**，而管道顶层代码在 2502 行就执行 → 调用时名字未绑定。此前未跑过带新日期的完整管道，故首次触发。
- 修复：用脚本把该 reroute 定义块整体移至管道起点(2502)之前；`is_pure_model_release`/`compute_gantt` 及其常量留原位（render 阶段仍可用）；`_sec_color`(2636) 等延迟解析名字，调用时已绑定。py_compile 通过。
- 重跑成功：dailies 返回 115 期（2026-08-14 … 2026-04-22，本次 08:05 上游已发布 08-14；首跑 07:50 时 404 未发布）。增量新增 1 期（2026-08-14）；累计 115 期。merge_today_feed 为 2026-08-13 补实时流并重分类基础模型发布 → 模型发布/更新；回填/翻译/排版若干。
- ⚠️ 插曲：成功运行后每小时同步 cron(:07) 执行 `git reset --hard origin/main`，把未提交的修复与 115 期数据回滚（generate_archive.py 退回 bug 版、archive.json 退 114，仅孤立 ai-daily-2026-08-14.html 残留）。按 SOP「对齐远端后重放修复」：重新应用 reroute 排序修复 → 重跑重建一致态(115 期) → commit → `git push origin main`(5153933..ab6ef50) 锁定。现 origin/main 已含修复与 115 期数据，后续 cron `reset --hard` 不再回滚。
- 最终校验：archive.json 115 期=HTML 文件数=index 唯一链接数；冲突标记 0；本地与 origin 零分歧。该 bug 已根治，后续定时运行不会再触发 NameError。
- 注：本自动化 memory.md 也会被 cron reset 回滚，故关键修复须 push 到 origin 才持久；本条目为重新补记。
