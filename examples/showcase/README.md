# 供应链异常分析台 · 离线演示

三张自包含 HTML 展示同一组模拟业务数据的基准分析、固定 AI 草稿及组合压力情景。数据包含 30 个 SKU、3 个仓库、180 天历史需求，全部来自仓库的 `data/demo/`；不包含真实企业数据或个人审核意见。

| 页面 | 内容 | 预计缺口组合 | 建议补货组合 | 证据记录 |
|---|---|---:|---:|---:|
| [base.html](base.html) | 基准分析，无 AI 草稿 | 17 | 21 | 119 |
| [base_ai.html](base_ai.html) | 相同基准，附 4 条固定 AI 草稿 | 17 | 21 | 119 |
| [combined.html](combined.html) | 需求倍率 1.25，到货及新增采购交期延后 7 天 | 69 | 74 | 171 |

## 打开与阅读

可直接访问 [在线展示首页](https://1463332164-ship-it.github.io/supply-chain-risk-analytics-public/)，并通过各页顶部导航切换。使用者已于 2026-10-19 确认 Actions 部署与在线导航正常；这不是回归测试 CI 或浏览器自动化的验证声明。

下载 HTML 后，用 Chrome 打开本地文件即可；可断网使用，不需要启动服务器、安装 Python、提供 API 密钥或额外数据文件。GitHub 的文件预览可能显示 HTML 源码，应下载后打开。单页可独立分析；离线跨页导航需要同时保存 `index.html`、`base.html`、`base_ai.html` 和 `combined.html` 到同一目录，保持文件名不变。

先看核心指标，再用仓库、SKU 和风险范围筛选库存表，点击“查看”读取逐日库存与到货图。日期悬停、点击或下拉选择可显示当日数值；JSON 详情用于追溯，CSV 下载对应当前筛选。

证据台账默认折叠，展开后可查看全部证据的 ID、优先级、原始指标、文件来源与解释边界。证据提供核查线索，不证明根因。AI 区域也默认折叠；展示已有固定建议，不提供实时聊天或网页采购审批。

## 从程序重新生成

在项目根目录使用 Python 3.12。下列输出目录必须不存在，重复运行时换新编号；不要覆盖旧结果：

```powershell
python -m scai analyze --data data/demo --out runs/showcase_repro_01/base
python -m scai validate-ai --run runs/showcase_repro_01/base --data data/demo --response examples/ai_response_codex.json --out runs/showcase_repro_01/base_ai
python -m scai analyze --data data/demo --out runs/showcase_repro_01/combined --demand-factor 1.25 --delay-days 7
```

分别打开生成目录内的 `base/dashboard.html`、`base_ai/dashboard_ai.html`、`combined/dashboard.html`。这条流程不依赖个人审核文件，也不会实时调用模型 API。当前发布页另加了展示首页和跨页导航；CLI 生成的是分析页，不包含这些发布导航，因此不应要求生成 HTML 与当前发布 HTML 逐字节一致。

需要四情景与重复运行检查时，可使用一个新的目录：

```powershell
python scripts/audit_scenarios.py --out runs/showcase_scenarios_01 --response examples/ai_response_codex.json
```

## AI 与业务边界

- 固定建议来自 `examples/ai_response_codex.json`，由 Codex 根据程序证据辅助生成。引用、数值和结构校验不能证明解释正确；建议仍需独立人工审核。
- 正式审核由 Python CLI 的 `validate-ai` 和 `review` 流程处理，v2 审核以 `response_sha256` 绑定完整响应。查看、展开或下载页面不构成批准，不自动采购。
- 模拟需求不等于真实销售；库存快照与订单独立生成，未验证真实历史库存流水。预测基线不是适用于所有品类的最优模型。
- 补货是规则建议，未纳入 MOQ、产能、运输和资金约束；OTD 按到期订单全量收货计算，不是 OTIF。
- 延迟情景同时改变到货、采购交期和预测窗口，不能把差值解释为单一因素的因果效果。模拟结果不代表真实企业降本、收益或正式部署。

基准 SKU001/WH1：D3 净余额 −15，D6 到货 128、净余额 59。组合压力：D2 净余额 −3，D13 到货 128、净余额 −105。四情景预计缺口组合为 17、29、42、69；建议补货组合为 21、35、45、74。

## 文件完整性与验证范围

本目录是从已核验完整运行包导出的单文件演示，不是独立运行包，不能作为 `validate-ai --run` 的输入。源运行包中的 results、packet、manifest、输出哈希及输入匹配关系已核验；AI 页另核验响应、v2 模板绑定及其引用的运行 manifest。个人审核记录没有复制到这里。

[showcase_metadata.json](showcase_metadata.json) 使用 schema v2，将历史来源与当前展示文件分开：

- `pages.*.html_sha256` 保留导航修改前的原始导出哈希，与 `original_export_git_commit` 中对应文件的 Git 字节一致；`byte_identical_to_stage5_preview` 和 `verification_scope` 也仅记录原始准备阶段，不能解释为当前导航页的验收状态。
- `published_file_sha256` 记录本目录当前四个 HTML（包括 `index.html`）按 `.gitattributes` 统一 CRLF 为 LF 后的 UTF-8 字节（避免 Windows 检出换行差异）。修改页面后应重新计算；它不证明远程部署内容已经同步。
- 输入、生成器、源 `results.json`、packet、manifest 和 AI 摘要保留原始来源含义。导航修改没有重新生成业务结果，也没有改写这些摘要。

文件名中的 metadata 表示展示来源摘要，不是程序使用的 `run_manifest.json`，也不是数字签名。源运行包留在本地，不随本目录分发。核对当前展示文件可在仓库根目录运行：

```powershell
$m = Get-Content examples/showcase/showcase_metadata.json -Raw | ConvertFrom-Json
$m.published_file_sha256.PSObject.Properties | ForEach-Object {
    $html = [IO.File]::ReadAllText((Join-Path (Get-Location) ("examples/showcase/" + $_.Name)))
    $bytes = [Text.Encoding]::UTF8.GetBytes($html.Replace("`r`n", "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $actual = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant() }
    finally { $sha.Dispose() }
    if ($actual -ne $_.Value) { throw "HTML hash mismatch: $($_.Name)" }
}
Write-Output "Showcase HTML hashes match."
```

页面包含完整 result payload 与证据内容，但不包括独立的源 CSV 或原始结果文件；查看来源行时需要仓库中的模拟数据，重新计算需按上面的命令运行。完整性校验与 JavaScript 逻辑测试不能替代浏览器视觉验收，也不能单独证明远程测试 CI 或 GitHub 部署状态。

## 最终收尾验收补充（2026-10-19）

工作区 142 项 Python 测试（含新增 6 项展示契约检查）及三个看板共 90 项 DOM 检查通过。四个线上 HTML 与本地 LF 哈希一致；内置浏览器约 471 CSS 像素宽视口已检查导航、筛选、日期明细、JSON、证据与固定 AI 草稿展示。

公开提交 `682b58f` 的回归测试工作流、Pages 工作流及干净克隆另有成功证据；它们不覆盖尚未提交的候选改动。未执行实际断网、手机触屏及 CSV 文件落盘的浏览器验收。完整命令、业务指标和限制见 [最终验收记录](../../docs/FINAL_ACCEPTANCE.md)。元数据中的 `verification_scope` 保持原始导出阶段含义，不把本次验证写回历史状态。
