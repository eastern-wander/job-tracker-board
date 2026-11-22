import tempfile
import unittest

from core import Store
from discovery import normalize
from sponsorship import evidence
from workflow import application_day, japan_review


class ApplicationDayTests(unittest.TestCase):
    def test_only_receipted_attempts_succeed_on_utc_date(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            job = store.ingest(dict(title="Project Coordinator", company="Example", location="Vancouver",
                                    country="Canada", source="Manual", url="https://example.com/job/1"))["id"]
            with store.connect() as c:
                c.execute("INSERT INTO apply_attempts(job,platform,state,created,confirmed_at,detail) VALUES(?,?,?,?,?,?)",
                          (job, "LinkedIn", "confirmed", "2026-11-05T01:00:00+00:00", "2026-11-05T01:01:00+00:00",
                           '{"receipt":"test receipt","cv":"v1","cl":"v2"}'))
                self.assertEqual(len(application_day(c, "2026-11-05")["automatic"]), 1)
                self.assertEqual(len(application_day(c, "2026-11-04")["automatic"]), 0)
                c.execute("UPDATE apply_attempts SET detail='historical note'")
                groups = application_day(c, "2026-11-05")
                self.assertEqual(len(groups["automatic"]), 0)
                self.assertEqual(len(groups["pending"]), 1)

    def test_japan_location_and_independent_gates(self):
        _, job = normalize("test", "Test", dict(id=1, internal_job_id=2, title="Business Operations Specialist",
            location={"name":"東京都"}, absolute_url="https://example.com/job/1",
            content="Business-level Japanese required; English proficiency strongly preferred.\nWe do sponsor visas."), {}, verification=True)
        self.assertEqual(job["country"], "Japan")
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            self.assertEqual(store.ingest(job)["result"], "added")
            self.assertEqual(store.jobs()[0]["country"], "Japan")
        support = evidence(job["jd"], True)
        self.assertTrue(support["evidence"])
        reasons = japan_review(job, dict(japanese="none", work_authorized=False, requires_sponsorship=True), support)
        self.assertTrue(any("明确要求日语" in reason for reason in reasons))
        self.assertTrue(any("目前无日本工作许可" in reason for reason in reasons))
        self.assertTrue(any("签证支持及适用条件" in reason for reason in reasons))
