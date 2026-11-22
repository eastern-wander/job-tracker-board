import datetime as dt
import unittest
from unittest.mock import patch
import core,discovery,matching,test_product
class FreshnessTests(unittest.TestCase):
    setUp=test_product.ProductTests.setUp
    settings=test_product.ProductTests.settings
    add=test_product.ProductTests.add
    def greenhouse(self,first=None):
        raw={"id":1,"internal_job_id":1,"title":"Operations Coordinator","location":{"name":"Vancouver"},"absolute_url":"https://example.invalid/jobs/1","content":__import__("fixture_demo").demo_jobs()[0]["jd"],"updated_at":self.clock.isoformat()}
        if first:raw["first_published"]=first
        return discovery.normalize("fixture","Demo",raw,self.store.settings(),self.clock)[1]
    def test_old_first_publication_updated_today_stays_old_and_deduplicates(self):
        old=(self.clock-dt.timedelta(days=30)).isoformat()
        item=self.greenhouse(old);item["industry_declared"]="traditional"
        first=self.store.ingest(item);second=self.store.ingest({**item,"updated_at":self.clock.isoformat()})
        self.assertEqual(first["id"],second["id"]);self.assertEqual(len(self.store.jobs()),1)
        self.assertFalse(core.within_discovery_window(item["original_posted_at"],self.clock,72))
        self.assertGreaterEqual(matching.analyze(item,self.profile)["score"],80)
    def test_verified_first_publication_within_72_hours_is_fresh(self):
        item=self.greenhouse((self.clock-dt.timedelta(hours=24)).isoformat())
        self.assertTrue(core.within_discovery_window(item["original_posted_at"],self.clock,72))
    def test_last_published_created_updated_and_first_sighting_are_not_original(self):
        uuid="12345678-1234-1234-1234-123456789012";jd=__import__("fixture_demo").demo_jobs()[0]["jd"]
        with patch("discovery.now",return_value=self.clock):
            ashby=discovery.normalize_ashby("demo-company","Demo",{"jobUrl":"https://jobs.ashbyhq.com/demo-company/"+uuid,"isListed":True,"title":"Operations Coordinator","location":"Vancouver","descriptionPlain":jd,"publishedAt":self.clock.isoformat()},self.store.settings())[1]
            lever=discovery.normalize_lever("demo-company","Demo",{"id":uuid,"hostedUrl":"https://jobs.lever.co/demo-company/"+uuid,"text":"Operations Coordinator","categories":{"location":"Vancouver"},"description":jd,"createdAt":int(self.clock.timestamp()*1000)},self.store.settings())[1]
        for item in [ashby,lever,self.greenhouse()]:
            self.assertFalse(core.within_discovery_window(item["original_posted_at"],self.clock,72))
            self.assertFalse(item["original_posted_at"])
            item["industry_declared"]="traditional"
            self.assertGreaterEqual(matching.analyze(item,self.profile)["score"],80)
        self.assertEqual(ashby["platform_date_kind"],"Last published")
    def test_older_ashby_job_republished_today_retains_verified_original_and_identity(self):
        uuid="12345678-1234-1234-1234-123456789012"
        old=self.clock-dt.timedelta(days=30)
        row={"jobUrl":"https://jobs.ashbyhq.com/demo-company/"+uuid,"isListed":True,"title":"Operations Coordinator","location":"Vancouver","descriptionPlain":__import__("fixture_demo").demo_jobs()[0]["jd"],"publishedAt":old.isoformat()}
        with patch("discovery.now",return_value=self.clock):
            initial=discovery.normalize_ashby("demo-company","Demo",row,self.store.settings())[1]
            # Synthetic independent first-publication proof, not inferred from publishedAt.
            initial.update(original_posted_at=old.isoformat(),posted=old.astimezone(core.TZ).date().isoformat(),posting_date_evidence="Fixture independently verified original timestamp")
            first=self.store.ingest(initial)
            republished=discovery.normalize_ashby("demo-company","Demo",{**row,"publishedAt":self.clock.isoformat()},self.store.settings())[1]
            second=self.store.ingest(republished)
        self.assertEqual(first["id"],second["id"]);self.assertEqual(len(self.store.jobs()),1)
        stored=self.store.jobs()[0]
        self.assertFalse(core.within_discovery_window(stored["original_posted_at"],self.clock,72))
        self.assertEqual(dt.datetime.fromisoformat(stored["original_posted_at"]),old)
        self.assertGreaterEqual(matching.analyze(stored,self.profile)["score"],80)

if __name__=="__main__":unittest.main()
