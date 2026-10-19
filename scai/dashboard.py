"""Self-contained HTML; no CDN, telemetry or remote runtime."""
import json
import re
from html import escape
from pathlib import Path

from .ai import make_packet, validate_response


def _json_text(value):
    return escape(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def _field(record, key):
    if key not in record:
        return '未提供'
    value = record[key]
    return escape(value) if isinstance(value, str) else _json_text(value)


def _evidence_panel(result):
    rows = result.get('evidence') or []
    cards = []
    for row in rows:
        cards.append(f'''<article class="evidence-item">
<div class="evidence-heading"><h3>{_field(row, 'id')}</h3><span class="section-state">优先级：{_field(row, 'priority')}</span></div>
<dl class="entity-fields"><div><dt>类型</dt><dd>{_field(row, 'type')}</dd></div><div><dt>SKU</dt><dd>{_field(row, 'sku')}</dd></div><div><dt>仓库</dt><dd>{_field(row, 'warehouse')}</dd></div></dl>
<div class="evidence-fields"><div><h4>已计算指标 · 原值</h4><pre class="metric-json">{_json_text(row['metrics']) if 'metrics' in row else '未提供'}</pre></div><div><h4>来源 · 文件与记录</h4><pre class="source-text">{_field(row, 'source')}</pre></div></div>
<p class="evidence-meaning"><b>解释与边界：</b><span>{_field(row, 'meaning')}</span></p>
<details class="raw-record"><summary>完整证据 JSON</summary><pre class="raw-json evidence-raw">{_json_text(row)}</pre></details>
</article>''')
    content = ''.join(cards) or '<p class="muted">当前结果没有证据记录。</p>'
    return f'''<section class="secondary"><details id="evidence-details" class="disclosure">
<summary><span class="summary-main"><span class="disclosure-title">证据台账</span><span class="muted">按需查看指标、来源与解释；根因尚未验证。</span></span><span id="evidence-count" class="section-state">{len(rows)} 条证据</span></summary>
<div id="evidence" class="evidence-list" tabindex="0" aria-label="全部证据，按原始顺序">{content}</div>
</details></section>'''


def _ai_panel(result, response):
    warning = ''
    if response is None:
        status = '未导入AI草稿'
        content = '<p class="muted">尚未导入 AI 草稿。可使用分析输出中的 ai_prompt.txt 与 ai_packet.json 准备响应，再通过 CLI 校验导入。</p>'
    else:
        items = response.get('items', []) if isinstance(response, dict) else []
        count = len(items) if isinstance(items, list) else 0
        try:
            packet = make_packet(result, result['input_sha256'])
            validate_response(packet, response)
        except (ValueError, TypeError, KeyError) as exc:
            status = f'{count} 条草稿 · 校验失败'
            warning = f'<div id="ai-warning" class="notice validation-warning" role="alert"><b>AI 草稿校验失败。</b> {escape(str(exc))}。请核对原始证据与响应；此草稿不得作为已校验建议或批准记录。</div>'
        else:
            status = f'{count} 条建议 · 待人工审核'
        content = '<p class="muted">展示已导入的固定 AI 草稿，不调用实时大模型，也不提供网页采购审批。</p>'
        if not warning:
            content += '<p class="review-state">引用、数值及结构检查通过；解释仍待人工核实，不代表人工批准。</p>'
        if isinstance(response, dict):
            content += f'<p class="ai-limitations"><b>使用边界：</b>{_field(response, "limitations")}</p>'
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue  # Invalid content is retained verbatim in the full JSON below.
                content += f'''<article class="aiitem"><h3>{_field(item, 'evidence_id')}</h3>
<p><b>待核查解释：</b>{_field(item, 'hypothesis')}</p><p><b>核查建议：</b>{_field(item, 'action')}</p>
<p class="muted">建议负责职能：{_field(item, 'owner_role')}</p><h4>引用指标 · 原值</h4><pre class="metric-json">{_json_text(item['observed']) if 'observed' in item else '未提供'}</pre></article>'''
        content += f'<details class="raw-record"><summary>完整原始 AI 草稿 JSON</summary><pre id="ai-raw" class="raw-json">{_json_text(response)}</pre></details>'
    return warning, f'''<section class="secondary"><details id="ai-details" class="disclosure">
<summary><span class="summary-main"><span class="disclosure-title">AI建议与人工审核</span><span class="muted">固定草稿展示与审核流程说明</span></span><span id="ai-status" class="section-state">{status}</span></summary>
<div class="disclosure-body"><div id="ai">{content}</div><p class="review-guide">正式审核通过 Python CLI 的 validate-ai → review 完成。v2 审核绑定完整响应的 response_sha256 并归档；展开、点击或查看页面均不产生批准，不执行采购。此页面不读取个人审核记录。</p></div>
</details></section>'''


def render(result,path,ai_response=None):
    payload=json.dumps({'result':result,'ai':ai_response},ensure_ascii=False,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    evidence = _evidence_panel(result)
    ai_warning, ai_panel = _ai_panel(result, ai_response)
    template='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Supply Chain AI | 模拟业务分析台</title>
<style>body{margin:0;background:#f2f5f9;color:#18324a;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1220px;margin:32px auto;padding:0 24px}header{background:#102c47;color:white;padding:26px 30px;border-radius:18px}h1{margin:6px 0;font-size:30px}h2{font-size:20px}.eyebrow{color:#81d6dc;letter-spacing:2px}.notice{background:#fff1ce;border:1px solid #e9c575;padding:12px 18px;margin:20px 0;border-radius:10px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:15px}.card,section{background:white;border:1px solid #dce3ea;border-radius:12px;padding:20px;margin:16px 0}.value{font-size:30px;font-weight:700;color:#126f7a}.muted{color:#5d6d7c;font-size:13px}.controls{display:flex;gap:12px;flex-wrap:wrap}select,input,button{padding:9px;border:1px solid #bdcbd7;border-radius:7px;background:white;color:#173b58}button{cursor:pointer}.scroll{overflow:auto;max-height:500px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:11px 10px;text-align:left;border-bottom:1px solid #e1e8ef;white-space:nowrap}th{position:sticky;top:0;background:#eaf0f5}td.wrap{white-space:normal;min-width:200px;max-width:400px}.pill{background:#fce7db;color:#994623;border-radius:4px;padding:3px 7px}pre{white-space:pre-wrap;word-break:break-word;background:#f4f7fa;padding:16px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.bar{height:15px;background:#218b96;border-radius:3px}.barrow{display:grid;grid-template-columns:110px 1fr 70px;gap:12px;margin:14px 0;align-items:center}.risk{color:#b44825}footer{padding:25px 0;color:#667}.aiitem{border-left:3px solid #d49b3d;padding:8px 15px;margin:15px 0}@media(max-width:760px){.cards,.grid{grid-template-columns:1fr 1fr}h1{font-size:23px}main{padding:0 12px}.grid{grid-template-columns:1fr}}</style>
<style>
[hidden]{display:none!important}button:hover{background:#e9f4f5}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #218b96;outline-offset:3px}
.status-tag{display:inline-block;padding:4px 8px;border-radius:6px;font-weight:600}.status-shortage_reorder,.status-shortage_only{background:#fff0ec;color:#a1372a}.status-buffer_reorder{background:#fff3d9;color:#825511}.status-covered{background:#e9f4ef;color:#28604d}.field-note{display:block;font-size:12px;color:#5d6d7c;white-space:normal;max-width:170px}.metric-guide,.decision-explanation{background:#f4f8fb;border:1px solid #dce8ed;border-radius:8px;padding:12px 16px;margin:14px 0;font-size:13px}.decision-explanation p{margin:7px 0}.status-cell{white-space:normal;min-width:180px;max-width:240px}
.inventory-detail{margin-top:24px;border-top:2px solid #dce8ed;padding-top:22px}.detail-heading{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}.detail-heading h3{margin:0;font-size:21px}.empty-state{padding:28px;background:#f5f8fb;border:1px dashed #b8c9d7;border-radius:10px;color:#536b7f;text-align:center}
.detail-summary{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.detail-summary span{background:#eef4f8;border-radius:6px;padding:7px 12px}.detail-summary .risk-tag{background:#fff0ec;color:#a1372a}.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:#456075;margin:12px 0}.legend i{display:inline-block;width:16px;height:9px;margin-right:6px;border-radius:2px}.chart-scroll{overflow-x:auto;border:1px solid #dce3ea;border-radius:10px;background:#fff}.chart-stack{padding:16px 12px 4px}.chart-stack h4{margin:2px 0 0 12px;font-size:15px}.chart-stack svg{display:block;width:100%;height:auto;font-family:inherit}.chart-stack svg text{fill:#52697b;font-size:12px}.chart-stack svg .marker-label{fill:#a1372a;font-weight:700}.chart-stack svg .hit{cursor:crosshair}.chart-stack svg .hit:hover{fill:#126f7a;fill-opacity:.07}
.hover-readout{min-height:26px;color:#315569;margin:10px 0;font-size:13px}.day-controls{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:18px 0 10px}.day-detail{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.day-metric{background:#f1f6f9;border-radius:8px;padding:12px 16px}.day-metric strong{display:block;font-size:23px;color:#173b58}.day-metric.negative{background:#fff0ec}.day-metric.negative strong{color:#a1372a}.selected-row{background:#eef8f8}details{margin-top:18px}summary{cursor:pointer;color:#315569}
@media(max-width:600px){.day-detail{grid-template-columns:1fr}.detail-summary{font-size:13px}section{padding:14px}.detail-heading h3{font-size:18px}}
</style>
<style>
h2{margin:0 0 16px}.cards{gap:16px;margin:20px 0}.cards .card{margin:0}.grid{margin:16px 0;align-items:start}.grid>section{margin:0;min-width:0}th,td{vertical-align:top}button{font:inherit;font-size:13px;font-weight:600}pre{border-radius:8px}summary:focus-visible{outline:3px solid #218b96;outline-offset:3px}
.secondary{padding:0;overflow:hidden}.disclosure{margin:0}.disclosure>summary{display:flex;align-items:center;gap:14px;padding:18px 20px;list-style:none}.disclosure>summary::-webkit-details-marker{display:none}.disclosure>summary::before{content:'›';font-size:25px;color:#126f7a;flex:none;transition:transform .15s}.disclosure[open]>summary::before{transform:rotate(90deg)}.disclosure[open]>summary{border-bottom:1px solid #dce3ea}.summary-main{flex:1;min-width:0}.summary-main>span{display:block}.disclosure-title{font-size:18px;font-weight:700;color:#18324a}.section-state{display:inline-block;background:#edf4f7;color:#315569;border-radius:6px;padding:4px 9px;font-size:12px;overflow-wrap:anywhere}.disclosure-body{padding:4px 20px 18px}
.evidence-list{max-height:680px;overflow:auto;padding:16px;scrollbar-gutter:stable}.evidence-item{border:1px solid #dce3ea;border-radius:9px;padding:16px;margin-bottom:12px}.evidence-item:last-child{margin-bottom:0}.evidence-heading{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}.evidence-item h3,.aiitem h3{margin:0;font-size:15px;overflow-wrap:anywhere}.evidence-item h4,.aiitem h4{font-size:13px;margin:8px 0;color:#456075}.entity-fields{display:grid;grid-template-columns:2fr 1fr 1fr;gap:12px;margin:12px 0}.entity-fields>div,.evidence-fields>div{min-width:0}.entity-fields dt{font-size:12px;color:#5d6d7c}.entity-fields dd{margin:0;font-size:13px;overflow-wrap:anywhere}.evidence-fields{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}.metric-json,.source-text,.raw-json{font:12px/1.7 ui-monospace,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;word-break:normal;padding:12px;margin:0}.evidence-meaning,.aiitem p,.ai-limitations{overflow-wrap:anywhere;white-space:pre-wrap}.evidence-meaning{font-size:13px;margin:12px 0}.raw-record{margin-top:12px}.raw-record>summary{font-size:13px;padding:4px 0}.raw-record pre{margin-top:8px}.review-guide{padding:12px 14px;background:#f4f8fb;border-radius:8px;font-size:13px;color:#456075;overflow-wrap:anywhere}.review-state{color:#825511;font-size:13px}.validation-warning{border-color:#cd7662;background:#fff0ec;color:#8e3025;overflow-wrap:anywhere}
@media(max-width:600px){main{margin:18px auto}header{padding:20px}.cards{gap:10px}.cards .card{padding:14px}.value{font-size:26px}.disclosure>summary{padding:16px;flex-wrap:wrap;gap:8px}.summary-main{flex-basis:calc(100% - 32px)}.disclosure>summary>.section-state{margin-left:22px}.evidence-list{padding:10px;max-height:70vh}.evidence-item{padding:12px}.evidence-fields{grid-template-columns:minmax(0,1fr);gap:4px}.entity-fields{grid-template-columns:minmax(0,1fr)}.disclosure-body{padding:4px 14px 14px}.barrow{grid-template-columns:90px minmax(0,1fr) 64px;gap:8px}}
@media(prefers-reduced-motion:reduce){.disclosure>summary::before{transition:none}}
</style>
<main><header><div class="eyebrow">P1 / EVIDENCE-DRIVEN OPERATIONS</div><h1>供应链需求、库存与交付异常分析台</h1><div id="meta"></div></header>
<div class="notice"><b>全部运营数据为模拟。</b>预测风险不等于已发生缺货，补货量是规则建议；未证明企业收益。AI内容为待人工审核草稿。</div>
__AI_WARNING__
<div class="cards" id="cards"></div><div class="grid"><section><h2>预测基线 · 独立测试段</h2><div id="models"></div><p class="muted">验证期选模型，末段测试；每个起点仅使用之前历史。WAPE 为汇总绝对误差 / 汇总实际需求。</p></section><section><h2>采购交付 · 到期订单口径</h2><div id="delivery"></div><p class="muted">最近28日承诺到期的订单作为分母；已到期未收货也计入。不支持部分收货，未使用 OTIF 命名。</p></section></div>
<section><h2>库存风险与补货核查</h2><div class="controls"><label>仓库 <select id="warehouse"><option value="">全部</option></select></label><label>SKU <input id="sku" placeholder="例如 SKU001"></label><label>范围 <select id="risk"><option value="all">全部</option><option value="shortage">预计有缺口</option><option value="reorder">建议补货</option><option value="buffer_reorder">无缺口但建议补货</option></select></label><button id="download">下载当前筛选 CSV</button></div><p class="muted" id="count"></p>
<div class="metric-guide"><b>缺口看每日余额，补货看窗口总量与安全缓冲。</b>“预测期无缺口”表示后台首次缺口日为 null；第 0 天表示快照已有缺口。最大净缺口为 0 表示输出的净缺口量为零；建议补货为 0 表示当前规则未建议新增采购，不代表每天都无缺口；预计采购额为 0 是建议量 × 单价的结果，不是金额缺失。所有判断仅适用于当前情景与预测窗口。</div>
<div class="scroll"><table><thead><tr><th>SKU / 仓</th><th>补货风险状态</th><th>现货</th><th>覆盖天数</th><th>首次缺口日</th><th>最大净缺口</th><th>建议补货</th><th>预计采购额 CNY</th><th>追溯</th></tr></thead><tbody id="inventory"></tbody></table></div>
<div class="inventory-detail" id="inventory-detail"><div class="detail-heading"><h3 id="detail-title">逐日库存分析</h3><span class="muted">预测窗口 · SKU × 仓库</span></div>
<p id="chart-empty" class="empty-state" role="status">点击上方库存表的“查看”，分析每日库存与到货节奏。</p>
<div id="decision-explanation" class="decision-explanation" hidden></div>
<div id="chart-content" hidden><div id="detail-summary" class="detail-summary"></div>
<p class="muted">净余额 = 前日净余额 + 当日预计到货 − 当日预测需求。负数表示模型预计的净缺口；到货按日初、需求按日末计算。</p>
<div class="legend"><span><i style="background:#126f7a"></i>日末净余额（件）</span><span><i style="background:#f8d5cd"></i>日末负余额风险</span><span><i style="background:#b13c2e"></i>首次缺口</span><span><i style="background:#5376bb"></i>预测需求（件/日）</span><span><i style="background:#c47b20"></i>预计到货（件/日）</span></div>
<p class="muted">悬停查看当日数值；点击图中日期所在列固定明细，也可用下方日期下拉框选择。窄屏可左右滚动两张图。</p>
<div class="chart-scroll" id="chart-scroll"><div class="chart-stack" id="chart-stack"><h4>01 / 预测库存净余额</h4><div id="balance-chart"></div><h4>02 / 预测需求与预计到货</h4><div id="flow-chart"></div></div></div>
<p id="chart-hover" class="hover-readout">悬停任一日期列，查看每日数值。</p>
<div class="day-controls"><label for="day-select">固定查看日期</label><select id="day-select"></select><span id="day-caption" class="muted"></span></div>
<div id="day-detail" class="day-detail" aria-live="polite"></div>
</div><details id="trace-details"><summary>原始 JSON 数据追溯</summary><pre id="trace">点击表内“查看”</pre></details></div></section>
__EVIDENCE__
__AI_PANEL__
<footer>Python 标准库 · 本地离线展示 · 数据与算法可复算 · v0.1.0</footer></main>
<script id="payload" type="application/json">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('payload').textContent),r=data.result,s=r.summary;
const $=id=>document.getElementById(id),esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),fmt=v=>v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
$('meta').textContent=`快照 ${s.as_of} · ${s.sku_count} SKU / ${s.warehouse_count} 仓 / ${s.history_days} 日 · 需求倍率 ${s.demand_factor} / 到货延后 ${s.delay_days} 日`;
$('cards').innerHTML=[['需求记录',fmt(s.demand_rows),'已通过数据契约检查'],['预计缺口组合',fmt(s.shortage_entities),`共 ${s.series} 个 SKU-仓组合`],['到期订单准时率',s.otd==null?'—':fmt(s.otd*100)+'%',`${s.on_time_orders} / ${s.due_orders} 笔`],['建议补货数量',fmt(s.reorder_suggestion_units),'未考虑 MOQ / 容量 / 资金限制']].map(x=>`<div class="card"><div>${x[0]}</div><div class="value">${x[1]}</div><div class="muted">${x[2]}</div></div>`).join('');
const max=Math.max(...Object.values(r.metrics.test).map(m=>m.wape??0),0.001);
$('models').innerHTML=Object.entries(r.metrics.test).map(([name,m])=>`<div class="barrow"><span>${esc(name)}${name===s.selected_model?' ✓':''}</span><div class="bar" style="width:${100*(m.wape??0)/max}%"></div><span>${m.wape==null?'—':fmt(m.wape*100)+'%'}</span></div>`).join('');
$('delivery').innerHTML='<table><tr><th>供应商</th><th>准时 / 到期</th><th>OTD</th></tr>'+r.suppliers.map(x=>`<tr><td>${esc(x.supplier)}</td><td>${x.on_time_orders} / ${x.due_orders}</td><td>${x.otd==null?'—':fmt(x.otd*100)+'%'}</td></tr>`).join('')+'</table>';
$('warehouse').innerHTML += [...new Set(r.inventory.map(x=>x.warehouse))].sort().map(w=>`<option>${esc(w)}</option>`).join('');
// Selection is keyed by the entity, never by its changing filtered row index.
let filtered=[],selectedKey=null,selected=null,points=[],selectedDay=0;
const entityKey=x=>JSON.stringify([x.sku,x.warehouse]);
const qty=v=>v==null?'不适用':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:4});
// Shortage is a daily timing condition; reorder is an independent total/safety target.
const hasShortage=x=>x.first_shortage_day!=null;
const needsReorder=x=>x.reorder_suggestion_units>0;
function riskState(x){
    if(hasShortage(x))return needsReorder(x)
        ?{key:'shortage_reorder',label:'有缺口且需补货',note:'核查新增采购，并确认能否及时覆盖前段缺口。'}
        :{key:'shortage_only',label:'有缺口但当前建议补货为0',note:'窗口总量含缓冲已满足，但到货节奏仍可能留下前段缺口；核查调拨或催交。'};
    return needsReorder(x)
        ?{key:'buffer_reorder',label:'无缺口但需补货',note:'每日余额未负，但窗口末库存不足以满足安全缓冲目标。'}
        :{key:'covered',label:'无缺口且无需补货',note:'当前窗口未见缺口，按现有规则无需新增采购。'};
}
function matchesScope(x,scope){return scope==='all'||(scope==='shortage'&&hasShortage(x))||(scope==='reorder'&&needsReorder(x))||(scope==='buffer_reorder'&&!hasShortage(x)&&needsReorder(x));}
const shortageLabel=x=>x.first_shortage_day==null?'预测期无缺口':x.first_shortage_day===0?'第 0 天（快照已有缺口）':`第 ${x.first_shortage_day} 天`;
function zeroNote(value,note){return value===0?`<small class="field-note">${note}</small>`:'';}
function dateAt(day){const d=new Date(s.as_of+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+day);return d.toISOString().slice(0,10);}
const dayLabel=day=>`第 ${day} 天 · ${dateAt(day)}${day===0?'（快照）':''}`;
const dayText=p=>`${dayLabel(p.day)} ｜ 预测需求 ${qty(p.demand)} ｜ 预计到货 ${qty(p.arrival)} ｜ ${p.day===0?'快照':'日末'}净余额 ${qty(p.balance)} 件`;
function renderRows(){
    $('inventory').innerHTML=filtered.map((x,i)=>{const state=riskState(x);return `<tr${entityKey(x)===selectedKey?' class="selected-row"':''}><td>${esc(x.sku)} / ${esc(x.warehouse)}</td><td class="status-cell"><span class="status-tag status-${state.key}">${state.label}</span></td><td>${fmt(x.on_hand)}</td><td>${fmt(x.coverage_days)}</td><td class="${hasShortage(x)?'risk':''}">${shortageLabel(x)}</td><td>${qty(x.peak_net_shortage_units)}${zeroNote(x.peak_net_shortage_units,hasShortage(x)?'舍入值；以首次缺口判断为准':'预测期无净缺口')}</td><td>${qty(x.reorder_suggestion_units)}${zeroNote(x.reorder_suggestion_units,'当前规则未建议新增采购')}</td><td>${fmt(x.reorder_cost_cny)}${zeroNote(x.reorder_cost_cny,'建议量 × 单价为 0')}</td><td><button data-index="${i}" aria-label="查看 ${esc(x.sku)} ${esc(x.warehouse)} 逐日库存">查看</button></td></tr>`;}).join('');
}
function clearDetail(message){
    selectedKey=null;selected=null;points=[];selectedDay=0;
    $('detail-title').textContent='逐日库存分析';$('chart-content').hidden=true;
    $('chart-empty').hidden=false;$('chart-empty').textContent=message;
    ['balance-chart','flow-chart','detail-summary','day-select','day-detail'].forEach(id=>$(id).innerHTML='');
    $('chart-hover').textContent='';$('day-caption').textContent='';
    $('trace').textContent='点击表内“查看”';$('trace-details').open=false;
    $('decision-explanation').innerHTML='';$('decision-explanation').hidden=true;
}
function update(){
    filtered=r.inventory.filter(x=>(!$('warehouse').value||x.warehouse===$('warehouse').value)&&x.sku.toLowerCase().includes($('sku').value.toLowerCase())&&matchesScope(x,$('risk').value));
    $('count').textContent=`当前显示 ${filtered.length} / ${r.inventory.length} 项；其中预计有缺口 ${filtered.filter(hasShortage).length} 项、建议补货 ${filtered.filter(needsReorder).length} 项（两者可重叠）。`;
    const retained=filtered.find(x=>entityKey(x)===selectedKey);
    if(retained)showEntity(retained,false);
    else clearDetail(!filtered.length?'当前筛选无匹配项，请调整仓库、SKU 或缺口范围。':selectedKey?'所选条目已被筛选排除，请在表中重新选择“查看”。':'点击上方库存表的“查看”，分析每日库存与到货节奏。');
    renderRows();
}
function showEntity(x,reset=true){
    selected=x;selectedKey=entityKey(x);
    $('detail-title').textContent=`${x.sku} / ${x.warehouse} · 逐日库存分析`;
    $('trace').textContent=JSON.stringify(x,null,2);
    const path=Array.isArray(x.time_path)?x.time_path:[];
    const state=riskState(x);
    const arrivalTotal=path.reduce((total,p)=>total+p.arrival,0),demandTotal=path.reduce((total,p)=>total+p.demand,0);
    $('decision-explanation').hidden=false;
    $('decision-explanation').innerHTML=`<p><span class="status-tag status-${state.key}">${state.label}</span> ${state.note}</p>
        <p><b>当前建议：</b>补货 ${qty(x.reorder_suggestion_units)} 件；预计采购额 ${fmt(x.reorder_cost_cny)} CNY。${x.reorder_suggestion_units===0?'0 是真实规则输出，不代表缺货判断或数据缺失。':''}</p>
        <p><b>缺口依据：</b>初始净余额 ${qty(x.on_hand-x.backlog)} 件（现货 ${qty(x.on_hand)} − 积压 ${qty(x.backlog)}），逐日加预计到货、减预测需求；首次余额小于 0 的日期为首次缺口日。${shortageLabel(x)}。最大净缺口为快照及预测期最负余额的绝对值，最低取 0。</p>
        <p><b>预测窗口：</b>${qty(x.horizon_days)} 天 = 情景采购交期 ${qty(x.lead_days)} 天 + 7 天。${path.length?`窗口预测需求合计 ${qty(demandTotal)} 件，窗口有效预计到货合计 ${qty(arrivalTotal)} 件（按展示轨迹汇总）。`:'当前缺少逐日轨迹，无法展示需求与到货合计。'}</p>
        <p><b>到货依据：</b>仅计入快照后、尚未收货的有效预计到货；情景延迟已计入日期。过期未确认 ETA 不自动变成可用库存，窗口外到货不抵扣本窗口补货。</p>
        <p><b>补货依据：</b>建议量 = max(0，向上取整〔窗口预测需求 + 安全库存缓冲 − 现货 + 积压 − 窗口有效预计到货〕)。安全库存缓冲 = 窗口日均预测需求 × 库存配置中的安全天数。无缺口也可能需要补足缓冲；后期到货充足也不保证前期无缺口。</p>
        <p class="muted">预计采购额 = 后台建议补货量 × 库存配置单价；不表示已下单或节约金额。页面不从舍入后的轨迹反推安全天数或重算建议量，建议补货也不会自动加入到货柱状图。</p>`;
    points=path.length?[{day:0,demand:null,arrival:null,balance:x.on_hand-x.backlog},...path]:[];
    $('chart-content').hidden=!points.length;$('chart-empty').hidden=!!points.length;
    if(!points.length){
        $('chart-empty').textContent='该条目暂无逐日预测数据，可展开原始 JSON 核查。';
        ['balance-chart','flow-chart','detail-summary','day-select','day-detail'].forEach(id=>$(id).innerHTML='');
        $('chart-hover').textContent='';$('day-caption').textContent='';return;
    }
    const shortage=x.first_shortage_day;
    const shortageText=shortage==null?'预测期无缺口':shortage===0?`快照已存在净缺口 · ${dateAt(0)}`:`首次缺口：${dayLabel(shortage)}`;
    $('detail-summary').innerHTML=`<span>${path.length} 天预测 · ${dateAt(path[0].day)} 至 ${dateAt(path.at(-1).day)}</span><span class="${shortage==null?'':'risk-tag'}">${esc(shortageText)}</span><span>最大净缺口 ${qty(x.peak_net_shortage_units)} 件</span>`;
    $('day-select').innerHTML=points.map(p=>`<option value="${p.day}">${dayLabel(p.day)}</option>`).join('');
    if(reset||!points.some(p=>p.day===selectedDay))selectedDay=shortage!=null&&points.some(p=>p.day===shortage)?shortage:path[0].day;
    $('chart-hover').textContent='悬停任一日期列，查看每日数值。';
    if(reset)$('chart-scroll').scrollLeft=0;
    selectDay(selectedDay);
}
function selectDay(day){
    const p=points.find(p=>p.day===day);if(!p)return;
    selectedDay=day;$('day-select').value=String(day);
    $('day-caption').textContent=dayLabel(day);
    $('day-detail').innerHTML=[['预测需求',p.demand,'件/日'],['预计到货',p.arrival,'件/日'],[day===0?'快照净余额':'日末净余额',p.balance,'件']].map(([label,v,unit],i)=>`<div class="day-metric${i===2&&v<0?' negative':''}"><span>${label}</span><strong>${qty(v)}${v==null?'':` <small>${unit}</small>`}</strong></div>`).join('');
    drawCharts();
}
function drawCharts(){
    const n=points.length,W=Math.max(960,n*72+100),L=76,R=W-30,T=48,B=230,step=(R-L)/n;
    const x=i=>L+step*(i+.5),lastDay=points.at(-1).day;
    $('chart-stack').style.minWidth=`${Math.max(780,n*52+100)}px`;
    const labels=points.map((p,i)=>`<text x="${x(i)}" y="252" text-anchor="middle">第 ${p.day} 天</text><text x="${x(i)}" y="270" text-anchor="middle">${dateAt(p.day).slice(5)}</text>`).join('');
    const chosen=points.findIndex(p=>p.day===selectedDay);
    const guide=`<line x1="${x(chosen)}" x2="${x(chosen)}" y1="${T}" y2="${B}" stroke="#126f7a" stroke-dasharray="3 4" opacity=".65"/>`;
    const hits=points.map((p,i)=>`<rect class="hit" data-day="${p.day}" x="${L+step*i}" y="${T}" width="${step}" height="${282-T}" fill="transparent"><title>${esc(dayText(p))}</title></rect>`).join('');
    const frame=(title,content)=>`<svg viewBox="0 0 ${W} 286" role="img" aria-label="${esc(title)}；${dateAt(0)} 至 ${dateAt(lastDay)}；可用下方日期选择框查看明细"><title>${esc(title)}</title>${content}${labels}${guide}${hits}</svg>`;
    function axis(y,lo,hi){return Array.from({length:5},(_,i)=>{const v=lo+(hi-lo)*i/4;return `<line x1="${L}" x2="${R}" y1="${y(v)}" y2="${y(v)}" stroke="#e4ebf0"/><text x="${L-10}" y="${y(v)+4}" text-anchor="end">${fmt(v)}</text>`;}).join('');}
    const low=Math.min(0,...points.map(p=>p.balance)),high=Math.max(0,...points.map(p=>p.balance));
    const padding=(high-low||1)*.12,lo=low<0?low-padding:0,hi=high+padding;
    const y=v=>B-(v-lo)/(hi-lo)*(B-T),zero=y(0);
    const risk=points.map((p,i)=>p.balance<0?`<rect data-risk-day="${p.day}" x="${L+i*step}" y="${zero}" width="${step}" height="${B-zero}" fill="#f8d5cd"/>`:'').join('');
    const line=`<polyline data-series="balance" points="${points.map((p,i)=>`${x(i)},${y(p.balance)}`).join(' ')}" fill="none" stroke="#126f7a" stroke-width="3" stroke-linejoin="round"/>`;
    const dots=points.map((p,i)=>`<circle cx="${x(i)}" cy="${y(p.balance)}" r="3.5" fill="${p.balance<0?'#b13c2e':'#126f7a'}"/>`).join('');
    const first=points.findIndex(p=>p.day===selected.first_shortage_day);
    let marker='';
    if(first>=0){const p=points[first],label=first===0?'快照已有缺口':`首次缺口 · 第 ${p.day} 天`;marker=`<g data-first-shortage="${p.day}"><line x1="${x(first)}" x2="${x(first)}" y1="${T-6}" y2="${B}" stroke="#b13c2e" stroke-width="1.5" stroke-dasharray="5 4"/><circle cx="${x(first)}" cy="${y(p.balance)}" r="6" fill="#b13c2e" stroke="white" stroke-width="2"/><text class="marker-label" x="${Math.max(L+72,Math.min(R-72,x(first)))}" y="26" text-anchor="middle">${label}</text></g>`;}
    $('balance-chart').innerHTML=frame('预测库存净余额（件）',risk+axis(y,lo,hi)+`<line data-zero-line="true" x1="${L}" x2="${R}" y1="${zero}" y2="${zero}" stroke="#6b7d8b" stroke-width="1.5"/><text x="${R}" y="${zero-6}" text-anchor="end">零余额基准</text>`+line+dots+marker);
    const top=Math.max(1,...points.flatMap(p=>[p.demand??0,p.arrival??0]))*1.12,fy=v=>B-v/top*(B-T),bw=Math.min(22,step*.3);
    const bars=points.map((p,i)=>p.day===0?'':`<rect data-series="demand" data-value="${p.demand}" x="${x(i)-bw-2}" y="${fy(p.demand)}" width="${bw}" height="${B-fy(p.demand)}" rx="2" fill="#5376bb"/><rect data-series="arrival" data-value="${p.arrival}" x="${x(i)+2}" y="${fy(p.arrival)}" width="${bw}" height="${B-fy(p.arrival)}" rx="2" fill="#c47b20"/>`).join('');
    $('flow-chart').innerHTML=frame('预测需求与预计到货（件/日）',axis(fy,0,top)+bars);
}
['warehouse','risk'].forEach(id=>$(id).addEventListener('change',update));
$('sku').addEventListener('input',update);
$('inventory').addEventListener('click',e=>{const index=e.target.dataset.index;if(index!==undefined&&filtered[Number(index)]){showEntity(filtered[Number(index)]);renderRows();}});
['balance-chart','flow-chart'].forEach(id=>{
    $(id).addEventListener('pointerover',e=>{const day=e.target.dataset.day;if(day!==undefined){const p=points.find(p=>p.day===Number(day));if(p)$('chart-hover').textContent=dayText(p);}});
    $(id).addEventListener('pointerleave',()=>{$('chart-hover').textContent='悬停任一日期列，查看每日数值。';});
    $(id).addEventListener('click',e=>{if(e.target.dataset.day!==undefined)selectDay(Number(e.target.dataset.day));});
});
$('day-select').addEventListener('change',()=>selectDay(Number($('day-select').value)));
update();
$('download').onclick=()=>{const fields=['sku','warehouse','on_hand','coverage_days','first_shortage_day','peak_net_shortage_units','reorder_suggestion_units'];const cell=v=>'"'+String(v??'').replace(/^[=+@-]/,"'").replace(/"/g,'""')+'"';const csv='\ufeff'+[fields.join(','),...filtered.map(x=>fields.map(k=>cell(x[k])).join(','))].join('\\r\\n');const u=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download='filtered_inventory_synthetic.csv';a.click();URL.revokeObjectURL(u);};
</script></html>'''
    fragments = {'__PAYLOAD__': payload, '__EVIDENCE__': evidence,
                 '__AI_PANEL__': ai_panel, '__AI_WARNING__': ai_warning}
    page = re.sub(r'__(?:PAYLOAD|EVIDENCE|AI_PANEL|AI_WARNING)__',
                  lambda match: fragments[match.group()], template)
    Path(path).write_text(page,encoding='utf-8',newline='\n')
