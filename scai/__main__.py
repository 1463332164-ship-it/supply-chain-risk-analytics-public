import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from .data import generate,read_snapshot,load_snapshot,dump,write_csv
from .analysis import analyze
from .ai import make_packet,prompt,validate_response,read_json,review,review_template,bind_pending_review,read_json_snapshot
from .artifacts import normalize_parameters,verify_run,check_new_output,publish_bundle,file_sha256,RUN_OUTPUTS
from .dashboard import render


def run(data,out,demand_factor=1.0,delay_days=0):
    demand_factor,delay_days=normalize_parameters(demand_factor,delay_days)
    check_new_output(out,[data])
    snapshot=read_snapshot(data)
    tables,series,asof=load_snapshot(snapshot)
    result,detail=analyze(tables,series,asof,demand_factor,delay_days)
    h=snapshot.sha256
    result['input_sha256']=h
    packet=make_packet(result,h)
    snapshot.assert_unchanged()
    def build(folder):
        dump(folder/'results.json',result)
        write_csv(folder/'forecast_backtest.csv',detail)
        write_csv(folder/'inventory_risks.csv',[{k:v for k,v in x.items() if k!='time_path'} for x in result['inventory']])
        write_csv(folder/'exceptions.csv',[{**x,'metrics':json.dumps(x['metrics'],ensure_ascii=False)} for x in result['evidence']],['id','type','priority','sku','warehouse','source','metrics','meaning'])
        dump(folder/'ai_packet.json',packet)
        (folder/'ai_prompt.txt').write_text(prompt(packet),encoding='utf-8',newline='\n')
        render(result,folder/'dashboard.html')
        dump(folder/'run_manifest.json',{'schema_version':1,'python':platform.python_version(),'input_sha256':h,'parameters':{'demand_factor':demand_factor,'delay_days':delay_days},'data_validation':'passed','ai_execution':'not_called_by_run','output_sha256':{name:file_sha256(folder/name) for name in RUN_OUTPUTS}})
    publish_bundle(out,[data],build,before_publish=snapshot.assert_unchanged)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description='Synthetic supply-chain analysis with evidence-grounded AI review')
    sub=p.add_subparsers(dest='cmd',required=True)
    g=sub.add_parser('generate');g.add_argument('--out',required=True,help='NEW data directory; existing paths are refused');g.add_argument('--seed',type=int,default=20261018)
    a=sub.add_parser('analyze');a.add_argument('--data',default='data/demo');a.add_argument('--out',required=True,help='NEW run directory separate from input; existing paths are refused');a.add_argument('--demand-factor',type=float,default=1);a.add_argument('--delay-days',type=int,default=0)
    v=sub.add_parser('validate-ai');v.add_argument('--run',default='runs/base');v.add_argument('--response',required=True)
    rr=sub.add_parser('review');rr.add_argument('--run',default='runs/base');rr.add_argument('--response',required=True);rr.add_argument('--decisions',required=True)
    for command in (v,rr):
        command.add_argument('--data',required=True,help='Original input CSV directory; fingerprint is recomputed')
        command.add_argument('--out',required=True,help='Separate NEW output directory; existing paths are refused')
    v.add_argument('--pending-decisions',help='Explicitly migrate legacy pending-only decisions to a NEW v2 template; source preserved')
    args=p.parse_args(argv)
    try:
        if args.cmd=='generate': generate(args.out,args.seed);print('Generated synthetic data:',args.out)
        elif args.cmd=='analyze': print(json.dumps(run(args.data,args.out,args.demand_factor,args.delay_days)['summary'],ensure_ascii=True,indent=2))
        elif args.cmd=='validate-ai':
            sources=[args.run,args.data,args.response]
            if args.pending_decisions: sources.append(args.pending_decisions)
            check_new_output(args.out,sources)
            result,packet=verify_run(args.run,args.data)
            response=read_json(args.response)
            status=validate_response(packet,response)
            template=review_template(packet,response)
            legacy_bytes=None
            if args.pending_decisions:
                legacy,legacy_bytes=read_json_snapshot(args.pending_decisions)
                template=bind_pending_review(packet,response,legacy)
            status.update(input_verification='actual_csv_fingerprint_verified',input_sha256=result['input_sha256'],
                          response_sha256=template['response_sha256'],run_manifest_sha256=file_sha256(Path(args.run)/'run_manifest.json'))
            def build(folder):
                dump(folder/'ai_validation.json',status)
                dump(folder/'ai_draft.json',response)
                dump(folder/'review_template.json',template)
                render(result,folder/'dashboard_ai.html',response)
                if legacy_bytes is not None:
                    (folder/'legacy_decisions_snapshot.json').write_bytes(legacy_bytes)
                    dump(folder/'migration.json',{'mode':'explicit_pending_only','source_sha256':hashlib.sha256(legacy_bytes).hexdigest(),
                                                'source_binding_status':'legacy_unbound','target_schema_version':2})
            publish_bundle(args.out,sources,build)
            print(json.dumps(status,ensure_ascii=True))
        else:
            sources=[args.run,args.data,args.response,args.decisions]
            check_new_output(args.out,sources)
            _,packet=verify_run(args.run,args.data)
            response=read_json(args.response);decisions=read_json(args.decisions)
            result=review(packet,response,decisions)
            provenance={'input_sha256':packet['input_sha256'],'results_sha256':file_sha256(Path(args.run)/'results.json'),
                        'run_manifest_sha256':file_sha256(Path(args.run)/'run_manifest.json')}
            def build(folder):
                dump(folder/'human_review.json',result)
                dump(folder/'response_snapshot.json',response)
                dump(folder/'decisions_snapshot.json',decisions)
                dump(folder/'ai_packet.json',packet)
                dump(folder/'run_reference.json',provenance)
            publish_bundle(args.out,sources,build)
            print(json.dumps({'approved_count':result['approved_count'],'review_saved':True}))
    except (OSError,ValueError,TypeError,KeyError) as e:
        print(f'ERROR: {e}',file=sys.stderr)
        return 2
    return 0


if __name__=='__main__': raise SystemExit(main())
