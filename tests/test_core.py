import copy
import csv
import json
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
from scai.data import generate,load,fingerprint,write_csv,SCHEMAS,number
from scai.analysis import forecast,score,delivery,inventory_risk,evaluate
from scai.ai import make_packet,validate_response,review,review_template
from scai.__main__ import run,main


class MathTests(unittest.TestCase):
    def test_hand_calculation(self):
        m=score([10,20],[12,17])
        self.assertEqual(m['mae'],2.5)
        self.assertAlmostEqual(m['wape'],5/30)
        self.assertAlmostEqual(m['bias'],-1/30)

    def test_zero_demand_is_undefined(self):
        self.assertIsNone(score([0,0],[1,2])['wape'])

    def test_no_future_leakage(self):
        y=list(range(180));altered=y[:124]+[99999]*56
        for model in ('naive','seasonal7','ma28'):
            self.assertEqual(forecast(y[:124],7,model),forecast(altered[:124],7,model))

    def test_seasonal_repeats_last_week(self):
        self.assertEqual(forecast([1,2,3,4,5,6,7],9,'seasonal7'),[1.,2.,3.,4.,5.,6.,7.,1.,2.])

    def test_late_arrival_cannot_hide_early_shortage(self):
        a=date(2026,10,17)
        inv={'sku':'S','warehouse':'W','source_row':2,'lead_days':7,'on_hand':10,'backlog':0,'safety_days':3,'unit_cost_cny':1}
        orders=[{'received_date':None,'expected_date':a+timedelta(days=5),'qty':1000}]
        r=inventory_risk(inv,orders,[10]*28,a,'naive')
        self.assertEqual(r['first_shortage_day'],2)
        self.assertEqual(r['peak_net_shortage_units'],30)
        self.assertEqual(r['reorder_suggestion_units'],0)  # sufficient later, still short earlier

    def test_stale_eta_not_available(self):
        a=date(2026,10,17)
        inv={'sku':'S','warehouse':'W','source_row':2,'lead_days':7,'on_hand':0,'backlog':0,'safety_days':0,'unit_cost_cny':1}
        r=inventory_risk(inv,[{'received_date':None,'expected_date':a,'qty':99999}],[10]*28,a,'naive')
        self.assertEqual(r['reorder_suggestion_units'],140)

    def test_due_cohort_includes_unreceived(self):
        a=date(2026,10,17)
        rows=[{'promised_date':a,'received_date':a},{'promised_date':a,'received_date':None},{'promised_date':a+timedelta(days=1),'received_date':None}]
        self.assertEqual(delivery(rows,a),{'due_orders':2,'on_time_orders':1,'otd':0.5})

    def test_non_finite_numbers(self):
        for v in ('NaN','inf','-1'):
            with self.assertRaises(ValueError): number(v)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sandbox_root=Path(__file__).resolve().parents[1]/'runs'
        sandbox_root.mkdir(exist_ok=True)
        cls.tmp=tempfile.TemporaryDirectory(dir=sandbox_root);cls.root=Path(cls.tmp.name);cls.data=cls.root/'data'
        generate(cls.data)
        cls.tables,cls.series,cls.asof=load(cls.data)
        cls.result=run(cls.data,cls.root/'base')
        cls.packet=make_packet(cls.result,fingerprint(cls.data))

    @classmethod
    def tearDownClass(cls):
        assert cls.root.resolve().is_relative_to((Path(__file__).resolve().parents[1]/'runs').resolve())
        cls.tmp.cleanup()

    def response(self):
        e=self.packet['evidence'][0]
        return {'packet_sha256':self.packet['packet_sha256'],'limitations':'模拟；待人工审核','items':[{'evidence_id':e['id'],'observed':dict(e['metrics']),'hypothesis':'待核实：需求与到货节奏存在错配','action':'核查到货承诺与可调拨库存','owner_role':'计划'}]}

    def test_expected_scope(self):
        self.assertEqual(len(self.tables['demand']),16200)
        self.assertEqual(len(self.tables['orders']),540)
        self.assertEqual(len(self.series),90)

    def test_seed_reproducibility(self):
        generate(self.root/'again')
        self.assertEqual(fingerprint(self.data),fingerprint(self.root/'again'))

    def test_result_reproducibility(self):
        run(self.data,self.root/'repeat')
        self.assertEqual((self.root/'base/results.json').read_bytes(),(self.root/'repeat/results.json').read_bytes())

    def test_scenario_changes_risk(self):
        stress=run(self.data,self.root/'stress',1.25,7)
        self.assertGreater(stress['summary']['shortage_entities'],self.result['summary']['shortage_entities'])
        self.assertEqual(stress['summary']['otd'],self.result['summary']['otd']) # historical OTD must not change

    def test_test_period_cannot_select_model(self):
        changed=copy.deepcopy(self.series)
        for rows in changed.values():
            for row in rows[152:]:row['demand_units']=99999
        winner,metrics,_=evaluate(changed)
        self.assertEqual(winner,self.result['summary']['selected_model'])
        self.assertEqual(metrics['validation'],self.result['metrics']['validation'])

    def test_duplicate_and_missing_day_rejected(self):
        for mode in ('duplicate','missing'):
            folder=self.root/mode;generate(folder)
            path=folder/'demand.csv'
            with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
            rows=rows+[rows[0]] if mode=='duplicate' else rows[1:]
            write_csv(path,rows,SCHEMAS['demand'])
            with self.assertRaises(ValueError):load(folder)

    def test_invalid_foreign_key_rejected(self):
        folder=self.root/'foreign';generate(folder)
        path=folder/'orders.csv'
        with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        rows[0]['sku']='UNKNOWN';write_csv(path,rows,SCHEMAS['orders'])
        with self.assertRaises(ValueError):load(folder)

    def test_ai_valid_reference(self):
        self.assertEqual(validate_response(self.packet,self.response())['checked_items'],1)

    def test_ai_unknown_reference_rejected(self):
        r=self.response();r['items'][0]['evidence_id']='fake'
        with self.assertRaises(ValueError):validate_response(self.packet,r)

    def test_ai_fabricated_number_rejected(self):
        r=self.response();r['items'][0]['observed']['first_shortage_day']=999
        with self.assertRaises(ValueError):validate_response(self.packet,r)

    def test_ai_changed_packet_rejected(self):
        r=self.response();r['packet_sha256']='different'
        with self.assertRaises(ValueError):validate_response(self.packet,r)

    def test_tampered_packet_rejected(self):
        p=copy.deepcopy(self.packet);p['evidence'][0]['metrics']['first_shortage_day']=999
        with self.assertRaises(ValueError):validate_response(p,self.response())

    def test_ai_text_number_rejected(self):
        r=self.response();r['items'][0]['action']='降低成本20%'
        with self.assertRaises(ValueError):validate_response(self.packet,r)

    def test_review_requires_identity_and_reason(self):
        r=self.response();d=review_template(self.packet,r);d['decisions'][0]['decision']='approve'
        with self.assertRaises(ValueError):review(self.packet,r,d)
        d['decisions'][0].update(reviewer='TEST_FIXTURE_NOT_HUMAN',reason='test only')
        self.assertEqual(review(self.packet,r,d)['approved_count'],1)

    def test_invalid_scenario_exit_code(self):
        self.assertEqual(main(['analyze','--data',str(self.data),'--out',str(self.root/'bad'),'--demand-factor','-1']),2)


if __name__=='__main__':unittest.main()
