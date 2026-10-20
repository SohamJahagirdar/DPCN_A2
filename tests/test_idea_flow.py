"""Offline synthetic and mocked-provider tests; no keys, HTTP or legacy build."""
import csv
import gzip
import json
from pathlib import Path
import random
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from pipeline.idea_flow import (FIELDS, VERSION, Study, chronology, doi, outside,
                               reverse_reach, select_pilot, verify_study, work_id, write_csv, write_json)
from pipeline.idea_flow_fetch import (Client, ProviderError, StopAcquisition, acquire,
                                     decode_response, free_allowance, process_page)
from pipeline.idea_flow_metrics import (age_window, analyze, composition, deeper_reach, expected_richness,
                                       full_gate, records, sample_g2, summarize, validate_pilot)


def raw(wid, refs=(), field="17", year=2020, **extra):
    return dict(id="https://openalex.org/" + wid, doi="https://doi.org/10.1/" + wid,
                title="Paper " + wid, publication_year=year, publication_date=None,
                type="article", referenced_works=["https://openalex.org/" + w for w in refs],
                primary_topic={"field": {"id": "https://openalex.org/fields/" + field, "display_name": "Field " + field}} if field else None,
                **extra)


def seed(wid, inst="IISc", year=2016, field=FIELDS[0], n=15, **extra):
    return dict(work_id=wid, homes=[inst], title="Seed " + wid, year=year,
                stored_citations=n, citation_band="0-9" if n < 10 else "10-99" if n < 100 else "100+",
                sampling_field=field, stored_type="article", doi="10.1/"+wid, identity_conflict=False,
                selection_rank=wid, **extra)


def page(results, count=None, cursor=None):
    return dict(results=results, meta=dict(count=len(results) if count is None else count, next_cursor=cursor))


