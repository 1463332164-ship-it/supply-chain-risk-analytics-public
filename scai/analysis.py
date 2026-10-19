"""Transparent baselines, due-cohort OTD and time-phased inventory heuristics."""
from collections import Counter, defaultdict
from datetime import timedelta
from math import ceil
from statistics import mean

MODELS = ("naive", "seasonal7", "ma28")


def forecast(history, horizon, model):
    if not history or horizon<1: raise ValueError("empty history or invalid horizon")
    if model == "naive": return [float(history[-1])] * horizon
    if model == "ma28": return [mean(history[-28:])] * horizon
    if model == "seasonal7":
        if len(history)<7: raise ValueError("seasonal7 needs 7 observations")
        return [float(history[-7 + i%7]) for i in range(horizon)]
    raise ValueError("unknown model")


def score(actual, predicted):
    if len(actual)!=len(predicted) or not actual: raise ValueError("invalid score vectors")
    den=sum(actual)
    err=[p-a for a,p in zip(actual,predicted)]
    return {"mae":sum(abs(e) for e in err)/len(err),"wape":sum(abs(e) for e in err)/den if den else None,"bias":sum(err)/den if den else None,"n":len(err)}


def evaluate(series):
    detail=[]
    for (sku,wh), rows in sorted(series.items()):
        y=[r["demand_units"] for r in rows]
        for phase, cuts in [("validation",range(124,152,7)),("test",range(152,180,7))]:
            for cut in cuts:
                for model in MODELS:
                    pred=forecast(y[:cut],7,model)
                    for h,(a,p) in enumerate(zip(y[cut:cut+7],pred),1):
                        detail.append({"sku":sku,"warehouse":wh,"phase":phase,"cutoff":rows[cut-1]["date"].isoformat(),"target_date":rows[cut+h-1]["date"].isoformat(),"horizon":h,"model":model,"actual":a,"forecast":p})
    metrics={}
    for phase in ("validation","test"):
        metrics[phase]={}
        for model in MODELS:
            selected=[r for r in detail if r["phase"]==phase and r["model"]==model]
            metrics[phase][model]=score([r["actual"] for r in selected],[r["forecast"] for r in selected])
    winner=min(MODELS,key=lambda m:metrics["validation"][m]["mae"])
    return winner,metrics,detail


def delivery(orders, asof):
    due=[r for r in orders if asof-timedelta(days=27)<=r["promised_date"]<=asof]
    ontime=[r for r in due if r["received_date"] is not None and r["received_date"]<=r["promised_date"]]
    return {"due_orders":len(due),"on_time_orders":len(ontime),"otd":len(ontime)/len(due) if due else None}


def inventory_risk(inv, orders, history, asof, model, demand_factor=1.0, delay_days=0):
    lead=inv["lead_days"]+delay_days
    horizon=lead+7
    daily=[v*demand_factor for v in forecast(history,horizon,model)]
    avg=mean(daily)
    arrivals=defaultdict(int)
    for r in orders:
        # Stale ETA is unconfirmed: do not silently make overdue stock available today.
        if r["received_date"] is None and r["expected_date"]>asof:
            arrivals[(r["expected_date"]-asof).days+delay_days]+=r["qty"]
    balance=inv["on_hand"]-inv["backlog"]
    minimum=balance
    first_shortage=0 if balance<0 else None
    path=[]
    for day,units in enumerate(daily,1):
        balance+=arrivals[day]-units  # arrivals at start of day; demand at end
        minimum=min(minimum,balance)
        if balance<0 and first_shortage is None: first_shortage=day
        path.append({"day":day,"arrival":arrivals[day],"demand":round(units,4),"balance":round(balance,4)})
    eligible=sum(q for d,q in arrivals.items() if 1<=d<=horizon)
    target=sum(daily)+avg*inv["safety_days"]
    replenish=max(0,ceil(target-inv["on_hand"]+inv["backlog"]-eligible))
    return {"sku":inv["sku"],"warehouse":inv["warehouse"],"source_row":inv["source_row"],"model":model,"on_hand":inv["on_hand"],"backlog":inv["backlog"],"lead_days":lead,"horizon_days":horizon,"forecast_daily":round(avg,4),"coverage_days":round(inv["on_hand"]/avg,4) if avg else None,"first_shortage_day":first_shortage,"peak_net_shortage_units":round(max(0,-minimum),4),"reorder_suggestion_units":replenish,"reorder_cost_cny":round(replenish*inv["unit_cost_cny"],2),"time_path":path}


