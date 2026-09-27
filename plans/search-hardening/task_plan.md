# Search hardening（CapMesh 加固轮）

## Goal
检验"用户搜索本地历史能否找到约定范围内的真实命中并跳到同一来源同一修订的正确消息；
故障时明确说明并恢复"。只审查与补复现证据，不改产品实现。

## Scope
mutation（验证对抗）+ browser（检索链路 QA）；三故障簇上限；合成数据。

## Plan
- [x] S1 事实边界与基线（HEAD/脏文件/哈希/端口/437+9 基线）
- [x] S2 独立预期（oracle.md 九不变量+预期表）与合成 fixture/manifest
- [x] S3 实验登记与执行（mutation detected / browser pass，预算内）
- [x] S4 缺陷报告 + 六维度声明（findings.md）

## Acceptance
每项结论有 planted/reached/responsible_check 或 target_operation/oracle/fault_hit/recovery
证据；不再把实现现状抄成预期；未定义行为归 contract_gap。

## Next Step
本轮补证完成，见 [closure/report.md](closure/report.md)。G1/G2 已声明当前行为；若要改变匹配或排序能力，另立产品任务。U1 仍待安排。

## Status
完成（本轮）。实验记录：experiment.json（mutation）、experiment-browser.json（browser）。

## Closure round — 2026-09-27

用户授权完成剩余验证加固；产品实现与既有 tests/ 保持不变。旧实验/绑定产物不覆盖。

- [x] C1 参数化新版 fixture、完整身份/正文/状态断言、字面负例及反向校验。
- [x] C2 冻结完整源码与合成来源、绑定浏览器新证据范围。
- [x] C3 真实点击/返回换词、索引变化后翻页、来源故障恢复。
- [x] C4 独立复审、当前契约说明与交付记录。

采用 Obsidian/Wiki/自动化开发范式与智能体协作.md 中验收依据原则：按实际行为给结论，不把静态或接口通过替代浏览器交互。
