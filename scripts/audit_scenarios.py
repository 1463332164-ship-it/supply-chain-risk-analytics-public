"""Run four real CLI scenarios into a new runs/ directory; never overwrite a run."""
import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                          encoding='utf-8', newline='\n')


def summarize(result):
    rows, s = result['inventory'], result['summary']
    overdue = [e for e in result['evidence'] if e['type'] == 'overdue_purchase_order']
    return {'entities': len(rows), 'shortage_entities': s['shortage_entities'],
            'sum_entity_peak_net_shortage_units': round(sum(x['peak_net_shortage_units'] for x in rows), 4),
            'reorder_entities': sum(x['reorder_suggestion_units'] > 0 for x in rows),
            'reorder_suggestion_units': s['reorder_suggestion_units'],
            'reorder_cost_cny': s['reorder_cost_cny'],
            'overdue_open_orders': len(overdue),
            'overdue_open_units': sum(e['metrics']['open_units'] for e in overdue),
            'due_orders': s['due_orders'], 'on_time_orders': s['on_time_orders'], 'otd': s['otd'],
            'excess_coverage_entities': sum(e['type'] == 'excess_coverage' for e in result['evidence']),
            'min_horizon_days': min(x['horizon_days'] for x in rows),
            'max_horizon_days': max(x['horizon_days'] for x in rows)}


def metric_delta(value, baseline):
    if value is None or baseline is None:
        return {'absolute': None, 'percent': None}
    return {'absolute': round(value - baseline, 6),
            'percent': round((value / baseline - 1) * 100, 6) if baseline else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='New directory strictly inside workspace runs/; existing paths are refused')
    parser.add_argument('--data', default='data/demo')
    parser.add_argument('--response', help='Optional AI response for THIS baseline; analysis runs without AI when omitted')
    args = parser.parse_args(argv)
    out = (ROOT / args.out).resolve()
    runs = (ROOT / 'runs').resolve()
    data = (ROOT / args.data).resolve()
    if out == runs or not out.is_relative_to(runs) or out.exists():
        parser.error('--out must be a new child directory inside workspace runs/')
    if out == data or out.is_relative_to(data) or data.is_relative_to(out):
        parser.error('input and output directories must not overlap')
    if args.response:
        response = (ROOT / args.response).resolve()
        if response == out or response.is_relative_to(out):
            parser.error('AI response and output directories must not overlap')
    out.mkdir(parents=True)
    try:
        return execute(args, out, data)
    except (OSError, ValueError, RuntimeError, AssertionError, KeyError, TypeError) as exc:
        save(out / 'failure.json', {'status': 'failed', 'error': str(exc),
                                   'note': 'Incomplete experiment; retain diagnostic files and retry in a NEW directory.'})
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


def execute(args, out, data):
    commands = []

    def command(arguments):
        p = subprocess.run([sys.executable, '-m', 'scai', *arguments], cwd=ROOT,
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        commands.append({'argv': ['python', '-m', 'scai', *arguments], 'returncode': p.returncode,
                         'stdout': p.stdout, 'stderr': p.stderr})
        save(out / 'commands.json', commands)
        if p.returncode:
            raise RuntimeError(f'CLI failed; see {out / "commands.json"}')

    input_before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in data.glob('*') if p.is_file()}
    results, summaries = {}, {}
    for name, factor, delay in [('base', 1, 0), ('demand_125', 1.25, 0), ('delay_7', 1, 7), ('combined', 1.25, 7)]:
        extra = ['--demand-factor', str(factor), '--delay-days', str(delay)]
        command(['analyze', '--data', args.data, '--out', (out / name).relative_to(ROOT).as_posix(), *extra])
        result = read(out / name / 'results.json')
        manifest = read(out / name / 'run_manifest.json')
        for file, digest in manifest['output_sha256'].items():
            if hashlib.sha256((out / name / file).read_bytes()).hexdigest() != digest:
                raise AssertionError(f'{name}/{file} manifest mismatch')
        results[name], summaries[name] = result, summarize(result)
    command(['analyze', '--data', args.data, '--out', (out / 'base_repeat').relative_to(ROOT).as_posix()])
    identical = (out / 'base/results.json').read_bytes() == (out / 'base_repeat/results.json').read_bytes()
    if not identical:
        raise AssertionError('Repeated baseline changed')
    delta = {name: {key: metric_delta(value, summaries['base'][key])
                    for key, value in values.items()} for name, values in summaries.items()}
    ai_status = {'status': 'not_requested'}
    if args.response:
        try:
            command(['validate-ai', '--run', (out / 'base').relative_to(ROOT).as_posix(),
                     '--data', args.data, '--response', args.response,
                     '--out', (out / 'base_ai').relative_to(ROOT).as_posix()])
            ai_status = {'status': 'passed', 'output': 'base_ai'}
        except RuntimeError:
            ai_status = {'status': 'failed', 'note': 'Analysis complete; optional AI validation failed. See commands.json.'}
    input_after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in data.glob('*') if p.is_file()}
    if input_before != input_after:
        raise AssertionError('Input files changed during experiment')
    selected = {}
    for name, result in results.items():
        selected[name] = []
        for row in result['inventory']:
            if row['sku'] == 'SKU001' and row['warehouse'] in ('WH1', 'WH2'):
                item = dict(row)
                first = item['first_shortage_day']
                item['first_shortage_date'] = (date.fromisoformat(result['summary']['as_of']) + timedelta(days=first)).isoformat() if first is not None else None
                selected[name].append(item)
    summary = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'python': sys.version,
               'input_sha256': input_before, 'input_unchanged': True, 'repeat_results_identical': identical,
               'analysis_status': 'passed', 'ai_validation': ai_status,
               'scenarios': summaries, 'delta_from_base': delta, 'selected_entities': selected,
               'metric_note': 'Sum of per-entity peak net shortages is not lost sales, cumulative shortage or a simultaneous network shortage. Horizons differ when delay_days changes.',
               'historical_metrics_unchanged': all(r['metrics'] == results['base']['metrics'] and r['suppliers'] == results['base']['suppliers'] for r in results.values())}
    save(out / 'experiment_summary.json', summary)
    with (out / 'scenario_metrics.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['scenario', *summaries['base']])
        writer.writeheader()
        writer.writerows({'scenario': name, **values} for name, values in summaries.items())
    print(json.dumps({'output': out.relative_to(ROOT).as_posix(), 'scenarios': summaries,
                      'repeat_results_identical': identical, 'ai_validation': ai_status}, ensure_ascii=True, indent=2))
    return 2 if ai_status['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
