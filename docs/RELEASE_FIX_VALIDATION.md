# 固定 AI 草稿、响应绑定与人工审核契约

项目采用离线文件交换，没有外部大模型 API 客户端。附带的 `examples/ai_response_codex.json` 是根据模拟证据生成的固定 Codex 辅助草稿。它只提出待核查解释与动作，不证明根因、不代表审批或采购执行。

## 校验链

`validate-ai` 先通过 `verify_run` 核验实际三张输入 CSV、完整运行包、情景参数、packet 和 manifest，再检查响应结构、证据 ID、观察指标及必要限制说明。响应必须绑定当前 packet，不能将基准草稿混用到其他情景。

响应最多 9 条，每条只引用包内一个唯一证据 ID；`observed` 的键与有限数值必须匹配原证据，不允许布尔值冒充数值。解释字段必须是受长度约束的字符串，假设标为“待核实”，数字集中在 observed。此类结构规则不能证明中文叙述的因果解释正确，也不能替代对遗漏、语义和业务可行性的人工判断。

通过后，在全新目录生成 `ai_validation.json`、`ai_draft.json`、v2 `review_template.json` 和 `dashboard_ai.html`。它不会写入个人审核记录，也不会把结构检查通过标记为批准。

## v2 绑定完整响应

审核对象的顶层字段为 `schema_version`、`packet_sha256`、`response_sha256` 和 `decisions`，版本必须为整数 2。完整响应按 JSON 键排序、UTF-8、紧凑分隔符序列化，再计算 SHA-256；包含 limitations、建议列表及每条建议全部字段。列表顺序有意义，数值 JSON 类型保留，不做舍入或业务数值重写。JSON 文件排版和对象键顺序变化不改变此内容摘要。

`packet_sha256` 保留已有独立计算契约，不能把它与响应摘要或文件字节 SHA-256 混为一谈。修改建议文本、动作、观察指标或条目顺序后，原响应绑定审核会被拒绝，需要针对新响应重新审核。

每条决定恰含 evidence_id、decision、reviewer、reason，必须覆盖全部 AI 条目且无重复。decision 仅允许 `approve`、`reject`、`pending`。reviewer 和 reason 始终必须是字符串；approve/reject 必须填写非空内容。pending 可以保留空字符串，但 null、数字、列表等非法类型不会被接受。

## 演示与正式记录

在项目根目录运行，所有输出目录必须尚不存在：

```powershell
python -m scai analyze --data data/demo --out runs/ai_example_01/base
python -m scai validate-ai --run runs/ai_example_01/base --data data/demo --response examples/ai_response_codex.json --out runs/ai_example_01/draft
```

可打开 draft 目录的 HTML 查看草稿。正式人工审阅时，另存并填写生成的 v2 模板，保持版本及摘要字段；随后用 `review` 显式提供原运行目录、实际输入、响应和填写后的 decisions。`review --help` 显示完整参数。不要在缺乏证据时为演示而批准建议。

`review` 在独立新目录归档 human_review、response_snapshot、decisions_snapshot、ai_packet 与 run_reference。新目录限制和完整构建后发布保护同样适用。归档内容是用户提供的声明，没有身份认证；批准建议不等于已采取措施或已产生收益。

页面展开、点击、筛选和 CSV 下载不会改写审核状态。pending 不等于 approved；程序中的正式批准值是 `approve`。页面不提供采购审批或自动下单功能。个人审核内容及归档不随公开候选项目分发。

## 旧 v1 的边界

旧记录只绑定 packet，无法绑定建议的具体内容。只读检查将其分类为 `legacy_unbound`，不把旧批准解释成 v2 批准；直接用于当前 `review` 会被拒绝。保留旧文件，不自动修改或升级。

只有显式使用 `validate-ai --pending-decisions` 时，才允许将全部为 pending、字段合法且匹配当前条目的旧记录迁移到新 v2 模板；原始字节另存快照并记录摘要。旧 approve/reject 不会自动绑定，必须重新审阅。此选项不属于无需个人材料的默认演示流程。

## 相关验证与限制

`tests/test_release_safety.py` 和 `tests/test_audit_regressions.py` 覆盖 reviewer/reason 类型、完整响应绑定、草稿改变拒绝旧审核、旧版迁移边界、运行包混用及输出失败保护。`tests/test_input_output_safety.py` 验证全新 generate → analyze → validate-ai → pending 模板归档的安全链路。测试中的审核者和理由是人工构造夹具，不是真人批准。

Python 与 JavaScript 的实际执行结果见 [README](../README.md#测试与验证范围)。JavaScript DOM 检查不能证明浏览器排版正确；既有使用者 Chrome 验收与本轮自动化分别记录。没有远程 GitHub Actions 成功声明，也没有未来公开仓库干净克隆完成的声明。

哈希用于发现不一致，不是数字签名或对抗协调伪造的机制。输入输出的本地文件系统边界见 [安全说明](INPUT_OUTPUT_SAFETY.md)，业务定义见 [数据与指标](DATA_AND_METRICS.md)。
