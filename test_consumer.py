import io,json,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import test_product,cv_queue,matching,runtime_config
import cv_worker

class ConsumerTests(unittest.TestCase):
    setUp=test_product.ProductTests.setUp
    settings=test_product.ProductTests.settings
    add=test_product.ProductTests.add

    def seed(self,count=1):
        self.settings(cv_queue_threshold=60)
        for i in range(count):self.add(i)
        cv_queue.reconcile(self.store)
        return cv_queue.panel(self.store)["rows"][0]["key"]

    def artifact(self,job,profile):
        from reportlab.pdfgen import canvas
        out=io.BytesIO();c=canvas.Canvas(out);c.drawString(40,750,"TEST ONLY - fake CV");c.save()
        return out.getvalue(),[{"id":f["id"],"text":f["text"]} for f in profile["facts"] if f["role"]],self.docx.read_bytes(),{"template_sha256":cv_queue.digest_file(self.docx)}

    def run_fake(self,adapter=None):
        with patch("runtime_config.fixture_mode",return_value=True):
            return cv_worker.consume(self.store,adapter=adapter or self.artifact,test_mode=True)

    def test_disabled_never_claims_or_calls_adapter(self):
        self.seed()
        with patch("cv_worker.production_adapter") as call:
            self.assertEqual(cv_worker.consume(self.store),[])
            call.assert_not_called()
        self.assertEqual(cv_queue.panel(self.store)["counts"]["preview"],1)

    def test_real_runtime_rejects_injected_adapter(self):
        self.seed()
        with patch("runtime_config.fixture_mode",return_value=False):
            with self.assertRaises(ValueError):cv_worker.consume(self.store,adapter=self.artifact,test_mode=True)

    def test_cv_only_atomic_completion_and_idempotency(self):
        self.seed()
        self.assertEqual(self.run_fake(),["ready"])
        self.assertEqual(self.run_fake(),[])
        with self.store.connect() as c:
            self.assertEqual([r[0] for r in c.execute("SELECT kind FROM documents")],["CV"])
            self.assertEqual(c.execute("SELECT count(*) FROM application_records").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM cv_queue_attempts").fetchone()[0],1)
        self.assertEqual(cv_queue.panel(self.store)["counts"]["ready"],1)

    def test_concurrent_consumers_share_atomic_daily_cap(self):
        self.seed(2);self.settings(cv_queue_daily_limit=1)
        with patch("runtime_config.fixture_mode",return_value=True):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:cv_worker.consume(self.store,adapter=self.artifact,test_mode=True),range(2)))
        self.assertEqual(sum(len(x) for x in results),1)

    def test_error_is_sanitized_and_retry_is_explicit_and_bounded(self):
        key=self.seed()
        def fail(*args):raise ValueError("private@example.invalid secret")
        for i in range(3):
            self.assertEqual(self.run_fake(fail),["failed"])
            self.assertEqual(self.run_fake(fail),[])
            if i<2:cv_worker.retry(self.store,key)
        with self.assertRaises(ValueError):cv_worker.retry(self.store,key)
        with self.store.connect() as c:
            text=json.dumps([dict(r) for r in c.execute("SELECT * FROM cv_queue_attempts")])
            self.assertNotIn("private@",text);self.assertNotIn("secret",text)
            self.assertEqual(c.execute("SELECT count(*) FROM documents").fetchone()[0],0)

    def test_retry_cannot_evade_daily_budget(self):
        key=self.seed();self.settings(cv_queue_daily_limit=1)
        self.run_fake(lambda *args:(_ for _ in ()).throw(ValueError()))
        cv_worker.retry(self.store,key)
        self.assertEqual(self.run_fake(),[])

    def test_template_changed_during_render_cannot_commit(self):
        self.seed()
        def changed(job,profile):
            result=self.artifact(job,profile)
            self.docx.write_bytes(self.docx.read_bytes()+b"changed")
            return result
        self.assertEqual(self.run_fake(changed),["failed"])
        with self.store.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM documents").fetchone()[0],0)

    def test_known_hard_failure_added_after_claim_cannot_commit(self):
        self.seed()
        def changed(job,profile):
            result=self.artifact(job,profile)
            with self.store.connect() as c:c.execute("UPDATE jobs SET status='Submission Confirmation Unknown'")
            return result
        self.assertEqual(self.run_fake(changed),["failed"])

    def test_restart_marks_claim_interrupted_without_retry(self):
        key=self.seed()
        row=cv_worker.claim(self.store)
        self.assertIsNotNone(row)
        self.assertEqual(cv_queue.recover_interrupted(self.store),1)
        self.assertEqual(self.run_fake(),[])
        with self.store.connect() as c:
            self.assertEqual(c.execute("SELECT state FROM cv_queue_attempts").fetchone()[0],"interrupted")

    def test_template_version_produces_one_new_cv(self):
        self.seed();self.run_fake()
        self.docx.write_bytes(self.docx.read_bytes()+b"new version")
        cv_queue.reconcile(self.store)
        self.assertEqual(self.run_fake(),["ready"])
        with self.store.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM documents").fetchone()[0],2)
        self.assertEqual(cv_queue.panel(self.store)["counts"]["ready"],1)
        self.assertEqual(cv_queue.panel(self.store)["counts"]["superseded"],1)

    def test_opt_in_requires_every_authorization_flag(self):
        config={"model_calls_enabled":True,"cv_worker_enabled":True,"cv_worker_authorization":{
            "provider":"codex_cli_chatgpt","endpoint_verified":True,"credentials_verified":True,
            "data_authorized":True,"cost_authorized":True}}
        with patch("runtime_config.config",return_value=config),patch("runtime_config.fixture_mode",return_value=False):
            self.assertTrue(runtime_config.worker_status()["enabled"])
            for key in ["endpoint_verified","credentials_verified","data_authorized","cost_authorized"]:
                config["cv_worker_authorization"][key]=False
                self.assertFalse(runtime_config.worker_status()["enabled"])
                config["cv_worker_authorization"][key]=True

    def test_worker_uses_existing_cv_adapter_not_cl(self):
        self.seed();job=self.store.jobs()[0];profile=matching.candidate()
        with patch("material_model.plan_cv",return_value=({"resume_bullets":[]} ,{})) as plan,patch("resume_template.render",return_value=self.artifact(job,profile)) as render,patch("material_model.plan") as combined,patch("material_model.plan_letter") as cl:
            cv_worker.production_adapter(job,profile)
            plan.assert_called_once();render.assert_called_once();combined.assert_not_called();cl.assert_not_called()

    def test_cv_prompt_omits_contact_block_and_has_no_letter_output(self):
        import material_model
        self.seed();job=self.store.jobs()[0];profile=matching.candidate()
        job["jd"]+=" Contact Alex Example at demo@example.invalid or +1 604 555 0100. Experience 2018-2024."
        prompt,schema=material_model.cv_request(job,profile)
        self.assertNotIn("demo@example.invalid",prompt);self.assertNotIn("+1 604 555 0100",prompt)
        self.assertNotIn("Alex Example",prompt);self.assertIn("2018-2024",prompt)
        self.assertNotIn("letter",schema["properties"])
        self.assertNotIn("identity",schema["properties"])

    def test_cv_only_plan_reuses_one_request_without_cl_or_hidden_retry(self):
        import material_model
        self.seed();job=self.store.jobs()[0];profile=matching.candidate()
        text="Coordinated vendor onboarding and project delivery with clear client communication and consistent operations."
        facts=[f["id"] for f in profile["facts"] if f["role"]]
        selection={"cv_facts":facts[:8],"cv_skills":[],"resume_summary":"An operations professional supporting client projects and vendor coordination with practical experience in reliable delivery clear communication and evidence based planning across teams.",
                   "resume_bullets":[{"id":f,"text":text,"compact":text} for f in facts]}
        with patch("runtime_config.worker_status",return_value={"enabled":True}),patch("material_model.shutil.which",return_value="fake-cli"),patch("material_model.request_json",return_value=(selection,{})) as request,patch("material_model.review_letter") as cl:
            result,audit=material_model.plan_cv(job,profile)
            self.assertIn("resume_bullets",result);request.assert_called_once();cl.assert_not_called()

    def test_real_offline_template_renderer_with_fake_profile(self):
        import resume_template,shutil
        if not (shutil.which("soffice")):
            self.skipTest("Local office renderer unavailable")
        self.seed();job=self.store.jobs()[0];profile=matching.candidate()
        bullets=[{"id":f["id"],"text":f["text"],"compact":f["text"]} for f in profile["facts"] if f["role"]]
        selected={"resume_summary":profile["summary"]["text"],"resume_bullets":bullets,"cv_facts":[b["id"] for b in bullets]}
        with patch("material_model.plan_cv",return_value=(selected,{})) as model:
            artifact=cv_worker.production_adapter(job,profile)
        row=cv_queue.panel(self.store)["rows"][0]
        cv_worker.validate_artifact(artifact,profile,row)
        self.assertEqual(artifact[3]["pages"],1)
        self.assertIn("original OOXML",artifact[3]["renderer"])
        with patch("material_model.plan_cv",return_value=(selected,{})):
            self.assertEqual(self.run_fake(cv_worker.production_adapter),["ready"])
        with self.store.connect() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM documents WHERE kind='CV'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT count(*) FROM documents WHERE kind='CL'").fetchone()[0],0)

if __name__=="__main__":unittest.main(verbosity=2)
