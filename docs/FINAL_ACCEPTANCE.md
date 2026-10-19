# 公开仓库最终收尾验收记录

记录日期：2026-10-19。对象仅为 `supply-chain-risk-analytics-public` 独立公开仓库。本次不修改开发仓库、个人审核内容或历史运行归档，不执行暂存、提交或推送。

## 版本和证据范围

- 开始分支为 `main`，HEAD 为 `682b58f026a291dc169a4a6480c0ef3011835055`；公开远程 main 指向同一提交。
- 开始已有三项未暂存修改：根 README、展示 README、展示 metadata；暂存区为空。本次保留这些修改，在此基础上补充说明和回归测试。
- 当前候选改动共五个文件：上述三项、本文、`tests/test_showcase.py`。没有修改 `scai/`、HTML、CSV、历史 JSON 或工作流。
- 本轮新增产物放入全新 `runs/final_acceptance_20261019_01/`，受现有 `.gitignore` 保护，不纳入发布。`before.json` 保存开始时 HEAD、完整 diff、索引与既有文件哈希；日志可能含本机路径，不适合公开。
- 下述远程 CI、Pages 和远程干净克隆只证明 `682b58f` 的状态；新增六项测试和文档尚未在远程执行。发布新提交后必须重新核验。

## 已执行检查

| 检查 | 结果与范围 |
|---|---|
| 工作区修改前 Python 测试 | 136 项通过 |
| 新增展示契约测试 | 6 项通过；当前 HTML 哈希、真实输入指纹、完整 payload、指标与 AI 绑定、四页导航、离线资源约束 |
| 最终工作区完整测试 | 142 项通过；失败、错误、跳过、预期失败均为 0 |
| 展示页 JavaScript DOM 测试 | base、base_ai、combined 各 30 项，共 90 项通过；使用本机可用的内置 Node，不等同于浏览器排版验收 |
| 公开远程干净克隆 | 全新目录从 GitHub clone，HEAD 为 `682b58f`；136 项测试通过 |
| 干净克隆 CLI | generate → analyze → validate-ai 全部成功；新生成的四个输入文件与附带模拟输入逐字节相同 |
| 四情景实验 | 脚本成功；重复基准 `repeat_results_identical: true`，可选 AI 校验通过，输入未改变 |
| 轨迹与结果 | 360 组情景记录，共 7,560 个预测日；轨迹长度、连续日序、库存余额递推、首次缺口和峰值缺口检查通过；基准及组合完整 results 与公开夹具逐字节一致 |
| 线上 HTML | index、base、base_ai、combined 均 HTTP 200，响应字节按 LF 口径与本地文件一致 |
| 当前及历史隐私模式扫描 | 当前已跟踪文件、3 个可达提交中的 52 个不同 Git blob，未发现所检查的本机绝对路径、常见密钥或个人审核/运行目录路径；这是有限模式检查，不是无敏感信息的绝对保证 |
| Git 与原文件保护 | HEAD、索引和既有提交历史保持不变；除计划修改的三个既有文档/元数据文件外，其余开始时既有文件哈希保持不变 |