def budget(used=0, remaining=1):
    return dict(rate_limit=dict(daily_budget_usd=1, daily_used_usd=used, daily_remaining_usd=remaining,
                               endpoint_costs_usd=dict(list=0.0001,singleton=0),resets_at="2026-10-20T00:00:00Z"))


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        p = self.root/"study"
        write_json(p/"study_manifest.json", dict(version=VERSION, repository=str(self.root/"repo"),cutoff="2026-10-15",seed_count=2))
        self.s = Study(p)
        write_json(p/"manifests/pilot_selection.json",dict(seeds=[],cells=[]))

    def tearDown(self):
        self.s.close(); self.tmp.cleanup()

    def add_seed(self, wid="W1", **kw):
        data = seed(wid, **kw)
        self.s.db.execute("INSERT INTO seeds(original_id,canonical_id,data,pilot,identity_status) VALUES(?,?,?,?,?)", (wid,wid,json.dumps(data),1,"resolved"))
        self.s.put_work(raw(wid,year=data["year"]),"seed-snapshot")
        self.s.db.commit()

    def front(self, targets=("W1",), stage="pilot"):
        return self.s.frontier(stage,"citers",targets,dict(filter="cites:"+"|".join(targets)))

    def test_id_validation_and_doi(self):
        self.assertEqual(work_id("https://openalex.org/w123"),"W123")
        for bad in [None,"W0","A12","https://evil.test/W12","W1/../W2","W12?key=x"]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):work_id(bad)
        self.assertEqual(doi("https://doi.org/10.1007/JHEP06(2018)120"),"10.1007/jhep06(2018)120")

    def test_external_directory_guard_and_preserve(self):
        for path in [self.root/"repo",self.root/"repo"/"outputs",self.root]:
            with self.assertRaises(ValueError):outside(path,self.root/"repo")
        self.assertEqual(outside(self.root/"study",self.root/"repo"),self.root/"study")

    def test_reverse_direction_diamond_cycle_and_shortest_distance(self):
        es=[("W2","W1"),("W3","W2"),("W4","W2"),("W5","W3"),("W5","W4"),("W1","W5"),("W3","W1")]
        reach=reverse_reach("W1",es,3)
        self.assertEqual(reach,{"W1":0,"W2":1,"W3":1,"W4":2,"W5":2})
        self.assertNotIn("W5",reverse_reach("W2",es,1))

    def test_multiseed_exact_edges_and_shared_citer_dedup(self):
        self.add_seed();self.add_seed("W2")
        fid=self.front(("W1","W2"))
        process_page(self.s,fid,"*",page([raw("W3",["W1","W2"]),raw("W4",["W2"])],2),"p1","now")
        self.assertEqual({tuple(r) for r in self.s.db.execute("SELECT citing,cited FROM citations")},{("W3","W1"),("W3","W2"),("W4","W2")})
        fid2=self.front(("W2",),"pilot-check")
        process_page(self.s,fid2,"*",page([raw("W3",["W2"])],1),"p2","now")
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM works").fetchone()[0],4)
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM citations").fetchone()[0],3)

    def test_cursor_terminal_and_transactional_resume(self):
        self.add_seed();fid=self.front()
        p=page([raw("W2",["W1"])],1,"next")
        process_page(self.s,fid,"*",p,"a","now")
        self.assertEqual(self.s.db.execute("SELECT status,cursor FROM frontiers").fetchone()[:],("running","next"))
        process_page(self.s,fid,"*",p,"a","now")
        process_page(self.s,fid,"next",page([],1),"b","now")
        self.assertEqual(self.s.db.execute("SELECT status,pages,returned FROM frontiers").fetchone()[:],("complete",2,1))

    def test_empty_is_distinct_from_pending_failed_partial(self):
        self.add_seed(); fid=self.front()
        self.assertEqual(records(self.s,"pilot")[0]["query_status"],"pending")
        process_page(self.s,fid,"*",page([],0),"empty","now")
        r=records(self.s,"pilot")[0]
        self.assertEqual(r["query_status"],"complete_empty"); self.assertIsNone(r["cross_field_share"])
        self.assertEqual(r["observed_citers"],0)

    def test_repeated_cursor_and_premature_empty_do_not_complete(self):
        self.add_seed();fid=self.front()
        for p in [page([raw("W2",["W1"])],1,"*"),page([],1,"x")]:
            with self.assertRaises(ValueError):process_page(self.s,fid,"*",p,"bad","now")
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM pages").fetchone()[0],0)

    def test_unmatched_references_fail_quality_gate(self):
        self.add_seed();fid=self.front()
        process_page(self.s,fid,"*",page([raw("W2",["W99"])],1),"bad","now")
        self.assertEqual(self.s.db.execute("SELECT status FROM frontiers").fetchone()[0],"inconsistent")

    def test_missing_result_count_is_not_exhaustive(self):
        self.add_seed();fid=self.front()
        process_page(self.s,fid,"*",page([raw("W2",["W1"])],2),"bad","now")
        self.assertEqual(self.s.db.execute("SELECT status FROM frontiers").fetchone()[0],"inconsistent")

    def test_doi_collision_does_not_merge_cross_boundary_nodes(self):
        self.add_seed()
        a=raw("W2");a["doi"]=raw("W1")["doi"]
        self.s.put_work(a,"other");self.s.db.commit()
        self.assertEqual(self.s.canonical("W2"),"W2")
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM works WHERE doi=?",("10.1/w1",)).fetchone()[0],2)

    def test_explicit_provider_alias_records_evidence_and_exact_edge(self):
        self.add_seed();self.s.put_work(raw("W9"),"provider-redirect",requested="W1");self.s.db.commit()
        self.assertEqual(self.s.canonical("W1"),"W9")
        self.assertEqual(self.s.db.execute("SELECT evidence FROM aliases").fetchone()[0],"provider-redirect")
        fid=self.front(("W9",))
        process_page(self.s,fid,"*",page([raw("W2",["W1"])],1),"p","now")
        self.assertEqual(tuple(self.s.db.execute("SELECT citing,cited FROM citations").fetchone()),("W2","W9"))

    def test_chronology_missing_same_year_and_inversion(self):
        self.assertEqual(chronology({"year":None},{"year":2020}),"unknown_year")
        self.assertEqual(chronology({"year":2020},{"year":2020}),"same_year_indeterminate")
        self.assertEqual(chronology({"year":2019},{"year":2020}),"year_inversion")

    def test_unknown_fields_and_exact_denominators(self):
        cs=[dict(id="W1",field_id="a"),dict(id="W2",field_id="b"),dict(id="W3",field_id="b"),dict(id="W4",field_id=None)]
        c=composition("a",cs+cs)
        self.assertEqual((c["observed_citers"],c["known_field_citers"],c["unknown_field_citers"]),(4,3,1))
        self.assertEqual(c["cross_field_share"],2/3)
        self.assertEqual((c["cross_field_lower"],c["cross_field_upper"]),(.5,.75))
        self.assertIsNone(composition(None,cs)["cross_field_share"])
        self.assertIsNone(composition("a",[])["cross_field_share"])

    def test_equal_age_window_censoring_and_missing_year(self):
        self.assertEqual(age_window(2022,2025,"2026-10-15"),"eligible")
        self.assertEqual(age_window(2022,2026,"2026-10-15"),"outside_window")
        self.assertEqual(age_window(2023,2025,"2026-10-15"),"right_censored")
        self.assertEqual(age_window(2022,2021,"2026-10-15"),"year_inversion")
        self.assertEqual(age_window(2022,None,"2026-10-15"),"unknown_citer_year")

    def test_exact_rarefaction(self):
        self.assertIsNone(expected_richness({"a":9}))
        self.assertEqual(expected_richness({"a":20}),1)
        self.assertEqual(expected_richness({"a":5,"b":5}),2)

    def test_selection_all_cells_deterministic_joint_and_exclusions(self):
        seeds=[];i=1
        for inst in ["IISc","TIFR"]:
            for f in FIELDS:
                for y in [2016,2020]:
                    for n in [5,20]:
                        seeds.extend([seed("W"+str(i),inst,y,f,n),seed("W"+str(i+100),inst,y,f,n)]);i+=1
        frame,chosen,cells=select_pilot(seeds)
        self.assertEqual((len(frame),len(chosen),len(cells)),(48,24,24))
        shuffled=list(reversed(seeds))
        self.assertEqual([s["work_id"] for s in chosen],[s["work_id"] for s in select_pilot(shuffled)[1]])
        joint=seed("W999",homes_override=True);joint.pop("homes_override");joint["homes"]=["IISc","TIFR"]
        s=select_pilot(seeds+[joint])[1]
        self.assertEqual(len(s),len({r["work_id"] for r in s}))
        self.assertEqual(len(select_pilot([dict(v,identity_conflict=True) for v in seeds])[1]),0)

    def test_all_originals_retained_even_when_unacquired(self):
        self.add_seed();self.add_seed("W2")
        rs=records(self.s)
        self.assertEqual(len(rs),2)
        self.assertTrue(all(r["query_status"]=="not_started" for r in rs))
        self.assertTrue(all(r["cross_field_share"] is None for r in rs))

    def test_joint_homes_and_provider_aliases_count_once_in_summary(self):
        self.add_seed();r=records(self.s)[0];r2=dict(r,original_id="W9",homes=["TIFR"])
        summary=summarize([r,r2])
        joint=next(v for v in summary if v["dimension"]=="institution")
        self.assertEqual((joint["value"],joint["canonical_seeds"]),("IISc;TIFR",1))

    def test_budget_free_only_and_unknown_format(self):
        self.assertEqual(free_allowance(budget(.2,.8))["free_remaining_credits"],8000)
        d=budget(1.2,50);d["rate_limit"]["daily_budget_usd"]=100
        self.assertEqual(free_allowance(d)["free_remaining_credits"],0)
        with self.assertRaises(StopAcquisition):free_allowance({})
        for malformed in (budget(float('nan'),1),budget(0,float('inf'))):
            with self.assertRaises(StopAcquisition):free_allowance(malformed)
        d=budget();d["rate_limit"]["endpoint_costs_usd"]["list"]=.001
        with self.assertRaises(StopAcquisition):free_allowance(d)

    def mock_client(self, transport, **kw):
        return Client(self.s,transport=transport,sleep=lambda n:None,clock=lambda:0,**kw)

    def test_snapshot_cache_no_duplicate_request_and_no_credentials(self):
        calls=[]
        def transport(path,params):
            calls.append(path);return 200,budget() if path=="/rate-limit" else page([raw("W1")]),{}
        c=self.mock_client(transport);c.establish_budget()
        first=c.request("/works",{"filter":"openalex_id:W1"})
        second=c.request("/works",{"filter":"openalex_id:W1"})
        self.assertEqual(first,second);self.assertEqual(calls,["/rate-limit","/works"])
        with self.assertRaises(ValueError):c.request("/works",{"api_key":"never"})
        self.assertEqual(len(list((self.s.path/"snapshots").glob("*.gz"))),1)

    def test_retry_and_budget_stop_preserve_frontier(self):
        self.add_seed();responses=[500,200]
        meta=self.s.frontier('pilot-metadata','metadata',['W1'],{})
        self.s.db.execute("UPDATE frontiers SET status='complete' WHERE id=?",(meta,));self.s.db.commit()
        def t(path,params):
            if path=="/rate-limit":return 200,budget(),{}
            code=responses.pop(0);return code,page([raw("W2",["W1"])]),{}
        c=self.mock_client(t);c.establish_budget()
        result=acquire(self.s,c,"pilot")
        self.assertIsNone(result["stopped_reason"])
        self.assertEqual(c.calls,2)
        # A different frontier pauses BEFORE any work request at an exhausted budget.
        fid2=self.front(("W1",),"pilot-check")
        c2=self.mock_client(lambda path,params:(200,budget(1,0),{}));c2.establish_budget()
        with self.assertRaises(StopAcquisition):c2.request("/works",{"cursor":"new"})
        self.assertEqual(c2.calls,0)
        self.assertEqual(self.s.db.execute("SELECT status FROM frontiers WHERE id=?",(fid2,)).fetchone()[0],"pending")

    def test_rate_limit_retry_and_auth_stop(self):
        sequence=[429,200]
        def t(path,params):
            if path=="/rate-limit":return 200,budget(),{}
            return sequence.pop(0),page([]),{}
        c=self.mock_client(t);c.establish_budget();c.request("/works",{"cursor":"*"});self.assertEqual(c.calls,2)
        c=self.mock_client(lambda path,params:(200,budget(),{}) if path=="/rate-limit" else (401,{},{}));c.establish_budget()
        with self.assertRaises(StopAcquisition):c.request("/works",{})

    def test_full_and_g2_gates_reject_unvalidated_pilot(self):
        c=self.mock_client(lambda path,params:(200,budget(),{}));c.establish_budget()
        with self.assertRaises(StopAcquisition):acquire(self.s,c,"full")
        self.assertFalse(sample_g2(self.s)["eligible_to_acquire"])
        self.assertFalse(validate_pilot(self.s)["passed"])

    def test_full_precision_export_headers_and_empty_schema(self):
        p=self.root/"export.csv"
        write_csv(p,["id","fraction"],[dict(id="W1",fraction=2/3)])
        with p.open(encoding="utf-8-sig",newline="") as f:
            d=csv.DictReader(f);r=next(d);self.assertEqual(d.fieldnames,["id","fraction"]);self.assertEqual(float(r["fraction"]),2/3)
        write_csv(p,["id","fraction"],[])
        self.assertIn("id,fraction",p.read_text(encoding="utf-8-sig"))

    def test_parallel_credit_reservations_never_oversubscribe(self):
        c=self.mock_client(lambda path,params:(200,budget(.9975,.0025),{}) if path=='/rate-limit' else (200,page([]),{}))
        c.establish_budget()
        def call(i):
            try:c.request('/works',{'cursor':str(i)});return True
            except StopAcquisition:return False
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(call,range(30)))
        self.assertEqual(sum(results),5)
        self.assertEqual(c.calls,5)
        self.assertEqual(self.s.db.execute('SELECT sum(credits_reserved) FROM requests').fetchone()[0],5)

    def test_rejected_page_rolls_back_every_normalized_row(self):
        self.add_seed();fid=self.front()
        bad=raw('W3');bad['referenced_works']=['not-a-work']
        with self.assertRaises(ValueError):process_page(self.s,fid,'*',page([raw('W2',['W1']),bad],2),'broken','now')
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM works').fetchone()[0],1)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM pages').fetchone()[0],0)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM citations').fetchone()[0],0)

    def test_count_drift_preserved_but_not_called_complete(self):
        self.add_seed();fid=self.front()
        process_page(self.s,fid,'*',page([raw('W2',['W1'])],2,'next'),'first','now')
        process_page(self.s,fid,'next',page([raw('W3',['W1'])],3,'more'),'second','now')
        f=self.s.db.execute('SELECT status,reason FROM frontiers').fetchone()
        self.assertEqual(tuple(f),('inconsistent','provider_count_drift'))
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM citations').fetchone()[0],2)

    def test_full_metadata_plan_keeps_unknown_fields_and_nonpilot_seeds(self):
        self.add_seed();self.add_seed('W2',field='')
        self.s.db.execute('UPDATE seeds SET pilot=0');self.s.db.commit()
        ids=self.s.plan('full-metadata',batch_size=1)
        self.assertEqual(len(ids),2)
        targets=[json.loads(r[0]) for r in self.s.db.execute("SELECT targets FROM frontiers WHERE stage='full-metadata'")]
        self.assertEqual({v for t in targets for v in t},{'W1','W2'})

    def test_snapshot_redacts_unexpected_provider_echo(self):
        c=self.mock_client(lambda path,params:(200,budget(),{}) if path=='/rate-limit' else (200,{'api_key':'unit-test-token','title':'Echo unit-test-token'},{}))
        c.key='unit-test-token';c.establish_budget();body,snapshot,_=c.request('/works',{})
        with gzip.open(self.s.path/'snapshots'/(snapshot+'.json.gz'),'rt',encoding='utf-8') as f:text=f.read()
        self.assertNotIn('unit-test-token',text);self.assertNotIn('api_key',body)

    def test_sampled_g2_shared_descendant_overlap_and_return_cycle(self):
        self.add_seed()
        for w in ['W2','W3','W4']:self.s.put_work(raw(w),'node')
        for a,b in [('W2','W1'),('W3','W1')]:self.s.db.execute('INSERT INTO citations VALUES(?,?,?)',(a,b,'later_year'))
        for parent,children in [('W2',['W4','W3']),('W3',['W4','W1'])]:
            fid=self.front((parent,),'g2')
            self.s.db.execute("UPDATE frontiers SET status='complete' WHERE id=?",(fid,))
            for child in children:
                self.s.db.execute('INSERT INTO edge_evidence VALUES(?,?,?,?,?)',(child,parent,fid,'snapshot','now'))
        self.s.db.commit()
        self.s.check('g2_selection',dict(seeds=[dict(seed='W1',sampled_intermediates=['W2','W3'],selection_probability=1,g1_population=2)]))
        result,reach,paths=deeper_reach(self.s)
        self.assertEqual(result['seeds'][0]['observed_new_g2_distinct'],1)
        self.assertEqual(result['seeds'][0]['g1_g2_overlap'],1)
        self.assertEqual(result['seeds'][0]['actual_two_edge_paths'],3)
        self.assertEqual([r['reached'] for r in reach],['W4'])
        self.assertEqual(sum(r['path_status']=='return_to_seed' for r in paths),1)

    def test_workload_reserves_metadata_before_full_queries(self):
        self.add_seed()
        self.s.check('pilot_acceptance',dict(passed=True))
        c=self.mock_client(lambda path,params:(200,budget(),{}));c.establish_budget()
        with self.assertRaises(StopAcquisition):acquire(self.s,c,'full')

    def test_compressed_and_plain_http_responses(self):
        payload=json.dumps({'results':[raw('W1')]}).encode()
        self.assertEqual(decode_response(payload,''),decode_response(gzip.compress(payload),'gzip'))
        with self.assertRaises(ValueError):decode_response(payload,'br')

    def test_full_gate_requires_every_resolved_seed_in_plan(self):
        self.add_seed('W1');self.add_seed('W2')
        fid=self.front(('W1',),'full')
        self.s.db.execute("UPDATE frontiers SET status='complete_empty' WHERE id=?",(fid,));self.s.db.commit()
        gate=full_gate(self.s)
        self.assertFalse(gate['passed'])
        self.assertTrue(gate['all_original_records_accounted'])
        self.assertFalse(gate['all_resolved_targets_planned'])
        self.assertEqual(gate['missing_resolved_targets'],['W2'])
        self.front(('W2',),'full')
        self.assertTrue(full_gate(self.s)['all_resolved_targets_planned'])

    def test_integrity_check_detects_changed_response_bytes(self):
        c=self.mock_client(lambda path,params:(200,budget(),{}) if path=='/rate-limit' else (200,page([]),{}))
        c.establish_budget();_,digest,_=c.request('/works',{})
        self.assertTrue(verify_study(self.s)['passed'])
        (self.s.path/'snapshots'/(digest+'.json.gz')).write_bytes(b'changed')
        result=verify_study(self.s)
        self.assertFalse(result['passed'])
        self.assertEqual(result['failures'][0]['reason'],'missing_or_changed_snapshot')
        self.s.put_work(raw('W1'),'nonexistent-proof');self.s.db.commit()
        self.assertEqual(verify_study(self.s)['provenance_without_request_snapshot'],['nonexistent-proof'])

    def test_analysis_normalized_exports_and_field_flow_denominators(self):
        self.add_seed('W1');self.add_seed('W2',inst='TIFR')
        fid=self.front(('W1','W2'),'full')
        process_page(self.s,fid,'*',page([raw('W3',['W1','W2'],field='19'),raw('W4',['W1'],field='')],2),'proof','now')
        analyze(self.s)
        with (self.s.path/'results/field_flows.csv').open(encoding='utf-8-sig',newline='') as f:
            flows=list(csv.DictReader(f))
        self.assertEqual(sum(int(r['seed_citer_links']) for r in flows if r['institution_membership']=='All'),3)
        self.assertEqual(sum(int(r['seed_citer_links']) for r in flows if r['institution_membership']=='IISc'),2)
        with (self.s.path/'results/works.csv').open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),4)
        self.assertEqual(next(r for r in rows if r['id']=='W3')['referenced_works_count'],'2')
        self.assertEqual(next(r for r in rows if r['id']=='W4')['field_missing'],'True')
        groups=json.loads((self.s.path/'results/group_summaries.json').read_text())
        iisc=next(r for r in groups if r['dimension']=='institution_membership' and r['value']=='IISc')
        self.assertEqual(iisc['known_year_edge_incidences'],2)
        self.assertEqual(iisc['pooled_cross_field_denominator'],1)
        self.assertEqual(iisc['pooled_cross_field_share'],1)
        self.assertEqual(iisc['age_eligible_complete_seeds'],1)
        self.assertEqual(iisc['age_known_field_edge_incidences'],0)
        self.assertIsNone(iisc['age_pooled_cross_field_share'])

    def test_partial_budget_checkpoint_resumes_to_terminal_completion(self):
        self.add_seed()
        meta=self.s.frontier('pilot-metadata','metadata',['W1'],{})
        self.s.db.execute("UPDATE frontiers SET status='complete' WHERE id=?",(meta,));self.s.db.commit()
        fid=self.s.plan('pilot')[0]
        process_page(self.s,fid,'*',page([raw('W2',['W1'])],2,'next'),'first','now')
        self.s.db.execute("UPDATE frontiers SET status='partial',reason='Free allowance safety reserve reached' WHERE id=?",(fid,));self.s.db.commit()
        c=self.mock_client(lambda path,params:(200,budget(),{}) if path=='/rate-limit' else (200,page([raw('W3',['W1'])],2),{}))
        c.establish_budget();acquire(self.s,c,'pilot',workers=1)
        f=self.s.db.execute('SELECT status,reason,pages FROM frontiers WHERE id=?',(fid,)).fetchone()
        self.assertEqual(tuple(f),('complete',None,2))
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM citations').fetchone()[0],2)

    def test_same_id_reference_is_flagged_without_inventing_new_reach(self):
        self.add_seed()
        self.s.db.execute('UPDATE works SET data=? WHERE id=?',(json.dumps(raw('W1',['W1'])),'W1'));self.s.db.commit()
        fid=self.front()
        process_page(self.s,fid,'*',page([raw('W1',['W1'])],1),'loop','now')
        row=records(self.s,'pilot')[0]
        self.assertTrue(row['provider_self_reference'])
        self.assertTrue(row['query_complete'])
        self.assertEqual(row['observed_citers'],0)
        self.assertEqual(self.s.db.execute('select count(*) from citations').fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
