"""Run real tests and archive execution evidence. No external dependencies."""
import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scai.data import dump


def command(args):
    p=subprocess.run([sys.executable,*args],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONIOENCODING':'utf-8'})
    return {'command':['python',*args],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Archive verification in a NEW runs/ directory; never overwrite historical examples.')
    parser.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    out=(ROOT/args.out).resolve()
    if out.exists() or out == ROOT/'runs' or not out.is_relative_to(ROOT/'runs'):
        parser.error('--out must be a new child directory inside workspace runs/')
    out.mkdir(parents=True)
    checks=[]
    checks.append(command(['-m','unittest','discover','-s','tests','-v']))
    if checks[-1]['returncode']:
        dump(out/'verification.json',{'all_commands_passed':False,'commands':checks})
        return 1
    for label,extra in [('base',[]),('repeat',[]),('stress',['--demand-factor','1.25','--delay-days','7']),('demand_only',['--demand-factor','1.25']),('delay_only',['--delay-days','7'])]:
        checks.append(command(['-m','scai','analyze','--out',str(out/label),*extra]))
        if checks[-1]['returncode']: break
    if all(c['returncode']==0 for c in checks):
        checks.append(command(['-m','scai','validate-ai','--run',str(out/'base'),'--data','data/demo','--out',str(out/'base_ai'),'--response','examples/ai_response_codex.json']))
    if all(c['returncode']==0 for c in checks):
        checks.append(command(['-m','scai','review','--run',str(out/'base'),'--data','data/demo','--out',str(out/'pending_review'),'--response','examples/ai_response_codex.json','--decisions',str(out/'base_ai/review_template.json')]))
    reproducible=False
    if all(c['returncode']==0 for c in checks):
        reproducible=(out/'base/results.json').read_bytes()==(out/'repeat/results.json').read_bytes()
    summary={label:json.loads((out/label/'results.json').read_text(encoding='utf-8'))['summary'] for label in ('base','stress','demand_only','delay_only') if (out/label/'results.json').exists()}
    report={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),'platform':platform.platform(),'all_commands_passed':all(c['returncode']==0 for c in checks),'repeat_results_identical':reproducible,'scenarios':summary,'commands':checks,'human_review':'pending; only pending template was processed','github_actions':'configuration only; not remotely executed','browser_visual':'not_assessed_by_this_script'}
    dump(out/'verification.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('commands','scenarios')},ensure_ascii=True,indent=2))
    return 0 if report['all_commands_passed'] and reproducible else 1


if __name__=='__main__':raise SystemExit(main())
