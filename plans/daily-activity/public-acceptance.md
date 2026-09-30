# 日活动公开验收边界

消息时间窗口、明确时区、跨来源覆盖与 mcode v2 解析已实现；Web 日期复盘后续由 [web-briefing-window](../web-briefing-window/task_plan.md) 修复。mcode 验收交接后续由 [model-review-handoff](../model-review-handoff/task_plan.md) 接通。

可复验入口：`python3 -m unittest tests.test_activity tests.test_mcode`。覆盖跨日续作、窗外排除、小数秒、DST、来源失败、修订分页、重复录制身份与只读解析。全量回归见 [当前收尾](../history-reuse-product/agent-first-closeout.md)。

原始定点历史定位、基线和本机性能记录保留在本地 acceptance.md、real-smoke.json、verify_real.py 等文件，不随公开仓库上传。它们是旧时点观察，不证明所有来源实时完整。U1/M3 已取消；未运行人类试用、真实模型验收、安装/部署或硬件复测。
