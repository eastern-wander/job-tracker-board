import json
import tempfile
import unittest

import assisted_apply as assisted
from core import Store, stamp

URL = "https://job-boards.greenhouse.io/fixture/jobs/123"


class AssistedApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.job = self.store.ingest(dict(title="Operations Specialist", company="Fixture",
            location="Toronto", country="Canada", vacancy="Active", source="Greenhouse", url=URL,
            industry_declared="traditional", jd="Coordinate project logistics and partnerships."))["id"]
        with self.store.connect() as c:
            c.execute("UPDATE jobs SET match=? WHERE id=?", (json.dumps(
                {"score": 86, "checks": {}, "source_hash": "profile", "jd_hash": "description"}), self.job))
            for kind in ("CV", "CL"):
                c.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)",
                          (kind, self.job, stamp(), kind, "profile", "[]", b"fixture", "description"))
                c.execute("INSERT INTO document_assets VALUES(?,NULL,'{}')", (kind,))
                c.execute("UPDATE document_assets SET metadata=? WHERE document=?", ('{"fixture":true}', kind))
        assisted.profile(self.store, {"country":"Canada","identity":{"name":"QA Tester",
            "email":"qa@example.invalid","phone":"+1 604 555 0100"},"answers":{
            "work_authorization":"No","sponsorship":"Yes"},"confirmed":True})

    def act(self, action, **kwargs):
        return assisted.apply_action(self.store, {"id": self.job, "action": action, **kwargs})

    def enable(self):
        assisted.mode(self.store, {"mode":"Assisted Apply", "ack":True})

    def test_dry_run_and_per_job_confirmation(self):
        self.assertEqual(assisted.panel(self.store)["mode"], "Dry Run")
        with self.assertRaises(ValueError):
            self.act("open", reviewed=True)
        with self.assertRaises(ValueError):
            assisted.mode(self.store, {"mode":"Assisted Apply"})
        self.enable()
        with self.assertRaises(ValueError):
            self.act("open")
        self.assertEqual(self.act("open", reviewed=True)["stage"], "Assisted filling")
        with self.assertRaises(ValueError):
            self.act("open", reviewed=True)

    def test_employer_requires_existing_work_authorization(self):
        job = assisted.job_row(self.store, self.job)
        profile = assisted.profile(self.store)
        job["jd"] += " Applicants must be currently authorized to work in Canada on a full-time basis."
        self.assertIn("JD 明确要求已有工作许可", assisted.blockers(job, profile, {}))
        job["jd"] = "We ask whether applicants are currently authorized to work in Canada."
        self.assertNotIn("JD 明确要求已有工作许可", assisted.blockers(job, profile, {}))

    def test_receipt_is_only_success_and_preserves_used_versions(self):
        self.enable()
        self.act("open", reviewed=True)
        with self.assertRaises(ValueError):
            self.act("submitted", confirmed=True)
        self.act("review", reviewed=True, docs={"CV":"CV"})
        self.assertEqual(assisted.panel(self.store)["counts"]["awaiting"], 1)
        self.act("submitted", confirmed=True)
        self.assertEqual(assisted.panel(self.store)["counts"]["submitted"], 0)
        with self.assertRaises(ValueError):
            self.act("open", reviewed=True)
        self.act("receipt", confirmed=True, proof_kind="Application number", proof="Fixture receipt ABC123")
        panel = assisted.panel(self.store)
        self.assertEqual(panel["counts"]["submitted"], 1)
        self.assertEqual(panel["jobs"][0]["stage"], "Receipt verified")
        self.assertEqual(panel["jobs"][0]["attempt"]["payload"]["used_docs"], {"CV":"CV"})
        with self.assertRaises(ValueError):
            self.act("requeue", confirmed=True, proof="Employer says no application")

    def test_legacy_unverified_requires_evidence_to_requeue(self):
        self.store.update(self.job, {"status":"Submission Confirmation Unknown","evidence":"fixture"})
        self.enable()
        with self.assertRaises(ValueError):
            self.act("open", reviewed=True)
        with self.assertRaises(ValueError):
            self.act("requeue", confirmed=True, proof="No confirmation email found")
        self.act("requeue", confirmed=True, proof_kind="Platform rejected", proof="Website confirms it rejected the attempt")
        self.assertEqual(self.act("open", reviewed=True)["stage"], "Assisted filling")

    def test_unresolved_import_is_deduplicated(self):
        assisted.save_backlog(self.store, URL+"?utm_source=foo", "Unreadable")
        assisted.save_backlog(self.store, URL, "Needs JD")
        rows = assisted.panel(self.store)["backlog"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "Needs JD")
        assisted.save_backlog(self.store, URL)
        self.assertEqual(assisted.panel(self.store)["backlog"], [])

    def test_profile_edit_requires_new_review(self):
        self.enable()
        self.act("open", reviewed=True)
        assisted.profile(self.store, {"country":"Canada","identity":{"phone":"+1 604 555 0101"},
            "answers":{}, "confirmed":True})
        with self.assertRaisesRegex(ValueError, "已变化"):
            self.act("review", reviewed=True, docs={"CV":"CV"})
