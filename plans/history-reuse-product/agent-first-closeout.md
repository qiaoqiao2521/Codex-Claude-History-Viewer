# 2026-10-01 Agent 对接优先收尾

## 范围

用户取消 U1/M3；当前计划、README、PROJECT 与关联进度同步。旧试用材料保留为非执行模板，冻结报告不改为通过。合并已有四来源验收交接、mcode Web 接入与本地成果素材导出，沿用已有授权；不发布版本、替换安装或重启用户服务。

## 验证

本轮 `python3 -m unittest discover -s tests`：558 项，557 passed / 1 skipped（外部 reader 未配置）；九套 `tests/test_*.js` 全部通过。改动 JS 语法、Python 编译与 `git diff --check` 通过。暂存区另导出至干净临时目录，558 项 Python（1 skip）和九套 JS 再次通过，确认不依赖本地保留文件；公开 Markdown 相对链接检查无缺失，凭据模式扫描无命中。旧浏览器证据见 model-review-handoff/acceptance.md 与 outcome-materials/progress.md，本轮未重新进行浏览器验收。

## 保留项与接续责任

接续 owner 均为根 Codex；保持本地原文件，不删除或上传：

- `plans/daily-activity/` 中除 task_plan.md / public-acceptance.md 外的原始记录：包含真实会话身份、定位、私有路径或对应测量。公开内容使用无身份摘要；若需继续发布，先从 acceptance.md 与 verify_real.py 定点核对并制作脱敏副本，不重扫历史。
- `plans/specmesh-r001-validation/`：原计划明确不提交实验 fixture/Harness 产物，含本机实验材料。入口 task_plan.md / progress.md；需要复用时先按原授权区分公开规范与本地证据。
- `plans/ubuntu-keyboard-recovery/`：桌面恢复仍待实际键盘输入确认；入口 progress.md，接续需用户真实输入反馈，不能以此次测试冒充硬件/桌面验收。
- `agents/controlmesh_typescript_migration_plan(1)..md`：历史 CM 迁移提案，未核对当前 CM 实现；保留参考，未来在 CM 仓库核对当前计划后才考虑归档发布。
- `plans/search-hardening/*.json.lock`：运行时锁文件，不入库，不在不确定持有者时删除。

这些保留项不阻塞本次 Agent 对接源码与取消 U1/M3 的文档交付；不是声称所有历史实验均已验收。
