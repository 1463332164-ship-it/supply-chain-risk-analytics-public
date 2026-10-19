# 供应链异常分析台 · 离线演示

三张自包含 HTML 展示同一组模拟业务数据的基准分析、固定 AI 草稿及组合压力情景。数据包含 30 个 SKU、3 个仓库、180 天历史需求，全部来自仓库的 `data/demo/`；不包含真实企业数据或个人审核意见。

| 页面 | 内容 | 预计缺口组合 | 建议补货组合 | 证据记录 |
|---|---|---:|---:|---:|
| [base.html](base.html) | 基准分析，无 AI 草稿 | 17 | 21 | 119 |
| [base_ai.html](base_ai.html) | 相同基准，附 4 条固定 AI 草稿 | 17 | 21 | 119 |
| [combined.html](combined.html) | 需求倍率 1.25，到货及新增采购交期延后 7 天 | 69 | 74 | 171 |

## 打开与阅读

下载 HTML 后，用 Chrome 打开本地文件即可；可断网使用，不需要启动服务器、安装 Python、提供 API 密钥或额外数据文件。GitHub 的文件预览可能显示 HTML 源码，应下载后打开。

先看核心指标，再用仓库、SKU 和风险范围筛选库存表，点击“查看”读取逐日库存与到货图。日期悬停、点击或下拉选择可显示当日数值；JSON 详情用于追溯，CSV 下载对应当前筛选。

证据台账默认折叠，展开后可查看全部证据的 ID、优先级、原始指标、文件来源与解释边界。证据提供核查线索，不证明根因。AI 区域也默认折叠；展示已有固定建议，不提供实时聊天或网页采购审批。

## 从程序重新生成

在项目根目录使用 Python 3.12。下列输出目录必须不存在，重复运行时换新编号；不要覆盖旧结果：

```powershell
python -m scai analyze --data data/demo --out runs/showcase_repro_01/base
python -m scai validate-ai --run runs/showcase_repro_01/base --data data/demo --response examples/ai_response_codex.json --out runs/showcase_repro_01/base_ai
python -m scai analyze --data data/demo --out runs/showcase_repro_01/combined --demand-factor 1.25 --delay-days 7
```

分别打开生成目录内的 `base/dashboard.html`、`base_ai/dashboard_ai.html`、`combined/dashboard.html`。这条流程不依赖个人审核文件，也不会实时调用模型 API。

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

[showcase_metadata.json](showcase_metadata.json) 记录情景参数、模拟输入来源与哈希、每张 HTML 及源 `results.json` 的 SHA-256，以及生成器源码摘要。文件名中的 metadata 表示展示来源摘要，不是程序使用的 `run_manifest.json`，也不是数字签名。源运行包留在本地，不随本目录分发。

页面包含完整 result payload 与证据内容，但不包括独立的源 CSV 或原始结果文件；查看来源行时需要仓库中的模拟数据，重新计算需按上面的命令运行。完整性校验与 JavaScript 逻辑测试不能替代浏览器视觉验收，也不表示远程 CI 或 GitHub 发布已经完成。
