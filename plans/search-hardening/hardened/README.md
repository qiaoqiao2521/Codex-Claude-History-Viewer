# 修正后的独立检索验证资产

范围：只补合成复放材料及验证断言，不修改产品实现或 `tests/`。旧 `evidence/`、oracle、实验 JSON 和绑定报告均保持原样。这里不是回填原实验 attempt，也不改变各 1/3 的登记预算。

## 重放

工作目录为仓库根，以下 `RUN` 必须是不存在的临时目录，`LOGS` 也必须不存在。全套仅使用 Python 标准库。

入口先把 `self_test.py`、`build_fixture.py`、`manifest_spec.py`、`probe.py` 四个脚本复制到本轮 `run-root/verifier/`，校验复制字节并设为只读，再启动冻结的 `self_test.py` 执行全部步骤。每个子命令都指向这份冻结副本，不从工作树动态加载验证脚本。

```bash
python3 plans/search-hardening/hardened/self_test.py \
  --repo /absolute/path/to/frozen/source \
  --run-root /tmp/hv-hardened-new-run \
  --logs /tmp/hv-hardened-new-logs
```

生成器和索引/查询阶段也可单独运行：

```bash
python3 plans/search-hardening/hardened/build_fixture.py --root /tmp/hv-new-fixture
python3 plans/search-hardening/hardened/probe.py --repo /absolute/path/to/source \
  --root /tmp/hv-new-fixture --cache /tmp/hv-new-cache --setup
python3 plans/search-hardening/hardened/probe.py --repo /absolute/path/to/source \
  --root /tmp/hv-new-fixture --cache /tmp/hv-new-cache
```

`--setup` 是唯一显式索引阶段；之后查询不会 scan。setup 把保留的 parser_version 设为 1，search_blob 截至 2,000,000 字符。该实验模拟**现有 schema 中的旧版本有界缓存**，不声称覆盖全部历史发行版 schema 迁移。

## 独立预期

`manifest_spec.py` 不导入产品模块；会话身份、消息位置和正文来自这里的固定构造。store_id 按独立声明的协议计算：UTF-8 JSON `[system, source, resolved source root]` 的 SHA256（ensure_ascii=False，默认 separators）。不是调用产品 API 生成答案。

19 个场景覆盖：

- 跨来源同名 ID，完整 `(system, source, store_id, id)`，数量与分页去重。
- 单消息 2M 之后的中英文命中、8192 之后的命中；摘录正文、role、绝对 index、truncated 均精确相等。
- context 排除但消息编号仍计入；跨消息 AND；无命中和 metadata-only 的不同状态。
- `%`、`_`、反斜杠均含正例与相似干扰反例。
- G1：`CAFÉ` 不匹配 `Café café`，`café` 匹配；G2：五条早期单词匹配时返回前 3 条，2106 的完整短语不入摘录。**只固定当前可观察口径，不决定改成 Unicode casefold 或短语优先。**
- 查询异常要给 errors+partial；摘录异常要给 snippet_status+partial；正常返回 errors=[]、partial=false。
- 25 条 `paginationneedle`，按 page-24 到 page-00，20+5 页无重复。

完整短语的 2106 位置在查询前另读缓存核对；时间通过 datetime+timedelta 生成，并逐行用 datetime.fromisoformat 验证，35 个文件、2184 个合法时间戳。

查询阶段保存/比较完整 SQLite 序列化字节哈希、total_changes、reader_state、parser_versions、源 JSONL 哈希。SQLite authorizer 拒绝写操作，并记录被吞掉的写尝试；scan mock 既抛错又检查 call_count，防止吞错造成假绿。

## 探针自己的负向验证

`self_test.py` 顺序运行控制组、8 种错误、恢复后的控制组。每个负例必须 **exit=1 且含预期断言**，不以任意崩溃或超时冒充检出：

| 注入 | 必须失败的断言 |
| --- | --- |
| 错 source | 完整身份 source |
| 错 store_id | 完整存储身份 |
| 错摘录正文 | snippets 精确比较 |
| 错 snippet_status | 状态精确比较 |
| 错 partial | 所有响应的 partial |
| 伪造 errors | 所有响应的 errors |
| 少一条结果 | 数量/分页 |
| 去掉 `_` 转义 | literal_underscore 数量，干扰会话不能命中 |

注入全是单进程 monkeypatch/返回对象变更；每次新进程启动，无产品源码改写。最终小日志见 [verification-v3/summary.json](verification-v3/summary.json)，记录命令、退出码、诊断、日志哈希、产品运行源码前后哈希，并绑定：

- 四个验证脚本的原始路径、冻结执行路径、各自运行前后 SHA256；实际 driver 路径单列。
- 生成后、索引前的 `manifest.json` 与 `source-hashes.json`，以及全部查询结束后的同两份文件；记录绝对路径和 SHA256。
- 两份小型 fixture 文档的归档副本及其 SHA256，保存在 v3 日志目录，便于核对当时实际使用的预期和源文件清单。

产品源码、验证脚本或 fixture 文档任一前后变化都会使整轮以非零退出。v3 控制组前后均 19/19 通过，8 个错误注入均以指定断言失败；四类 `*_unchanged` 均为 true。运行数据与冻结验证脚本位于 `/tmp/cchv-hardened-final-replay-v3-20260927`，产品来源仍为 `/tmp/hv-search-closure-20260927/source`。

`verification/` 与 [verification-v2/summary.json](verification-v2/summary.json) 原样保留：首次运行已通过，v2 增加“scan 异常即使被吞也计数”和旧缓存构造前置检查；v3 补上验证资产自身与实际生成清单的绑定，不倒填前两次记录。

初次调试的独立清单把中文摘录前面的 x 算成 57；应为 `70 - len('after2mneedle ') = 56`。当时探针 18/19 报失败，修正清单后重新生成新 fixture，未改变产品。这项算术更正及其影响也写在 [浏览器交接](BROWSER-HANDOFF.md)，没有改动已交付浏览器的 JSONL。

## 浏览器 fixture

独立生成 `/tmp/hv-search-closure-20260927/fixture` 已交给父任务。该来源数据与本 oracle 重放分开；运行 app 时用隔离 HOME、显式来源根/缓存/端口，并绑定完整运行源码快照。

真实点击、索引变化后点击下一页以及来源降级/恢复由父任务的浏览器报告提供；本目录的 Python 探针通过不等于这些浏览器动作通过。
