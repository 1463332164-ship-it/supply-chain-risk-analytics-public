# Supply Chain Risk Analytics｜供应链异常分析台

把需求、库存和采购订单转成可核查的供应链风险：先判断哪些 SKU／仓库可能出现库存缺口、哪些订单已延期，再沿逐日库存曲线和证据台账核对原因、讨论补货或催交。固定 AI 草稿辅助提出核查问题；系统不自动采购，也不把假设当作已验证根因。

**全部使用自建模拟数据：30 个 SKU、3 个仓库、180 天需求，合计 90 个 SKU／仓库组合。** 没有真实企业数据、部署案例或降本业绩。项目使用 Python 标准库与离线 HTML/CSS/JavaScript，设计、实现及测试有 Codex 辅助。

## 先看演示

**[在线展示首页](https://1463332164-ship-it.github.io/supply-chain-risk-analytics-public/)** · [基准分析](https://1463332164-ship-it.github.io/supply-chain-risk-analytics-public/base.html) · [固定 AI 草稿](https://1463332164-ship-it.github.io/supply-chain-risk-analytics-public/base_ai.html) · [组合压力](https://1463332164-ship-it.github.io/supply-chain-risk-analytics-public/combined.html)

建议用两分钟看一个问题：打开基准页，筛选 SKU001 / WH1，查看短缺发生日与后续到货；再切换组合压力页比较风险变化，最后展开证据与 AI 草稿，区分计算事实、待核实原因和人工决策。

下载任一 HTML 后用 Chrome 打开，可断网使用，不需要服务器、Python 或 API 密钥。仓库页面可能显示 HTML 源码，应先下载文件。单页可独立分析；如需离线跨页导航，请下载整个 `examples/showcase/` 目录，保持四个 HTML 的文件名和相对位置不变。

| 页面 | 内容 | 证据条数 |
|---|---|---:|
| [基准分析](examples/showcase/base.html) | 核心指标、库存与采购异常，无 AI 草稿 | 119 |
| [基准与固定 AI 草稿](examples/showcase/base_ai.html) | 相同业务结果，附 4 条待人工审核建议 | 119 |
| [组合压力](examples/showcase/combined.html) | 需求增加 25%，有效到货及新增采购交期延后 7 天 | 171 |

筛选仓库、SKU 和风险范围后，点击库存行的“查看”，可交互查看逐日需求、到货、净余额和日期明细，展开原始 JSON，下载当前筛选对应的 CSV。证据与 AI 区域默认折叠，展开后保留完整原值、来源和解释。更多信息见 [演示说明](examples/showcase/README.md)。

## 业务分析与结果

面向计划、采购及供应链分析岗位，项目把三个日常问题放到同一条可追溯流程中：优先核查哪些库存缺口、哪些延期订单需要跟进、补货建议基于什么数据。对工业工程与解决方案岗位，它展示了从业务口径、数据校验、规则计算到交互呈现和验收边界的实现过程；尚未测量真实业务中的效率或收益改善。

实现分工：`scai/data.py` 校验并固定输入快照 → `scai/analysis.py` 计算预测与风险 → `scai/artifacts.py` 校验输入指纹与运行产物一致性 → `scai/dashboard.py` 输出离线看板；可选的 `scai/ai.py` 校验固定草稿，人工再通过 CLI 留存审核决定。

流程包括：三表数据校验 → 三种需求预测基线与时间回测 → 逐日库存推演 → PO 延期、库存缺口及覆盖过高的证据台账 → 规则补货建议 → 可选 AI 草稿校验与独立人工审核。

| 情景 | 参数 | 预计缺口组合 | 建议补货组合 |
|---|---|---:|---:|
| 基准 | 需求倍率 1，延后 0 天 | 17 | 21 |
| 需求 +25% | 需求倍率 1.25，延后 0 天 | 29 | 35 |
| 到货及交期 +7 天 | 需求倍率 1，延后 7 天 | 42 | 45 |
| 组合压力 | 需求倍率 1.25，延后 7 天 | 69 | 74 |

缺口与补货分别判断：基准有 4 个组合在预测期内没有净缺口，但仍建议补足安全缓冲。SKU001/WH1 的基准 D3 净余额为 −15，D6 到货 128、净余额 59；组合压力 D2 净余额为 −3，D13 到货 128、净余额 −105。

这些是模型与模拟数据的结果，不代表已发生的缺货损失、实际采购或企业收益。延后情景同时改变到货、交期和观察窗口，不能解释成单一因素的因果效果。完整定义见 [数据与指标](docs/DATA_AND_METRICS.md)。

## 本地运行

当前验证环境为 Windows、Python 3.12；核心无第三方 Python 包。先在项目根目录确认 `python --version` 指向 Python 3.12。Node.js 仅供可选的 JavaScript 逻辑测试，日常分析和 HTML 展示不需要它。

下面各个输出目录必须尚不存在，包括空目录；重复执行时换一个新编号。`generate`、`analyze` 必须显式传入 `--out`，没有覆盖选项。输入与输出不得相同或互为父子目录。

直接分析已附模拟数据：

```powershell
python -m scai analyze --data data/demo --out runs/quickstart_01/base
python -m scai validate-ai --run runs/quickstart_01/base --data data/demo --response examples/ai_response_codex.json --out runs/quickstart_01/base_ai
```

用 Chrome 打开生成的 `runs/quickstart_01/base/dashboard.html` 或 `runs/quickstart_01/base_ai/dashboard_ai.html`。这两条命令不需要个人审核文件，也不会调用外部大模型 API。

从生成数据开始复现：

```powershell
python -m scai generate --out runs/from_scratch_01/data
python -m scai analyze --data runs/from_scratch_01/data --out runs/from_scratch_01/base
python -m scai validate-ai --run runs/from_scratch_01/base --data runs/from_scratch_01/data --response examples/ai_response_codex.json --out runs/from_scratch_01/base_ai
```

默认种子为 20261018，生成字节应与附带模拟输入一致。更换 `--seed` 后，原固定 AI 响应可能不匹配，需针对新证据包生成响应再校验。

复现四情景、重复基准及可选 AI 校验：

```powershell
python scripts/audit_scenarios.py --out runs/scenarios_01 --response examples/ai_response_codex.json
```

## AI 与人工审核

[固定 AI 响应](examples/ai_response_codex.json) 是预先保存的 Codex 辅助草稿，不是实时聊天或外部 API 接入。证据台账记录全部异常证据；AI 证据包只从每类选取前三项，不能代替全面风险审查。

`validate-ai` 核查运行包、实际输入、响应结构、证据引用和数值，并在新目录生成 v2 审核模板。v2 的 `response_sha256` 绑定完整响应内容；修改建议后旧审核不再适用。正式记录由 Python `review` 命令校验并归档，`pending` 不等于批准。浏览、展开或下载页面均不会批准建议、执行采购或认证审核人身份。流程与旧 v1 兼容边界见 [AI 审核契约](docs/RELEASE_FIX_VALIDATION.md)。

## 测试与验证范围

```powershell
python -m unittest discover -s tests -v
node scripts/check_dashboard.mjs examples/showcase/base.html
node scripts/check_dashboard.mjs examples/showcase/base_ai.html
node scripts/check_dashboard.mjs examples/showcase/combined.html
```

Python 测试覆盖计算口径、数据异常、页面生成、输入输出保护及 AI 审核。JavaScript 脚本使用无外部依赖的 DOM 测试桩，检查筛选、日期、JSON、CSV 和展示契约；它不是 Chrome 排版、触屏或下载体验验收。

以下为公开仓库准备阶段的历史核验记录（2026-10-19），不是每次提交自动刷新的状态。该阶段在 Windows / Python 3.12.10 的独立测试副本中实际核验；副本不含 Git 历史、个人审核记录或预先存在的运行结果。最终候选目录只保存项目文件，测试产物留在副本。

| 验证 | 实际结果 |
|---|---|
| 完整 Python 测试 | 136 项通过；失败、错误、skip、expectedFailure、unexpectedSuccess 均为 0 |
| 输入输出及审核保护 | 上述总数包含 36 项输入输出安全测试、30 项发布/审核安全测试和 14 项审计回归 |
| README 快速分析与从数据生成开始的流程 | analyze/validate-ai 及 generate → analyze → validate-ai 均成功；生成输入与附带模拟数据字节一致 |
| 四情景与重复基准 | 脚本成功；四份完整 results.json 与既有基准逐字节一致，payload、manifest 和 AI 绑定一致 |
| 三张 showcase 的 JavaScript 逻辑 | 每页 30 项，共 90 项通过；通过内置 Node 执行现有 DOM 测试脚本，不表示已验证本机终端 Node 安装 |
| 两张历史基准 HTML 的 JavaScript 逻辑 | 每页 26 项，共 52 项通过，保持旧夹具兼容 |
| Chrome 人工验收 | 三张页面此前已由使用者验收；该准备阶段确认导航加入前的候选分析页与已验收文件、生成器新输出逐字节一致 |
| 该准备阶段的浏览器自动化、Linux/macOS 实机、远程 CI、公开仓库干净克隆 | 未执行 |

最终收尾验收（2026-10-19，Windows / Python 3.12.10）：工作区新增 6 项展示来源与导航契约测试后，完整 Python 测试为 **142 项通过**；三个展示看板的 DOM 检查共 **90 项通过**。四个线上 HTML 均返回 HTTP 200，按 LF 口径与本地哈希一致；已在内置浏览器约 471 CSS 像素宽视口检查四页导航、主要交互和窄屏布局。公开远程提交 `682b58f` 的干净克隆通过原有 136 项测试及 generate → analyze → validate-ai 流程。详见 [最终验收记录](docs/FINAL_ACCEPTANCE.md)。

已核验的远程状态（2026-10-19）：提交 `682b58f` 的 [reproducibility 测试](https://github.com/1463332164-ship-it/supply-chain-risk-analytics-public/actions/runs/39209139622) 与 [Pages 部署](https://github.com/1463332164-ship-it/supply-chain-risk-analytics-public/actions/runs/39209139383) 均成功。**上述远程证据只对应该提交，不覆盖尚未提交的文档与新增测试。** 新候选版本提交后仍需核对其自身的 CI、部署和线上页面。

[回归测试工作流](.github/workflows/tests.yml) 配置 Ubuntu/Python 3.12 测试与生成、分析命令；远程运行结果请查看 [Actions](https://github.com/1463332164-ship-it/supply-chain-risk-analytics-public/actions)。本地测试、用户在线验收、远程测试 CI 和公开干净克隆是不同证据，不能互相替代。

## 安全与使用边界

- 计算、数据校验与指纹来自同一份不可变 CSV 字节快照；多文件捕获不是外部事务。长期复现需要保留匹配的输入版本。
- 在新目标的同级临时目录完成构建后，以禁止替换目标的目录重命名发布。已有文件、空目录、路径重叠与符号链接／junction 会被拒绝。它不提供断电持久性、网络文件系统事务或对抗恶意并发路径替换的保证。
- Windows 路径与输出保护已有本机测试；Linux/macOS 排他重命名适配器有模拟测试，尚无对应平台实机验收。完整边界见 [输入输出安全](docs/INPUT_OUTPUT_SAFETY.md)。
- 模拟库存与订单独立生成，不是历史库存流水；未处理部分收货、退货、MOQ、产能和资金约束。采购额是建议量乘单价，不是节约金额。OTD 不是 OTIF。
- AI 的结构与数值校验不证明自由文本原因正确，也不能阻止有权限者同时篡改数据及摘要。人工审核记录是声明，不是身份认证或执行证明。

## 文件说明

`scai/` 是程序，`scripts/` 是验证入口，`tests/` 是回归测试，`data/demo/` 是模拟输入。`examples/showcase/` 是当前主展示；其 metadata 分别记录原始导出来源和当前展示页哈希；导航是导出后的展示层修改，不能作为 CLI 的运行 manifest。

`examples/base/` 中保留的分析包与旧 AI 页面、`examples/stress/results.json`、`examples/verification.json` 是测试依赖的历史夹具。旧页面不是最新 UI；旧验证 JSON 中的测试数、环境、命令及浏览器状态不代表当前验收。stress 目录只保留结果基准，不是完整运行包。不要用新 HTML 单独替换旧包中被 manifest 哈希绑定的文件。

个人审核和运行归档不随本项目分发。许可见 [LICENSE](LICENSE)。
