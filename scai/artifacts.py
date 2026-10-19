"""Run integrity and isolated review output; no supply-chain calculations."""
import hashlib
import math
from pathlib import Path

from .ai import make_packet, read_json
from .data import read_snapshot, load_snapshot
from .output import check_new_output, publish_bundle

RUN_OUTPUTS = ('results.json', 'forecast_backtest.csv', 'inventory_risks.csv',
               'exceptions.csv', 'ai_packet.json', 'dashboard.html')


def normalize_parameters(demand_factor=1.0, delay_days=0):
    if type(demand_factor) not in (int, float) or not math.isfinite(demand_factor) or not 0 < demand_factor <= 5:
        raise ValueError('scenario demand_factor out of allowed range')
    if type(delay_days) is not int or not 0 <= delay_days <= 60:
        raise ValueError('scenario delay_days must be an integer in 0..60')
    factor = int(demand_factor) if float(demand_factor).is_integer() else demand_factor
    return factor, delay_days


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_run(folder, data):
    """Require actual input CSVs. Legacy manifests with all required fields work.

    This detects mismatched artifacts, not coordinated forgery or identity.
    Missing/incomplete legacy manifests must be regenerated in a new directory.
    """
    folder = Path(folder)
    for name in ('run_manifest.json', *RUN_OUTPUTS):
        if not (folder / name).is_file():
            raise ValueError(f'run compatibility: missing {name}; regenerate in a new directory')
    manifest = read_json(folder / 'run_manifest.json')
    if not isinstance(manifest, dict) or type(manifest.get('schema_version', 1)) is not int or manifest.get('schema_version', 1) != 1:
        raise ValueError('unsupported run manifest version')
    hashes = manifest.get('output_sha256')
    if not isinstance(hashes, dict) or not all(name in hashes for name in RUN_OUTPUTS):
        raise ValueError('run compatibility: missing required output hashes; regenerate in a new directory')
    for name in RUN_OUTPUTS:
        if file_sha256(folder / name) != hashes[name]:
            raise ValueError(f'run hash mismatch: {name}')
    result = read_json(folder / 'results.json')
    packet = read_json(folder / 'ai_packet.json')
    if not isinstance(result, dict) or not isinstance(packet, dict):
        raise ValueError('results and packet must be objects')
    summary = result.get('summary')
    parameters = manifest.get('parameters')
    if not isinstance(summary, dict) or not isinstance(parameters, dict) or set(parameters) != {'demand_factor', 'delay_days'}:
        raise ValueError('run compatibility: missing scenario parameters')
    expected = normalize_parameters(parameters['demand_factor'], parameters['delay_days'])
    actual = normalize_parameters(summary.get('demand_factor'), summary.get('delay_days'))
    if actual != expected: raise ValueError('run scenario parameters mismatch')
    # Read and validate the real CSVs; never claim input verification from copied strings.
    snapshot = read_snapshot(data)
    load_snapshot(snapshot)
    snapshot.assert_unchanged()
    if any(obj.get('input_sha256') != snapshot.sha256 for obj in (result, packet, manifest)):
        raise ValueError('run input fingerprint mismatch')
    if make_packet(result, snapshot.sha256) != packet:
        raise ValueError('results/packet content mismatch')
    return result, packet
