# Findings

- qiao-wechat 的 MediaAsset 是图片资源，不是成果叙事；ArticleCreate 接收 Markdown，但没有稳定导入身份。因此本轮使用内容仓 Markdown 交接，不改发布服务。
- 内容仓实际位置：/home/muqiao/桌面/obsidian/xueyu-gongzhonghao，自动化边界为公众号/；新素材目录为公众号/素材/History-Viewer。现有草稿/待发布扫描不会自动消费此新目录，人工整理成文章后才进入原流程。
- evidence.selection_bundle 已核对修订并脱敏，限制 5 条 / 8000 字符；初始实现仅支持文件来源；后续四来源交接已扩展到 CBC/mcode/可解码 AGY/ZCode，仍以各来源的快照与修订支持范围为准。
- UI 沿用 workspace 的字体、主题和按钮，选证据后展开素材表单；只保留一条“填写→预览→导出”路径，不新增首页导航。

- 原子发布使用同目录临时文件写完并 fsync 后 hard-link，新建冲突只比较内容，不替换文件；目标目录/目标文件拒绝 symlink，非普通文件拒绝读取。
- 新写接口要求 loopback Host、JSON 和同源 Origin，防止普通跨站表单及非本地域名重绑定调用。
- 素材标题/叙事和历史文本放在自适应 Markdown 围栏内，避免历史 HTML/围栏内容被作为结构执行。
