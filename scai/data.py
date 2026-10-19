"""Explicit CSV contracts. Invalid input fails closed; no silent imputation."""
import csv
import hashlib
import io
import json
import math
import random
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from types import MappingProxyType

from .output import plain_path, publish_bundle

ASOF = date(2026, 10, 17)
SCHEMAS = {
    "demand": ["date", "sku", "warehouse", "demand_units", "data_origin"],
    "inventory": ["as_of", "sku", "warehouse", "on_hand", "backlog", "lead_days", "safety_days", "unit_cost_cny", "data_origin"],
    "orders": ["order_id", "sku", "warehouse", "supplier", "order_date", "promised_date", "expected_date", "received_date", "qty", "data_origin"],
}


def dump(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def write_csv(path, rows, fields=None):
    rows = list(rows)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _input_states(folder):
    states = []
    for name in sorted(SCHEMAS):
        path = plain_path(folder / f'{name}.csv')
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f'input must be a regular file: {path}')
        states.append((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
    return tuple(states)


@dataclass(frozen=True)
class InputSnapshot:
    """Immutable CSV bytes used by both parsing and the unchanged v1 digest.

    Repeated observations detect normal edits, not a multi-file filesystem
    transaction. Even if an external edit evades detection, parsed values and
    the digest still come from these exact bytes, never a later disk read.
    """
    folder: Path
    raw: Mapping[str, bytes]
    states: tuple

    @property
    def sha256(self):
        h = hashlib.sha256()
        for name in sorted(SCHEMAS):
            h.update(name.encode())
            h.update(self.raw[name])
        return h.hexdigest()

    def assert_unchanged(self):
        if _input_states(self.folder) != self.states:
            raise ValueError('input files changed during snapshot processing')
        for name in sorted(SCHEMAS):
            if (self.folder / f'{name}.csv').read_bytes() != self.raw[name]:
                raise ValueError('input files changed during snapshot processing')
        if _input_states(self.folder) != self.states:
            raise ValueError('input files changed during snapshot processing')


def read_snapshot(folder):
    folder = plain_path(folder)
    states = _input_states(folder)
    raw = {name: (folder / f'{name}.csv').read_bytes() for name in sorted(SCHEMAS)}
    snapshot = InputSnapshot(folder, MappingProxyType(raw), states)
    snapshot.assert_unchanged()
    return snapshot


def fingerprint(folder):
    return read_snapshot(folder).sha256


def generate(folder, seed=20261018):
    def build(staging):
        _generate(staging, seed)
        load(staging)  # Validate the complete generated bundle before publishing.
    publish_bundle(folder, (), build)


def _generate(folder, seed):
    rng = random.Random(seed)
    demand, inventory, orders = [], [], []
    for s in range(1, 31):
        for w in range(1, 4):
            sku, wh = f"SKU{s:03d}", f"WH{w}"
            base = 6 + s * 1.2 + w * 2
            values = []
            for t in range(180):
                dt = ASOF - timedelta(days=179-t)
                season = 1.3 if dt.weekday() < 5 else 0.65
                promotion = 1.6 if s <= 4 and t >= 155 else 1.0
                units = max(0, round(base * season * promotion + rng.gauss(0, base*0.13)))
                if s == 30:  # deliberately intermittent demand, not a well-fitted smooth series
                    units = units if rng.random() < 0.12 else 0
                values.append(units)
                demand.append(dict(zip(SCHEMAS["demand"], [dt.isoformat(),sku,wh,units,"synthetic"])))
            avg = sum(values[-28:]) / 28
            coverage = 2 if s % 7 == 1 else (65 if s % 7 == 0 else rng.randint(12,25))
            inventory.append(dict(zip(SCHEMAS["inventory"], [ASOF.isoformat(),sku,wh,round(avg*coverage),rng.randint(0,4),7+s%8,3,40+s*7,"synthetic"])))
            for j in range(6):
                promised = ASOF - timedelta(days=25-j*4) if j < 5 else ASOF + timedelta(days=5+s%10)
                lag = 4 if s%5 == 0 else rng.choice([-1,0,0,1,2])
                received = promised + timedelta(days=lag) if j < 4 else None
                expected = received if received else promised + timedelta(days=lag)
                orders.append(dict(zip(SCHEMAS["orders"], [f"PO-{s:03d}-{w}-{j}",sku,wh,f"SUP{s%5+1}",(promised-timedelta(days=14)).isoformat(),promised.isoformat(),expected.isoformat(),received.isoformat() if received else "",max(1,round(avg*8)),"synthetic"])))
    for name, rows in [("demand",demand),("inventory",inventory),("orders",orders)]:
        write_csv(Path(folder)/f"{name}.csv", rows, SCHEMAS[name])
    dump(Path(folder)/"provenance.json", {"origin":"synthetic", "seed":seed,"as_of":ASOF.isoformat(),"generator":"scai.data.generate", "purpose":"learning and portfolio; no company data", "limitations":"Demand is unconstrained simulated demand, not observed sales; inventory snapshots and purchase orders are simulated independently, not a historical stock-flow ledger."})


def number(value, integer=False, minimum=0):
    n = float(value)
    if not math.isfinite(n) or n < minimum or (integer and n != int(n)):
        raise ValueError(f"invalid numeric value {value!r}")
    return int(n) if integer else n


def load(folder):
    snapshot = read_snapshot(folder)
    result = load_snapshot(snapshot)
    snapshot.assert_unchanged()
    return result


def load_snapshot(snapshot):
    tables = {}
    for name, fields in SCHEMAS.items():
        with io.StringIO(snapshot.raw[name].decode('utf-8-sig'), newline='') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != fields:
                raise ValueError(f"{name}.csv: expected columns {fields}")
            rows, seen = [], set()
            for line, r in enumerate(reader,2):
                try:
                    if None in r or any(v is None for v in r.values()):
                        raise ValueError("malformed CSV row")
                    if r["data_origin"] != "synthetic":
                        raise ValueError("MVP contract accepts only synthetic operations; real data needs separate provenance adapter")
                    if not r["sku"] or not r["warehouse"]:
                        raise ValueError("empty entity key")
                    for k in fields:
                        if k in ("date","as_of","order_date","promised_date","expected_date","received_date"):
                            if k == "received_date" and not r[k]:
                                r[k] = None
                            else:
                                r[k] = date.fromisoformat(r[k])
                        if k in ("demand_units","on_hand","backlog","lead_days","safety_days","qty"):
                            r[k] = number(r[k],True,1 if k in ("lead_days","qty") else 0)
                        if k == "unit_cost_cny":
                            r[k] = number(r[k])
                    key = (r["date"],r["sku"],r["warehouse"]) if name=="demand" else ((r["sku"],r["warehouse"]) if name=="inventory" else r["order_id"])
                    if not key or key in seen: raise ValueError("duplicate/empty primary key")
                    seen.add(key)
                    r["source_row"] = line
                    rows.append(r)
                except (ValueError,TypeError) as e:
                    raise ValueError(f"{name}.csv row {line}: {e}") from e
            if not rows: raise ValueError(f"{name}.csv: no rows")
            tables[name] = rows
    inv = {(r["sku"],r["warehouse"]):r for r in tables["inventory"]}
    dates = {r["as_of"] for r in tables["inventory"]}
    if len(dates)!=1: raise ValueError("inventory: inconsistent snapshot dates")
    asof = next(iter(dates))
    series = {}
    for r in tables["demand"]:
        key=(r["sku"],r["warehouse"])
        if key not in inv or r["date"]>asof: raise ValueError(f"demand.csv row {r['source_row']}: unknown entity/future date")
        series.setdefault(key,[]).append(r)
    if set(series)!=set(inv): raise ValueError("inventory/demand entity mismatch")
    for key, rows in series.items():
        rows.sort(key=lambda r:r["date"])
        if len(rows)!=180 or rows[-1]["date"]!=asof or any((b["date"]-a["date"]).days!=1 for a,b in zip(rows,rows[1:])):
            raise ValueError(f"{key}: exactly 180 consecutive daily observations ending at snapshot required; missing dates are not zero demand")
    for r in tables["orders"]:
        if (r["sku"],r["warehouse"]) not in inv: raise ValueError(f"orders.csv row {r['source_row']}: unknown entity")
        if not r["supplier"] or r["order_date"]>asof or any(r[k]<r["order_date"] for k in ("promised_date","expected_date")) or (r["received_date"] is not None and not r["order_date"]<=r["received_date"]<=asof):
            raise ValueError(f"orders.csv row {r['source_row']}: invalid dates/supplier")
    return tables,series,asof
