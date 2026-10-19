// Dependency-free DOM harness; not a browser/layout test.
// node scripts/check_dashboard.mjs [HTML file] [optional JSON report path]
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const file=process.argv[2]||'examples/base/dashboard_ai.html';
const html=fs.readFileSync(file,'utf8');
const payload=JSON.parse(html.match(/<script id="payload" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const code=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
const checks=[];
function check(name,fn){fn();checks.push(name);}
const updatedUI=/id="(?:evidence-details|ai-details)"|class="evidence-item"/.test(html);
// Secondary panels are emitted as escaped HTML by Python, not inserted by JS.
// This harness checks their data; native details behavior/layout needs a browser.
const decodeText=text=>text.replace(/&(amp|lt|gt|quot|#x27|#39);/g,(_,key)=>({amp:'&',lt:'<',gt:'>',quot:'"','#x27':"'",'#39':"'"}[key]));
function boot(input=payload){
    const nodes=new Map();let downloaded=false,blob='';
    function node(id){if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:id==='risk'?'all':'',hidden:false,open:false,style:{},listeners:{},addEventListener(k,f){this.listeners[k]=f;}});return nodes.get(id);}
    node('payload').textContent=JSON.stringify(input);
    const context={document:{getElementById:node,createElement:()=>({click(){downloaded=true;}})},Blob:class{constructor(parts){blob=parts.join('');}},URL:{createObjectURL:()=> 'mock',revokeObjectURL(){}},console};
    vm.runInNewContext(code,context,{timeout:5000});
    const event=(id,type,dataset={})=>node(id).listeners[type]({target:{dataset}});
    const filter=(id,value)=>{node(id).value=value;event(id,id==='sku'?'input':'change');};
    const select=(index=0)=>event('inventory','click',{index:String(index)});
    return {node,event,filter,select,count:()=> (node('inventory').innerHTML.match(/<tr(?:\s[^>]*)?>/g)||[]).length,download(){node('download').onclick();return {downloaded,blob};}};
}
const app=boot();
const sample=payload.result.inventory.find(x=>x.sku==='SKU001'&&x.warehouse==='WH1');
assert.ok(sample,'This regression suite expects the supplied demo dataset.');
check('initial rows and unselected state',()=>{assert.equal(app.count(),90);assert.equal(app.node('chart-content').hidden,true);});
check('warehouse and SKU filtering',()=>{app.filter('warehouse','WH1');assert.equal(app.count(),30);app.filter('sku','sku001');assert.equal(app.count(),1);});
check('selection renders both charts and exact JSON trace',()=>{
    app.select();assert.equal(app.node('chart-content').hidden,false);
    assert.match(app.node('balance-chart').innerHTML,/<svg/);assert.match(app.node('flow-chart').innerHTML,/<svg/);
    assert.deepEqual(JSON.parse(app.node('trace').textContent),sample);assert.match(app.node('detail-title').textContent,/SKU001 \/ WH1/);
});
check('first shortage marker, zero line and risk shading',()=>{
    assert.ok(app.node('balance-chart').innerHTML.includes(`data-first-shortage="${sample.first_shortage_day}"`));assert.match(app.node('balance-chart').innerHTML,/data-zero-line/);
    for(const p of sample.time_path)assert.equal(app.node('balance-chart').innerHTML.includes(`data-risk-day="${p.day}"`),p.balance<0);
});
check('every source date supports click, hover and precise daily values',()=>{
    for(const p of sample.time_path){
        app.event('flow-chart','click',{day:String(p.day)});assert.equal(app.node('day-select').value,String(p.day));
        for(const value of [p.demand,p.arrival,p.balance])assert.ok(app.node('day-detail').innerHTML.includes(Number(value).toLocaleString('zh-CN',{maximumFractionDigits:4})));
        app.event('balance-chart','pointerover',{day:String(p.day)});assert.ok(app.node('chart-hover').textContent.includes(`第 ${p.day} 天`));
    }
    app.event('balance-chart','pointerleave');assert.match(app.node('chart-hover').textContent,/悬停/);
});
check('date selection, snapshot and full date labels',()=>{
    app.node('day-select').value='0';app.event('day-select','change');assert.match(app.node('day-caption').textContent,/2026-10-17/);assert.match(app.node('day-detail').innerHTML,/不适用/);
    app.event('balance-chart','click',{day:'3'});assert.match(app.node('day-caption').textContent,/2026-10-20/);assert.match(app.node('balance-chart').innerHTML,/10-20/);
});
check('SKU001 WH1 matches the independently checked base or stress trajectory',()=>{
    if(payload.result.summary.demand_factor===1&&payload.result.summary.delay_days===0){
        assert.equal(sample.first_shortage_day,3);
        assert.deepEqual(sample.time_path.slice(0,3).map(p=>p.balance),[24,4,-15]);
        assert.deepEqual(sample.time_path[5],{day:6,arrival:128,demand:18,balance:59});
    }else if(payload.result.summary.demand_factor===1.25&&payload.result.summary.delay_days===7){
        assert.equal(sample.first_shortage_day,2);assert.equal(sample.time_path[1].balance,-3);
        assert.deepEqual(sample.time_path[12],{day:13,arrival:128,demand:22.5,balance:-105});
    }
});
check('selection persists when still inside filter',()=>{app.filter('risk','shortage');assert.equal(app.node('chart-content').hidden,false);assert.equal(app.node('day-select').value,'3');});
check('CSV still exports the filtered rows',()=>{const d=app.download();assert.ok(d.downloaded);assert.match(d.blob,/SKU001/);assert.match(d.blob,/\r\n/);assert.equal(d.blob.split('\r\n').length,2);});
check('AI presence or absence preserves the complete server-rendered draft',()=>{
    if(!updatedUI){
        assert.ok(payload.ai?app.node('ai').innerHTML.includes('INV-SKU001-WH1'):app.node('ai').innerHTML.includes('尚未导入'));
        return; // Explicit legacy contract for unchanged historical examples.
    }
    const raw=html.match(/<pre id="ai-raw" class="raw-json">([\s\S]*?)<\/pre>/);
    if(payload.ai!=null){
        assert.ok(raw);assert.deepEqual(JSON.parse(decodeText(raw[1])),payload.ai);
        assert.match(html,/条建议 · 待人工审核/);assert.doesNotMatch(html,/id="ai-warning"/);
    }else{assert.equal(raw,null);assert.match(html,/未导入AI草稿/);assert.match(html,/尚未导入 AI 草稿/);}
});
if(updatedUI){
check('secondary panels start collapsed using native details',()=>{
    for(const id of ['evidence-details','ai-details']){
        const tag=html.match(new RegExp(`<details\\b[^>]*id="${id}"[^>]*>`));
        assert.ok(tag);assert.doesNotMatch(tag[0],/\bopen(?:\s|=|>)/);
    }
    assert.match(html,/AI建议与人工审核/);
});
check('every original evidence record is retained in its original order',()=>{
    const raw=[...html.matchAll(/<pre class="raw-json evidence-raw">([\s\S]*?)<\/pre>/g)].map(x=>JSON.parse(decodeText(x[1])));
    assert.deepEqual(raw,payload.result.evidence);
    assert.ok(html.includes(`>${payload.result.evidence.length} 条证据</span>`));
});
check('evidence metric and source values are preserved without display rounding',()=>{
    // Restrict to the evidence section; AI items also have metric blocks.
    const evidence=html.slice(html.indexOf('<details id="evidence-details"'),html.indexOf('<details id="ai-details"'));
    const metrics=[...evidence.matchAll(/<pre class="metric-json">([\s\S]*?)<\/pre>/g)].map(x=>JSON.parse(decodeText(x[1])));
    const sources=[...evidence.matchAll(/<pre class="source-text">([\s\S]*?)<\/pre>/g)].map(x=>decodeText(x[1]));
    assert.deepEqual(metrics,payload.result.evidence.map(x=>x.metrics));
    assert.deepEqual(sources,payload.result.evidence.map(x=>x.source));
});
check('formal review remains in the Python workflow with no page approval controls',()=>{
    const panel=html.slice(html.indexOf('<details id="ai-details"'),html.indexOf('<footer>'));
    for(const label of ['validate-ai → review','response_sha256','不产生批准','不执行采购'])assert.ok(panel.includes(label));
    assert.doesNotMatch(panel,/<(?:button|input)\b/);
});
}
check('filtered out selection clears all stale charts and JSON',()=>{
    app.filter('warehouse','WH2');assert.equal(app.node('chart-content').hidden,true);assert.equal(app.node('balance-chart').innerHTML,'');assert.equal(app.node('flow-chart').innerHTML,'');assert.equal(app.node('day-detail').innerHTML,'');assert.doesNotMatch(app.node('trace').textContent,/time_path/);assert.match(app.node('chart-empty').textContent,/重新选择/);
    app.filter('risk','all');app.select();assert.match(app.node('detail-title').textContent,/SKU001 \/ WH2/);
});
check('no matching rows clear detail and export header only',()=>{app.filter('sku','<img>');assert.equal(app.count(),0);assert.equal(app.node('chart-content').hidden,true);assert.match(app.node('chart-empty').textContent,/无匹配/);assert.equal(app.download().blob.split('\r\n').length,1);});
check('shortage filter count and null handling',()=>{app.filter('warehouse','');app.filter('sku','');app.filter('risk','shortage');assert.equal(app.count(),payload.result.inventory.filter(x=>x.first_shortage_day!==null).length);});
function fixture(overrides={},asof='2026-10-17'){
    const data=structuredClone(payload);data.ai=null;data.result.summary.as_of=asof;data.result.inventory=[{...sample,...overrides}];return boot(data);
}
check('no shortage and all-zero series have finite chart coordinates',()=>{
    const a=fixture({on_hand:0,backlog:0,first_shortage_day:null,peak_net_shortage_units:0,time_path:[{day:1,demand:0,arrival:0,balance:0}]});a.select();
    assert.match(a.node('detail-summary').innerHTML,/预测期无缺口/);assert.doesNotMatch(a.node('balance-chart').innerHTML,/data-first-shortage|data-risk-day|NaN|Infinity/);assert.doesNotMatch(a.node('flow-chart').innerHTML,/NaN|Infinity/);
    a.filter('risk','shortage');assert.equal(a.count(),0);assert.equal(a.node('chart-content').hidden,true);
});
check('day zero shortage survives recovery on day one',()=>{
    const a=fixture({on_hand:0,backlog:10,first_shortage_day:0,time_path:[{day:1,demand:0,arrival:20,balance:10}]});a.select();
    assert.match(a.node('balance-chart').innerHTML,/data-first-shortage="0"/);assert.match(a.node('detail-summary').innerHTML,/快照已存在净缺口/);assert.equal(a.node('day-select').value,'0');a.filter('risk','shortage');assert.equal(a.count(),1);
});
check('backend shortage flag is authoritative despite rounding to zero',()=>{
    const a=fixture({first_shortage_day:1,time_path:[{day:1,demand:1,arrival:0,balance:0}]});a.select();assert.match(a.node('balance-chart').innerHTML,/data-first-shortage="1"/);
});
check('empty or missing time_path clears earlier chart and preserves JSON',()=>{
    for(const path of [[],null,undefined]){const a=fixture({time_path:path});a.select();assert.equal(a.node('chart-content').hidden,true);assert.equal(a.node('balance-chart').innerHTML,'');assert.match(a.node('chart-empty').textContent,/暂无逐日/);assert.equal(JSON.parse(a.node('trace').textContent).sku,sample.sku);}
    const d=structuredClone(payload);d.result.inventory[1].time_path=[];const a=boot(d);a.select(0);a.select(1);assert.equal(a.node('balance-chart').innerHTML,'');assert.equal(a.node('day-detail').innerHTML,'');
});
check('empty inventory is safe',()=>{const d=structuredClone(payload);d.result.inventory=[];const a=boot(d);assert.equal(a.count(),0);assert.equal(a.node('chart-content').hidden,true);});
check('UTC dates cross leap day and year boundary correctly',()=>{
    for(const [start,expected] of [['2028-02-28','2028-02-29'],['2026-12-31','2027-01-01']]){const a=fixture({first_shortage_day:null,time_path:[{day:1,demand:1,arrival:0,balance:10}]},start);a.select();assert.ok(a.node('day-caption').textContent.includes(expected));}
});
check('long horizon supports final date without truncation',()=>{
    const path=Array.from({length:90},(_,i)=>({day:i+1,demand:1.25,arrival:0,balance:100-(i+1)*1.25}));const a=fixture({time_path:path,first_shortage_day:81});a.select();a.event('balance-chart','click',{day:'90'});assert.match(a.node('day-caption').textContent,/2027-01-15/);assert.match(a.node('balance-chart').innerHTML,/第 90 天/);
});
check('entity text is escaped and rendering never mutates business input',()=>{
    const d=structuredClone(payload);d.result.inventory[0].sku='<img src=x onerror=alert(1)>';const before=JSON.stringify(d);const a=boot(d);a.select();assert.doesNotMatch(a.node('inventory').innerHTML,/<img/);assert.equal(JSON.stringify(d),before);assert.equal(a.node('payload').textContent,before);
});
check('four states keep shortage and reorder independent; zero stays numeric',()=>{
    for(const [first,reorder,label] of [[2,30,'有缺口且需补货'],[2,0,'有缺口但当前建议补货为0'],[null,30,'无缺口但需补货'],[null,0,'无缺口且无需补货']]){
        const a=fixture({first_shortage_day:first,reorder_suggestion_units:reorder,reorder_cost_cny:reorder*2,peak_net_shortage_units:first===null?0:10});a.select();
        assert.ok(a.node('inventory').innerHTML.includes(label));assert.ok(a.node('decision-explanation').innerHTML.includes(label));
        if(first===null){assert.match(a.node('inventory').innerHTML,/预测期无缺口/);assert.match(a.node('inventory').innerHTML,/<td>0<small class="field-note">预测期无净缺口/);}
        if(reorder===0){assert.match(a.node('inventory').innerHTML,/<td>0<small class="field-note">当前规则未建议新增采购/);assert.match(a.node('inventory').innerHTML,/<td>0<small class="field-note">建议量 × 单价为 0/);}
        a.filter('risk','reorder');assert.equal(a.count(),reorder>0?1:0);
        a.filter('risk','buffer_reorder');assert.equal(a.count(),first===null&&reorder>0?1:0);
        a.filter('risk','shortage');assert.equal(a.count(),first!==null?1:0);
    }
});
check('null and day zero have distinct explicit table labels',()=>{
    const a=fixture({first_shortage_day:0,reorder_suggestion_units:0});assert.match(a.node('inventory').innerHTML,/第 0 天（快照已有缺口）/);assert.doesNotMatch(a.node('inventory').innerHTML,/预测期无缺口/);
    a.filter('risk','shortage');assert.equal(a.count(),1);a.filter('risk','reorder');assert.equal(a.count(),0);
});
check('all four scopes match source rows and CSV export',()=>{
    const a=boot();
    for(const [scope,predicate] of [['all',()=>true],['shortage',x=>x.first_shortage_day!==null],['reorder',x=>x.reorder_suggestion_units>0],['buffer_reorder',x=>x.first_shortage_day===null&&x.reorder_suggestion_units>0]]){
        a.filter('risk',scope);const expected=payload.result.inventory.filter(predicate);assert.equal(a.count(),expected.length);
        const csv=a.download().blob.split('\r\n');assert.equal(csv.length,expected.length+1);
        expected.forEach((x,i)=>assert.ok(csv[i+1].startsWith(`"${x.sku}","${x.warehouse}"`)));
    }
    if(payload.result.summary.demand_factor===1&&payload.result.summary.delay_days===0){
        for(const [scope,count] of [['all',90],['shortage',17],['reorder',21],['buffer_reorder',4]]){a.filter('risk',scope);assert.equal(a.count(),count);}
    }
});
check('new scopes keep selected chart or clear it with its explanation',()=>{
    const a=boot();a.filter('warehouse','WH1');a.filter('sku','SKU001');a.select();a.event('balance-chart','click',{day:'6'});
    a.filter('risk','reorder');assert.match(a.node('balance-chart').innerHTML,/<svg/);assert.equal(a.node('day-select').value,'6');assert.equal(a.node('decision-explanation').hidden,false);
    a.filter('risk','buffer_reorder');assert.equal(a.count(),0);assert.equal(a.node('balance-chart').innerHTML,'');assert.equal(a.node('flow-chart').innerHTML,'');assert.equal(a.node('decision-explanation').innerHTML,'');assert.equal(a.node('decision-explanation').hidden,true);
    const b=fixture({first_shortage_day:null,reorder_suggestion_units:30});b.select();b.filter('risk','buffer_reorder');assert.equal(b.node('chart-content').hidden,false);assert.match(b.node('detail-summary').innerHTML,/预测期无缺口/);b.filter('risk','shortage');assert.equal(b.node('chart-content').hidden,true);
});
check('detail explains horizon, arrivals, safety buffer and true zero cost',()=>{
    const a=fixture({reorder_suggestion_units:30,reorder_cost_cny:0});a.select();
    const explanation=a.node('decision-explanation').innerHTML;
    for(const label of ['预测窗口','安全库存缓冲','安全天数','有效预计到货','过期未确认 ETA','向上取整','预计采购额 0 CNY','补货 30 件'])assert.ok(explanation.includes(label));
    assert.match(a.node('inventory').innerHTML,/有缺口且需补货/);
    const b=fixture({first_shortage_day:2,reorder_suggestion_units:0});b.select();assert.match(b.node('decision-explanation').innerHTML,/调拨或催交/);
});
const report={status:'passed',file,checked_at_utc:new Date().toISOString(),test_type:'JavaScript DOM harness; not browser rendering',ui_contract:updatedUI?'collapsible_evidence_and_ai':'legacy_expanded',checks_count:checks.length,checks,browser_visual_status:'not assessed by this script'};
if(process.argv[3])fs.writeFileSync(process.argv[3],JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
