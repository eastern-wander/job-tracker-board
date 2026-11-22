import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app, core, cv_queue, discovery, matching, product_policy, runtime_config
from core import Store
from fixture_demo import create_profile, demo_jobs

class ProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        create_profile(self.folder/"profile")
        self.pdf=self.folder/"profile/main.pdf"; self.docx=self.folder/"profile/main.docx"
        for target,value in [("core.MAIN",self.pdf),("matching.MAIN",self.pdf),("app.MAIN",self.pdf)]:
            p=patch(target,value);p.start();self.addCleanup(p.stop)
        for target,value in [("runtime_config.resume_pdf",self.pdf),("runtime_config.resume_docx",self.docx),("runtime_config.facts_file",self.folder/"profile/confirmed_facts.json")]:
            p=patch(target,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch("app.email_alerts.load",return_value={});p.start();self.addCleanup(p.stop)
        self.store=Store(self.folder/"db")
        self.profile=matching.candidate()
        self.clock=dt.datetime(2026,11,22,7,tzinfo=core.TZ)

    def settings(self,**changes):
        with self.store.connect() as c:
            for k,v in changes.items(): c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",(k,json.dumps(v)))

    def add(self,index=0,**changes):
        item={**demo_jobs()[index],**changes}
        ident=self.store.ingest(item)["id"]
        job=next(j for j in self.store.jobs() if j["id"]==ident)
        matching.persist_match(self.store,job,matching.analyze(job,self.profile))
        return ident

    def test_all_five_countries_and_no_fabricated_dates(self):
        for country,location in [("Canada","Vancouver"),("United States","Seattle"),("UK","London"),("Japan","Tokyo"),("UAE","Dubai")]:
            row=dict(id=1,internal_job_id=1,title="Operations Coordinator",location={"name":location},absolute_url="https://example.invalid/jobs/1",content=demo_jobs()[0]["jd"])
            item=discovery.normalize("fixture","Demo",row,self.store.settings(),self.clock)[1]
            self.assertEqual(item["country"],country)
            self.assertFalse(item["original_posted_at"])
        self.settings(enabled_countries=["Canada"])
        self.assertIsNone(discovery.normalize("fixture","Demo",{**row,"location":{"name":"Seattle"}},self.store.settings(),self.clock))

    def test_freshness_is_elapsed_hours_and_unknown_stays_unknown(self):
        cutoff=self.clock.astimezone(dt.timezone.utc)-dt.timedelta(hours=24)
        self.assertTrue(core.within_discovery_window(cutoff.isoformat(),self.clock,24))
        self.assertFalse(core.within_discovery_window((cutoff-dt.timedelta(seconds=1)).isoformat(),self.clock,24))
        self.assertFalse(core.within_discovery_window("2026-11-21",self.clock,24))
        self.assertFalse(core.within_discovery_window(None,self.clock,24))
        self.assertFalse(core.within_discovery_window("bad-date",self.clock,24))

    def test_timezone_schedule_and_recovery_once(self):
        self.settings(timezone="Europe/London")
        with self.store.connect() as c:c.execute("INSERT INTO settings VALUES('scheduler_started',?)",(json.dumps("2026-11-01"),))
        clock=dt.datetime(2026,11,22,8,59,tzinfo=dt.timezone.utc)
        self.assertEqual(app.scheduled_kind(self.store,clock),"Recovery")
        with self.store.connect() as c:c.execute("INSERT INTO runs VALUES('r',?,'Recovery','{}')",(clock.isoformat(),))
        self.assertIsNone(app.scheduled_kind(self.store,clock))
        self.assertEqual(app.scheduled_kind(self.store,clock+dt.timedelta(minutes=1)),"Scheduled")

    def test_health_failed_missing_done_stale(self):
        s=self.store.settings()
        clock=self.clock.replace(hour=10)
        self.assertEqual(product_policy.relevant_run_health([],s,clock)["state"],"missing")
        failed=[{"kind":"Scheduled","created":clock.isoformat(),"result":{"errors":["fixture"]}}]
        self.assertEqual(product_policy.relevant_run_health(failed,s,clock)["state"],"failed")
        failed[0]["result"]={}
        self.assertEqual(product_policy.relevant_run_health(failed,s,clock)["state"],"done")
        self.assertTrue(product_policy.relevant_run_health(failed,s,clock+dt.timedelta(days=2))["stale"])

    def test_queue_idempotency_and_version_changes(self):
        self.settings(cv_queue_threshold=60)
        self.add()
        self.assertEqual(cv_queue.reconcile(self.store)["added"],1)
        self.assertEqual(cv_queue.reconcile(self.store)["added"],0)
        self.docx.write_bytes(self.docx.read_bytes()+b"fixture new version")
        self.assertEqual(cv_queue.reconcile(self.store)["added"],1)
        self.assertEqual(cv_queue.panel(self.store)["counts"]["superseded"],1)
        reopened=Store(self.folder/"db")
        self.assertEqual(cv_queue.reconcile(reopened)["added"],0)

    def test_stale_cv_and_missing_files_never_consumed(self):
        self.settings(cv_queue_threshold=60);self.add();cv_queue.reconcile(self.store)
        self.pdf.write_bytes(self.pdf.read_bytes()+b"new fixture version")
        with patch("runtime_config.fixture_mode",return_value=True):
            self.assertEqual(cv_queue.run_mock(self.store),[])
        self.assertEqual(cv_queue.panel(self.store)["counts"]["superseded"],1)

    def test_missing_dependency_blocks_then_recovers_same_queue_key(self):
        self.settings(cv_queue_threshold=60);self.add();cv_queue.reconcile(self.store)
        original=self.docx.read_bytes();self.docx.unlink()
        with patch("runtime_config.fixture_mode",return_value=True):
            self.assertEqual(cv_queue.run_mock(self.store),[])
        self.assertEqual(cv_queue.panel(self.store)["counts"]["blocked"],1)
        self.docx.write_bytes(original)
        self.assertEqual(cv_queue.reconcile(self.store)["added"],0)
        self.assertEqual(cv_queue.panel(self.store)["counts"]["preview"],1)

    def test_queue_retains_unknown_eligibility_without_approving_it(self):
        self.settings(cv_queue_threshold=60);ident=self.add()
        cv_queue.reconcile(self.store)
        self.assertEqual(cv_queue.panel(self.store)["counts"]["preview"],1)
        self.assertEqual(self.store.jobs()[0]["match"]["eligibility"],"Unverified")
        self.assertTrue(app.dashboard(self.store)["jobs"][0]["application_blockers"])

    def test_queue_skips_hard_failure_and_previous_application(self):
        self.settings(cv_queue_threshold=60); ident=self.add()
        with self.store.connect() as c:
            raw=json.loads(c.execute("SELECT match FROM jobs WHERE id=?",(ident,)).fetchone()[0]);raw["checks"]["Languages"]["state"]="Failed"
            c.execute("UPDATE jobs SET match=? WHERE id=?",(json.dumps(raw),ident))
        self.assertEqual(cv_queue.reconcile(self.store)["added"],0)
        with self.store.connect() as c:
            raw["checks"]["Languages"]["state"]="Unverified"
            c.execute("UPDATE jobs SET match=?,status='Submission Confirmation Unknown' WHERE id=?",(json.dumps(raw),ident))
        self.assertEqual(cv_queue.reconcile(self.store)["added"],0)

    def test_queue_skips_sponsorship_refusal_when_needed(self):
        self.settings(cv_queue_threshold=60,work_authorization_profiles={"Canada":{"state":"Requires sponsorship"}})
        self.add(jd=demo_jobs()[0]["jd"]+" We do not provide visa sponsorship.")
        self.assertEqual(cv_queue.reconcile(self.store)["added"],0)

    def test_mock_one_page_and_no_real_documents_or_repeat(self):
        self.settings(cv_queue_threshold=60);self.add();cv_queue.reconcile(self.store)
        with patch("runtime_config.fixture_mode",return_value=True):
            self.assertEqual(cv_queue.run_mock(self.store),["mock_completed"])
            self.assertEqual(cv_queue.run_mock(self.store),[])
        with self.store.connect() as c:
            self.assertEqual(c.execute("select count(*) from documents").fetchone()[0],0)
            self.assertEqual(c.execute("select count(*) from application_records").fetchone()[0],0)

    def test_mock_daily_budget_and_claim_survive_repeat_calls(self):
        self.settings(cv_queue_threshold=60,cv_queue_daily_limit=1)
        self.add(0);self.add(1);cv_queue.reconcile(self.store)
        with patch("runtime_config.fixture_mode",return_value=True):
            self.assertEqual(cv_queue.run_mock(self.store),["mock_completed"])
            self.assertEqual(cv_queue.run_mock(self.store),[])
        self.assertEqual(cv_queue.panel(self.store)["counts"]["preview"],1)

    def test_mock_failure_preserves_queue_without_automatic_retry(self):
        self.settings(cv_queue_threshold=60);self.add();cv_queue.reconcile(self.store)
        with patch("runtime_config.fixture_mode",return_value=True):
            self.assertEqual(cv_queue.run_mock(self.store,lambda row:b"invalid PDF"),["failed"])
            self.assertEqual(cv_queue.run_mock(self.store),[])

    def test_interrupted_queue_is_failed_without_retry(self):
        self.settings(cv_queue_threshold=60);self.add();cv_queue.reconcile(self.store)
        with self.store.connect() as c:
            c.execute("UPDATE cv_queue SET state='generating',attempts=1")
        self.assertEqual(cv_queue.recover_interrupted(self.store),1)
        self.assertEqual(cv_queue.recover_interrupted(self.store),0)
        with patch("runtime_config.fixture_mode",return_value=True):
            self.assertEqual(cv_queue.run_mock(self.store),[])
        self.assertEqual(cv_queue.panel(self.store)["counts"]["failed"],1)

    def test_production_cannot_run_mock_or_model(self):
        with patch("runtime_config.fixture_mode",return_value=False):
            with self.assertRaises(ValueError):cv_queue.run_mock(self.store)
        import material_model
        with patch("runtime_config.model_enabled",return_value=False),patch("material_model.subprocess.run") as network:
            with self.assertRaises(ValueError): material_model.request_json("fixture",{},None,{})
            network.assert_not_called()

    def test_dashboard_survives_missing_cv_and_template(self):
        self.add()
        self.pdf.unlink();self.docx.unlink()
        state=app.dashboard(self.store)
        self.assertFalse(state["dependency_health"]["resume_pdf"]["readable"])
        self.assertEqual(len(state["jobs"]),1)
        self.assertEqual(cv_queue.reconcile(self.store)["state"],"blocked")

    def test_discovery_finishes_report_if_resume_unreadable(self):
        self.settings(boards="",lever_boards="")
        self.pdf.unlink()
        with patch("app.collect",return_value=[demo_jobs()[0]]),patch("app.candidate",side_effect=PermissionError("fixture")),patch("runtime_config.fixture_mode",return_value=True):
            result=app.run_tasks(self.store,"Catch-up",active_only=True)
        self.assertEqual(result["added"],1)
        self.assertEqual(result["matching_status"],"blocked")
        self.assertTrue(result["errors"])
        self.assertIn("discovery",result)
        with self.store.connect() as c:self.assertEqual(c.execute("select count(*) from runs").fetchone()[0],1)

    def test_baseline_same_sample_scores_unchanged(self):
        source=Path(__file__).resolve().parent.parent/"baseline/matching.py"
        if not source.exists() or not (Path(__file__).resolve().parent/"fixtures/scoring.json").exists(): self.skipTest("Baseline is private review evidence, not distributed")
        spec=importlib.util.spec_from_file_location("baseline_matching",source)
        old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        fixture=Path(__file__).resolve().parent/"fixtures/scoring.json"
        for item in json.loads(fixture.read_text()):
            profile={"facts":[{"id":"F001","page":1,"text":item["matched"]}],"roles":[{"id":"R001"}],"sha256":"fixture"}
            job={"title":item["title"],"company":"Fixture","country":item["country"],"jd":item["jd"],"industry_declared":"traditional"}
            a=old.analyze(job,profile);b=matching.analyze(job,profile)
            self.assertEqual(a["score"],b["score"]);self.assertEqual(a["checks"],b["checks"])

    def test_settings_validation_does_not_enable_live(self):
        s=self.store.settings()
        product_policy.validate(s)
        with self.assertRaises(ValueError):product_policy.validate({**s,"cv_queue_mode":"Live"})
        with self.assertRaises(Exception):product_policy.validate({**s,"timezone":"Not/AZone"})

if __name__=="__main__":unittest.main(verbosity=2)