def analyze(tables,series,asof,demand_factor=1.0,delay_days=0):
    if not 0<demand_factor<=5 or not 0<=delay_days<=60: raise ValueError("scenario out of allowed range")
    winner,metrics,detail=evaluate(series)
    by_entity=defaultdict(list)
    for r in tables["orders"]: by_entity[(r["sku"],r["warehouse"])].append(r)
    inventory=[]
    evidence=[]
    for inv in tables["inventory"]:
        key=(inv["sku"],inv["warehouse"])
        risk=inventory_risk(inv,by_entity[key],[r["demand_units"] for r in series[key]],asof,winner,demand_factor,delay_days)
        inventory.append(risk)
        if risk["first_shortage_day"] is not None:
            evidence.append({"id":f"INV-{key[0]}-{key[1]}","type":"projected_shortage","priority":"high","sku":key[0],"warehouse":key[1],"source":f"inventory.csv:{inv['source_row']}; demand.csv:{key[0]}/{key[1]}; orders.csv:{key[0]}/{key[1]}","metrics":{"first_shortage_day":risk["first_shortage_day"],"peak_net_shortage_units":risk["peak_net_shortage_units"],"reorder_suggestion_units":risk["reorder_suggestion_units"]},"meaning":"预测下的净缺口，非已发生缺货；补货建议可能来不及弥补前段缺口，需要人工核查调拨/催交。"})
        elif risk["coverage_days"] is not None and risk["coverage_days"]>45:
            evidence.append({"id":f"EXCESS-{key[0]}-{key[1]}","type":"excess_coverage","priority":"medium","sku":key[0],"warehouse":key[1],"source":f"inventory.csv:{inv['source_row']}","metrics":{"coverage_days":risk["coverage_days"]},"meaning":"超过固定45日教学阈值；未考虑季节备货、MOQ及产品生命周期，不能直接判定呆滞。"})
    for r in tables["orders"]:
        if r["received_date"] is None and r["promised_date"]<asof:
            evidence.append({"id":r["order_id"],"type":"overdue_purchase_order","priority":"high","sku":r["sku"],"warehouse":r["warehouse"],"source":f"orders.csv:{r['source_row']}","metrics":{"overdue_days":(asof-r["promised_date"]).days,"open_units":r["qty"]},"meaning":"截至快照仍未全量收货且已超过承诺日期；原因未知。"})
    suppliers=[]
    for supplier in sorted({r['supplier'] for r in tables['orders']}):
        suppliers.append({"supplier":supplier,**delivery([r for r in tables['orders'] if r['supplier']==supplier],asof)})
    summary={"as_of":asof.isoformat(),"data_origin":"synthetic","demand_rows":len(tables['demand']),"series":len(series),"sku_count":len({k[0] for k in series}),"warehouse_count":len({k[1] for k in series}),"history_days":180,"selected_model":winner,"demand_factor":demand_factor,"delay_days":delay_days,"shortage_entities":sum(r['first_shortage_day'] is not None for r in inventory),"evidence_counts":dict(Counter(e['type'] for e in evidence)),"reorder_suggestion_units":sum(r['reorder_suggestion_units'] for r in inventory),"reorder_cost_cny":round(sum(r['reorder_cost_cny'] for r in inventory),2),**delivery(tables['orders'],asof)}
    return {"summary":summary,"metrics":metrics,"inventory":inventory,"evidence":evidence,"suppliers":suppliers},detail