[reproducibility run 39209139622](https://github.com/1463332164-ship-it/supply-chain-risk-analytics-public/actions/runs/39209139622) 和 [Pages run 39209139383](https://github.com/1463332164-ship-it/supply-chain-risk-analytics-public/actions/runs/39209139383) 均在 `682b58f` 上完成且结论为 success。未认证的 Pages 配置 API 返回 404，不能据此认定未部署；这里的部署证据来自成功工作流、HTTP 响应与真实页面。

## 真实浏览器检查

使用 Codex 内置浏览器访问当前线上四页，视口宽约 471 CSS 像素。四页均未出现整页横向溢出；宽表格及两张图在各自容器内横向滚动。实际检查包括：

- 展示首页进入基准页，基准 → AI → 组合页面切换，以及组合页返回首页。
- 基准仓库/SKU 筛选及“查看”；切换仓库过滤掉选中项时清空旧图并提示重选；不存在的 SKU 显示空筛选提示。
- “无缺口但建议补货”筛出 4 组；SKU004/WH2 明确显示预测期无缺口、最大缺口 0、建议补货 79，JSON 保留首次缺口 `null`。
- 日期下拉、组合图表第 13 天点击、原始 JSON 展开；AI 页 119 条证据展开及 4 条固定草稿展开，明确待人工审核、不执行采购。
- 基准 SKU001/WH1：第 3 天（2026-10-20）净余额 -15；第 6 天（2026-10-23）到货 128、需求 18、余额 59。WH2 第 6 天到货 156、需求 21、余额 63。
- 组合 SKU001/WH1：第 2 天（2026-10-19）余额 -3；第 13 天（2026-10-30）到货 128、需求 22.5、余额 -105。WH2 第 13 天到货 156、需求 26.25、余额 -144。

没有执行实际断网、实体手机触屏、其他浏览器/更窄屏宽、CSV 下载后的本地文件打开验收；CSV 内容与悬停逻辑由 DOM 测试覆盖，不能等同于这些体验已验收。本次没有修改 HTML，因此线上检查对象与工作区 HTML 一致。

## 四情景业务结果

所有情景均为 90 个 SKU×仓库组合，全部使用模拟数据。

| 情景 | 预计缺口组合 | 建议补货组合 | 各组合峰值净缺口之和（件） | 建议补货量（件） | 未全量收货的逾期订单 |
|---|---:|---:|---:|---:|---:|
| 基准 | 17 | 21 | 5,243 | 6,241 | 90 |
| 需求 × 1.25 | 29 | 35 | 8,339.25 | 10,874 | 90 |
| 到货及采购交期 +7 天 | 42 | 45 | 11,827 | 13,060 | 90 |
| 组合 | 69 | 74 | 21,854.75 | 26,612 | 90 |

峰值净缺口之和不是累计丢单量，也不是同一时点的全网缺口。延迟情景同时改变预计到货、采购交期和预测窗口（14–21 天变为 21–28 天），不能作单一因素的因果解释。逾期订单属于快照时的历史判定，情景参数不改写已发生记录，因此四情景相同。建议补货和预计缺口是不同判断；建议采购额不是已下单、已支出或降本收益。

## 实际命令及复现位置

以下在仓库根目录执行。所有输出目录必须不存在；复现时换用新的编号，不覆盖本轮产物。

```powershell
python -m unittest discover -s tests -v
python -B -m unittest discover -s tests -p test_showcase.py -v
node scripts/check_dashboard.mjs examples/showcase/base.html
node scripts/check_dashboard.mjs examples/showcase/base_ai.html
node scripts/check_dashboard.mjs examples/showcase/combined.html
python scripts/audit_scenarios.py --out runs/final_acceptance_20261019_01/scenarios --response examples/ai_response_codex.json
git clone https://github.com/1463332164-ship-it/supply-chain-risk-analytics-public.git runs/final_acceptance_20261019_01/clean_clone
```

Node 检查实际使用本机内置运行时的完整路径；上方 `node` 是 PATH 已配置时的等价写法，不代表用户的 VS Code 终端必定已配置 Node。

克隆内执行：

```powershell
python -B -m unittest discover -s tests -v
python -B -m scai generate --out runs/final_cli_data
python -B -m scai analyze --data runs/final_cli_data --out runs/final_cli_base
python -B -m scai validate-ai --run runs/final_cli_base --data runs/final_cli_data --response examples/ai_response_codex.json --out runs/final_cli_ai
```

本轮日志包括 `python_baseline.log`、`python_final.log`、三个 `dom_*.log`、`clean_clone_tests.log`、`clean_clone_cli.json`、`scenario_run.log`、`business_checks.json`、`remote_actions.json`、`initial_hash_checks.json`、`privacy_scan.json` 和 `after.json`。日志属于本地验收证据，不随公开文档上传。

## 收尾处理与发布建议

未发现需要修改业务算法或展示页面的阻断性故障。处理的文档问题与保护缺口如下：

1. 明确单页离线分析与四页离线导航的不同下载要求。
2. 保留 metadata 的原始导出哈希，使用 `published_file_sha256` 描述当前带导航 HTML；补充生成器 Git 字节与源运行产物摘要的含义。历史 `verification_scope` 不改写为本次验收结论。
3. 更新验证记录，区分本地候选版本、既有远程提交、真实浏览器检查和未执行项目；加入六项无 Git/网络/本机 runs 依赖的展示回归测试。
4. 既有 `.gitignore` 已忽略个人审核文件、`runs/`、`.env` 与 `.env.*`，并保留 `.env.example`；当前没有这些敏感路径被跟踪。本轮无需修改忽略规则。

建议发布上述五个候选文件；不发布 `runs/`、个人审核文件或本机日志。先查看最终 diff 与测试证据，获得使用者明确批准后才暂存、提交、推送。批准后的目标仍为 `main`，提交后核对远程 HEAD、该提交的 Actions、Pages 和线上四页。求职材料留在该发布核验之后准备，不将尚未验证的候选版本写成已经发布的成果。
