"""Version-keyed CV planning queue. No model calls or external side effects."""
import hashlib
import json
import io
from core import stamp, now
from industry import classify
from sponsorship import evidence
from auto_apply import prior_application
import runtime_config

POLICY = "cv-queue-v1"
FINAL = {"Submitted","Manually Applied","Submission Confirmation Unknown","Closed","Rejected","Withdrawn","Not Interested","Duplicate"}

def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS cv_queue(
        key TEXT PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs(id),
        jd_hash TEXT NOT NULL, cv_hash TEXT NOT NULL, template_hash TEXT NOT NULL,
        policy TEXT NOT NULL, state TEXT NOT NULL, created TEXT NOT NULL,
        updated TEXT NOT NULL, reason TEXT NOT NULL, document TEXT,
        attempts INTEGER NOT NULL DEFAULT 0)""")
    from cv_worker import initialize as initialize_attempts
    initialize_attempts(c)

def digest_file(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None

def gate(job, settings):
    match=job.get("match") or {}
    if classify(job)["state"]!="allowed": return "industry"
    if job["status"] in FINAL or job["vacancy"]=="Closed": return "closed_or_previous_application"
    if job["country"] not in settings["enabled_countries"]: return "disabled_country"
    if not job.get("jd") or job["jd"].startswith("[Partial JD]"): return "incomplete_jd"
    if (match.get("score") or 0)<settings["cv_queue_threshold"]: return "below_threshold"
    if match.get("eligibility")=="Failed" or any(x.get("state")=="Failed" for x in match.get("checks",{}).values()):
        return "hard_eligibility_failure"
    profile=settings.get("work_authorization_profiles",{}).get(job["country"],{})
    needs=profile.get("state") in {"Requires sponsorship","Not authorized"}
    if evidence(job["jd"],needs)["excluded"]: return "sponsorship_refused"
    # Reuse exact hard-authorization and Japan gates from existing manual policy.
    import re
    if needs and re.search(r"\bmust\s+(?:(?:already|currently)\s+)?(?:be\s+(?:(?:already|currently|legally)\s+)*(?:authorized|eligible)\s+to\s+work|have\s+(?:(?:existing|valid)\s+)?work\s+authori[sz]ation)",job["jd"],re.I):
        return "existing_authorization_required"
    if job["country"]=="Japan":
        from workflow import japan_review
        reasons=japan_review(job,settings.get("japan_application_preferences",{}),evidence(job["jd"],needs))
        if any("明确要求日语" in r for r in reasons): return "required_language"
    return None

def reconcile(store):
    settings=store.settings()
    if not settings["cv_queue_enabled"]: return {"added":0,"state":"disabled"}
    cv=digest_file(runtime_config.resume_pdf())
    template=digest_file(runtime_config.resume_docx())
    if not cv or not template:
        with store.connect() as c:
            c.execute("UPDATE cv_queue SET state='blocked',reason='Resume PDF or DOCX unavailable',updated=? WHERE state='preview'",(stamp(),))
        return {"added":0,"state":"blocked","reason":"Resume PDF or DOCX unavailable"}
    added=0
    with store.connect() as c:
        for job in store.jobs():
            reason=gate(job,settings)
            if reason or prior_application(c,job):
                c.execute("UPDATE cv_queue SET state='blocked',reason=?,updated=? WHERE job=? AND state IN ('preview','failed')",
                          (reason or "previous_application",stamp(),job["id"]))
                continue
            match=job["match"]
            jd=hashlib.sha256(job["jd"].encode()).hexdigest()
            key=hashlib.sha256(json.dumps([job["id"],jd,cv,template,POLICY]).encode()).hexdigest()
            c.execute("UPDATE cv_queue SET state='superseded',updated=? WHERE job=? AND key<>? AND state IN ('preview','failed','blocked','ready','mock_completed')",
                      (stamp(),job["id"],key))
            if match.get("source_hash")!=cv or match.get("jd_hash")!=jd:
                continue
            c.execute("UPDATE cv_queue SET state='preview',reason='Dependencies and policy rechecked',updated=? WHERE key=? AND state='blocked'",
                      (stamp(),key))
            c.execute("UPDATE cv_queue SET state='superseded',updated=? WHERE job=? AND key<>? AND state IN ('preview','failed')",
                      (stamp(),job["id"],key))
            existing=c.execute("""SELECT d.id FROM documents d LEFT JOIN document_assets a ON a.document=d.id
                WHERE d.job=? AND d.kind='CV' AND d.source_hash=? AND d.jd_hash=? AND a.metadata LIKE ?
                ORDER BY d.rowid DESC LIMIT 1""",(job["id"],cv,jd,"%"+template+"%")).fetchone()
            changed=c.execute("INSERT OR IGNORE INTO cv_queue VALUES(?,?,?,?,?,?,?,?,?,?,?,0)",
                (key,job["id"],jd,cv,template,POLICY,"ready" if existing else "preview",stamp(),stamp(),
                 "Existing matching CV" if existing else "Live generation disabled; reviewable job, not eligibility approval",
                 existing[0] if existing else None))
            added+=changed.rowcount
    return {"added":added,"state":"preview_only"}

def panel(store):
    import cv_worker
    import product_policy
    day=product_policy.local_clock(store.settings(),now()).date().isoformat()
    with store.connect() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM cv_queue ORDER BY created DESC")]
        used=c.execute("SELECT count(*) FROM cv_queue_attempts WHERE budget_day=?",(day,)).fetchone()[0]
    return {"mode":"Enabled" if runtime_config.worker_status()["enabled"] else "Preview","worker":{**runtime_config.worker_status(),"health":dict(cv_worker.HEALTH)},"live_enabled":runtime_config.worker_status()["enabled"],"daily_limit":store.settings()["cv_queue_daily_limit"],"used_today":used,"remaining_today":max(0,store.settings()["cv_queue_daily_limit"]-used),
            "rows":rows,"counts":{state:sum(r["state"]==state for r in rows) for state in
            ("preview","ready","blocked","superseded","generating","mock_completed","failed")}}

def run_mock(store, renderer=None):
    if not runtime_config.fixture_mode():
        raise ValueError("Mock generation is available only in fixture mode.")
    status=reconcile(store)
    if status["state"] in {"blocked","disabled"}:
        return []
    limit=store.settings()["cv_queue_daily_limit"]
    outcomes=[]
    import product_policy
    settings=store.settings()
    day=product_policy.local_clock(settings,now()).date().isoformat()
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        used=sum(r["attempts"] for r in c.execute("SELECT attempts,updated FROM cv_queue WHERE attempts>0")
                 if product_policy.run_day(r["updated"],settings)==day)
        rows=[dict(r) for r in c.execute("SELECT * FROM cv_queue WHERE state='preview' ORDER BY created LIMIT ?",(max(0,limit-used),))]
        for row in rows:
            c.execute("UPDATE cv_queue SET state='generating',attempts=attempts+1,updated=? WHERE key=? AND state='preview'",(stamp(),row["key"]))
    for row in rows:
        try:
            if renderer:
                pdf=renderer(row)
            else:
                from reportlab.pdfgen import canvas
                output=io.BytesIO(); page=canvas.Canvas(output)
                page.drawString(60,780,"TEST ONLY - CV queue fixture")
                page.drawString(60,755,"Not a real application document")
                page.save(); pdf=output.getvalue()
            from pypdf import PdfReader
            if len(PdfReader(io.BytesIO(pdf)).pages)!=1:
                raise ValueError("Mock renderer must produce exactly one page")
            state,reason="mock_completed","Fixture rendered one page; no real document or application created"
        except Exception as error:
            state,reason="failed",type(error).__name__
        with store.connect() as c:
            c.execute("UPDATE cv_queue SET state=?,reason=?,updated=? WHERE key=? AND state='generating'",
                      (state,reason,stamp(),row["key"]))
        outcomes.append(state)
    return outcomes


def recover_interrupted(store):
    """Single bound server restart: retain rows and do not retry generation automatically."""
    with store.connect() as c:
        c.execute("UPDATE cv_queue_attempts SET state='interrupted',finished=?,error='ProcessInterrupted' WHERE state='running'",(stamp(),))
        return c.execute("UPDATE cv_queue SET state='failed',reason='Generation interrupted by restart; explicit review required',updated=? WHERE state='generating'",(stamp(),)).rowcount
