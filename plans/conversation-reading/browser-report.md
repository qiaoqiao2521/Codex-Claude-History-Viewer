# 浏览器验收记录 — 2026-09-27

范围：Linux 隔离 IAB、`127.0.0.1:8844`、`build_fixture.py` 的合成数据。日常 Chrome 共享代理已阻断，未重启或绕过授权。未操作用户 8787/8895 服务。预期先写于 `browser-oracle.md`。

## 实际交互

| 场景 | 观察 |
| --- | --- |
| 同项目跨源同 ID | Codex/Claude shared-session 成组，另一个标题独立，原始行共 3 |
| 原生键盘开关 | summary Enter 后 open=null，Space 后 open=""；全部 3 行仍在 |
| 关闭归组 | details 数为 0，会话行仍为 3 |
| 关键消息 | Codex 节点固定为 1、2、4、5、6；context 0 与工具输入 3 不列为节点 |
| 真实点击失败链接 | 普通 click，未用 force 或脚本导航；URL message=4，显示“已定位消息 4”，工具正文含 `Error: LoginExpired — tests failed（合成旧失败）` |
| 同 ID 切来源 | 切 Claude 后旧面板隐藏、链接数 0；重新展开仅 Claude 用户请求和失败/最后回复 2 条，无 Codex 复测 |
| 跨页完整性 | 50/51、50 行 → 点击“更多对话” → 51/51、51 行；完整 system/source/store/id 去重数 51 |
| 420×840 阅读 | 最终面板约 235.19px 高；document clientWidth=scrollWidth=420；真实点击仍展开正确失败原文 |
| 420px 会话目录 | 打开目录后 clientWidth=scrollWidth=420，组标题换行并可滚动 |
| 最终桌面回查 | 3 个会话、5 条正确节点；本轮新标签捕获 error/warn 为 [] |

## 发现与修复

1. 静态独立审查：新增 parent 参数被 `forEach` 下标覆盖，置顶渲染报错；改显式闭包，补旧模式和关闭归组回归。
2. Handler 集成测试：缺失修订被统一错误映射误判为 409；明确作为 400，真实 stale 仍 409。
3. 浏览器：工具深链内存展开但 DOM 未重绘，位置正确而正文隐藏。根因不是最初猜测的偏好覆盖；修复在滚动路径先展开、重绘，再找新节点。新测试在隔离旧实现上 exit=1（指定 DOM 展开断言），修复后通过。
4. 窄屏：导航放标题区内被 flex 压缩。最终移到标题区下方，独立滚动且 max-height=28dvh；复验尺寸与实际点击。

桌面归组/分页验证先完成，随后仅调整 HTML/CSS 面板位置并复验窄屏、真实跳转和桌面节点。`runtime-before.json` 为早期调试快照；`runtime-final-before.json`/`runtime-final-after.json` 绑定最后布局复验窗口，不倒称覆盖更早操作。截图和浏览器调用输出在本任务工具记录中；IAB 不支持内容导出，未伪造磁盘截图或自动化录像。此文件为人工整理观察。

## 自动回归及边界

- Python：480 项，479 通过、1 跳过；原始输出 `evidence/python-tests.txt`。
- JS：9/9 套件通过；`evidence/js-tests.txt`。
- `node --check static/app.js`、`git diff --check` 通过。
- 未宣称真实私有历史、全来源浏览器矩阵、独立用户 U1、Windows/WSL 验收。原生无兼容消息索引来源的 unsupported 由 Handler 临时 SQLite 测试验证。
- 未提交、未发行、未更换现有安装；本轮临时服务与标签在收尾时停止/关闭。
