# Findings

- 用户截图的 /history 侧栏把13来源硬塞一排，文本压缩/换行失读，且页面有水平滚动条。
- / 默认search，进入 /history 又见全局keyword/date、session内查找与Roles/Theme；主次重复。
- 现有reuse.projects已跨来源聚合，但timeline会对每项提取audit，不适合纯阅读目录。增加共享轻量sessions列表，保留revision-bound分页。
- 项目归属继续以完整cwd为准；同目录不同来源合并会话目录，同ID必须保留source/system/store身份。
- 审计、续接命令、显示偏好均需保留，但不应占据初始对话视口。

## Review and browser evidence

- 读图和实现后审查确认两类真实导航不兼容：旧项目列表请求40条，但共享projects上限20；共享projects只有next_cursor，没有has_more。已修正真实接口参数和续页回归（20+1），未扩大旧资源预算。
- 设置禁止存储时，旧主题监听器导致pressed与实际主题冲突；设置对话框现在独占偏好控件。健康重检失败后旧刷新卡片序号失效导致loading不结束；刷新以可见且仍挂载的卡片生命周期判定。两项用真实两个脚本共同运行的Node shim复现并修复。
- 浏览器合成验收：默认首页7个项目；/fixture/repo点击即打开CBC，左栏统一CBC/Copilot/pi三会话；来源切换打开Copilot，Back恢复CBC；全局localneedle检索点击assistant消息定位到message=1，未出现旧Keyword/日期栏。
- 设置：深色+16px即时生效、重载保留、Escape关闭焦点回到设置按钮；来源页13来源状态/真实配置路径，CBC刷新返回可用状态；420/480px无页面横向溢出，420px读对话自动折叠目录且可重新展开。均只用work/project-reader-acceptance的合成数据，没有上传/导出真实历史。
- 1280×820 桌面复验：document/body scrollWidth 均为1280，目录和正文双栏；设置恢复默认后浅色14px、审计/会话信息折叠，初始视口呈现对话。
- 用量/简报中的跨项目会话跳转统一走阅读导航，同步项目、来源、列表和URL，刷新后仍可恢复；专门回归验证，避免只换右侧正文而保留旧项目目录。
- 最终独立审查复现双来源同时刷新时旧卡片被替换、后完成来源状态残留的问题；成功/失败均重读当前可见状态，旧按钮不操作新卡片。新增6种并发/关闭/切分类结果测试，关闭后不发隐藏健康检查。
