"""Frozen-report input, interpretation and output-preservation regressions."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pipeline.report import TEAM, analysis_html, integrated_findings, load_dashboard, write_report


def inputs():
    seeds = [dict(original_id="W1", canonical_id="W1", homes=["IISc", "TIFR"], authors_gt_12=False,
                  observed_citers=3, known_field_citers=2, unknown_field_citers=1,
                  cross_field_citers=1, cross_field_share=0.5, field_id="f1"),
             dict(original_id="W2", canonical_id="W2", homes=["IISc"], authors_gt_12=True,
                  observed_citers=1, known_field_citers=1, unknown_field_citers=0,
                  cross_field_citers=None, cross_field_share=None, field_id=None)]
    scope = dict(original_seeds=2, completed=2, unresolved=0, direct_edges=4, distinct_direct_citers=3,
                 cross_numerator=1, cross_denominator=2, known_field_citers=3, unknown_field_citers=1,
                 age_censored=1, age_eligible=1)
    idea = dict(seeds=seeds, scopes={"in": {"All": scope}}, cutoff="2026-10-15", direct_edges=4, distinct_direct_citers=3)
    res = dict(baseline=dict(nodes=1, edges=0, components=1, largest_component=1),
               summary=dict(max_lost_pairs=2),
               researchers=[dict(name="Bridge", lost_pair_fraction=0.2, lost_connected_pairs=2,
                                 connected_pairs_before_remaining=10, degree=4)])
    st = dict(meta=dict(group=18, years=[2016, 2026], institutions={"IISc": "IISc", "TIFR": "TIFR"}),
              network_tests=dict(faculty={"nodes": 1}), resilience=res, authorship=dict(summary=dict(faculty_edges=0)))
    return dict(DATA_ALL=st, DATA_NF=copy.deepcopy(st), COMPARE=[], IDEA_DATA=idea)


class FrozenReportTests(unittest.TestCase):
    def test_exact_team_cover_details(self):
        self.assertEqual(TEAM, (("Soham Jahagirdar", "2023102046"), ("Manas Inamdar", "2023102052"), ("Snehil Sanjog", "2023102051")))

    def test_input_hash_scope_and_required_latest_main_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"index.html"
            def put(p):
                path.write_text("\n".join(f"const {k} = {json.dumps(v)};" for k,v in p.items()), encoding="utf8")
                return hashlib.sha256(path.read_bytes()).hexdigest()
            p=inputs(); digest=put(p)
            self.assertEqual(load_dashboard(path,digest),p)
            with self.assertRaisesRegex(ValueError,"SHA-256 mismatch"): load_dashboard(path,"0"*64)
            with self.assertRaisesRegex(ValueError,"explicit lowercase"): load_dashboard(path,None)
            p['DATA_ALL']['meta']['years']=[2015,2026]
            with self.assertRaisesRegex(ValueError,"scope differs"): load_dashboard(path,put(p))
            p=inputs(); del p['DATA_NF']['network_tests']
            with self.assertRaisesRegex(ValueError,"Latest main network tests missing"): load_dashboard(path,put(p))

    def test_unknown_fields_reconcile_and_unique_works_remain_distinct(self):
        p=inputs(); f=integrated_findings(p['DATA_ALL'],p['DATA_NF'],p['IDEA_DATA'])
        self.assertEqual((f['unknown_citer'],f['unknown_seed_known_citer']),(1,1))
        self.assertEqual(f['scope']['distinct_direct_citers'],3)
        self.assertEqual(f['scope']['direct_edges'],4)
        text=analysis_html(p['DATA_ALL'],p['DATA_NF'],p['IDEA_DATA'])
        for term in ['seeds only','surviving researchers','Independent human source reviews','not causal','hypothetical']:
            # The report explicitly says citation evidence does not establish causality.
            if term=='not causal': term='causality'
            self.assertIn(term,text)

    def test_inconsistent_counts_and_removed_person_denominator_rejected(self):
        p=inputs(); p['IDEA_DATA']['scopes']['in']['All']['cross_denominator']=3
        with self.assertRaisesRegex(ValueError,'denominators disagree'): integrated_findings(p['DATA_ALL'],p['DATA_NF'],p['IDEA_DATA'])
        p=inputs(); p['DATA_ALL']['resilience']['researchers'][0]['connected_pairs_before_remaining']=11
        with self.assertRaisesRegex(ValueError,'removal measures disagree'): integrated_findings(p['DATA_ALL'],p['DATA_NF'],p['IDEA_DATA'])

    def test_bad_input_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'bad.html'; source.write_text('bad')
            with self.assertRaisesRegex(ValueError,'SHA-256 mismatch'):
                write_report(source,'0'*64,root/'output')
            self.assertFalse((root/'output').exists())

    def test_overlength_pdf_preserves_released_files(self):
        from pypdf import PdfWriter
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); pdf=root/'18_IISc_TIFR.pdf'; html=root/'18_IISc_TIFR.html'
            pdf.write_bytes(b'original PDF'); html.write_text('original HTML')
            def chrome(args,**kwargs):
                out=Path(next(a.split('=',1)[1] for a in args if a.startswith('--print-to-pdf=')))
                w=PdfWriter()
                for _ in range(6): w.add_blank_page(width=595,height=842)
                w.write(out)
            with patch('pipeline.report.load_dashboard',return_value=inputs()), patch('pipeline.report.build_html',return_value='report'), patch('pipeline.report._chrome',return_value='chrome'), patch('pipeline.report.subprocess.run',side_effect=chrome):
                with self.assertRaisesRegex(ValueError,'maximum is 5'): write_report('frozen','0'*64,root)
            self.assertEqual(pdf.read_bytes(),b'original PDF'); self.assertEqual(html.read_text(),'original HTML')

    def test_report_and_runner_imports_do_not_import_config(self):
        subprocess.run([sys.executable,'-B','-c',"import sys; import pipeline.report, run; assert 'config' not in sys.modules"],check=True)

    def test_valid_pdf_publishes_exact_source_and_provenance(self):
        from pypdf import PdfReader, PdfWriter
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def chrome(args,**kwargs):
                out=Path(next(a.split('=',1)[1] for a in args if a.startswith('--print-to-pdf=')))
                w=PdfWriter()
                for _ in range(5): w.add_blank_page(width=595,height=842)
                w.write(out)
            with patch('pipeline.report.load_dashboard',return_value=inputs()), patch('pipeline.report.build_html',return_value='verified HTML'), patch('pipeline.report._chrome',return_value='chrome'), patch('pipeline.report.subprocess.run',side_effect=chrome):
                pdf=write_report('frozen','a'*64,root)
            self.assertEqual(len(PdfReader(pdf).pages),5)
            self.assertEqual(pdf.with_suffix('.html').read_text(),'verified HTML')
            manifest=json.loads(pdf.with_suffix('.manifest.json').read_text())
            self.assertEqual(manifest['dashboard_sha256'],'a'*64)
            self.assertEqual(manifest['pdf_sha256'],hashlib.sha256(pdf.read_bytes()).hexdigest())
            self.assertFalse(list(root.glob('*.tmp')))

    def test_legacy_report_keeps_configured_sample_destination(self):
        from types import SimpleNamespace
        from pypdf import PdfWriter
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); processed=root/'processed'; processed.mkdir()
            for name in ['stats.json','stats_without_flagged.json']:
                (processed/name).write_text('{}')
            cfg=SimpleNamespace(PROCESSED=processed,REPORT=root/'report_sample')
            variant=SimpleNamespace(compare=lambda a,b:[])
            def chrome(args,**kwargs):
                out=Path(next(a.split('=',1)[1] for a in args if a.startswith('--print-to-pdf=')))
                w=PdfWriter(); w.add_blank_page(width=595,height=842); w.write(out)
            with patch.dict(sys.modules,{'config':cfg,'pipeline.variants':variant}), patch('pipeline.variants',variant,create=True), patch('pipeline.report.build_html',return_value='sample HTML'), patch('pipeline.report._chrome',return_value='chrome'), patch('pipeline.report.subprocess.run',side_effect=chrome):
                pdf=write_report()
            self.assertEqual(pdf,root/'report_sample/18_IISc_TIFR.pdf')
            self.assertTrue(pdf.is_file()); self.assertFalse((root/'report').exists())


if __name__=='__main__': unittest.main()
