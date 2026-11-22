"""CV-only queue consumer. Outbound calls require explicit, separately verified opt-in."""
import hashlib,io,json,threading,time,uuid
from core import now,stamp
import cv_queue,product_policy,runtime_config

MAX_ATTEMPTS=3
HEALTH={"state":"not_started","last_check":None,"error":None}
def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS cv_queue_attempts(
        token TEXT PRIMARY KEY, queue_key TEXT NOT NULL REFERENCES cv_queue(key),
        budget_day TEXT NOT NULL, started TEXT NOT NULL, finished TEXT,
        state TEXT NOT NULL, error TEXT NOT NULL)""")

def claim(store):
    settings=store.settings()
    day=product_policy.local_clock(settings,now()).date().isoformat()
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        used=c.execute("SELECT count(*) FROM cv_queue_attempts WHERE budget_day=?",(day,)).fetchone()[0]
        if not settings["cv_queue_enabled"] or used>=settings["cv_queue_daily_limit"]:return None
        row=c.execute("SELECT * FROM cv_queue WHERE state='preview' AND attempts<? ORDER BY created,key LIMIT 1",(MAX_ATTEMPTS,)).fetchone()
        if not row:return None
        row=dict(row);token=uuid.uuid4().hex
        c.execute("UPDATE cv_queue SET state='generating',attempts=attempts+1,updated=?,reason='CV-only generation in progress' WHERE key=? AND state='preview'",(stamp(),row["key"]))
        c.execute("INSERT INTO cv_queue_attempts VALUES(?,?,?,?,NULL,'running','')",(token,row["key"],day,stamp()))
        return {**row,"token":token}

def retry(store,key):
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT state,attempts FROM cv_queue WHERE key=?",(key,)).fetchone()
        if not row or row["state"]!="failed" or row["attempts"]>=MAX_ATTEMPTS:
            raise ValueError("Only failed entries below the three-attempt limit can be explicitly retried.")
        c.execute("UPDATE cv_queue SET state='preview',reason='Explicit retry requested; daily budget still applies',updated=? WHERE key=?",(stamp(),key))

def checked_job(store,row,profile=None):
    import matching
    from auto_apply import prior_application
    jobs=[j for j in store.jobs() if j["id"]==row["job"]]
    if not jobs:raise ValueError("Job unavailable")
    job=jobs[0]
    if cv_queue.gate(job,store.settings()):raise ValueError("Policy changed")
    with store.connect() as c:
        if prior_application(c,job):raise ValueError("Previous application")
    if (cv_queue.digest_file(runtime_config.resume_pdf())!=row["cv_hash"] or
        cv_queue.digest_file(runtime_config.resume_docx())!=row["template_hash"] or
        hashlib.sha256(job["jd"].encode()).hexdigest()!=row["jd_hash"] or
        (job["match"] or {}).get("source_hash")!=row["cv_hash"] or
        (job["match"] or {}).get("jd_hash")!=row["jd_hash"]):
        raise ValueError("Input version changed")
    if profile is not None and profile["sha256"]!=row["cv_hash"]:raise ValueError("Profile version changed")
    return job

def production_adapter(job,profile):
    from material_model import plan_cv
    from resume_template import render
    selected,audit=plan_cv(job,profile)
    pdf,bullets,docx,metadata=render(profile,selected,with_source=True)
    return pdf,bullets,docx,{**metadata,"model_requested":audit.get("model_requested"),"generator":"CV-only evidence plan"}

def validate_artifact(artifact,profile,row):
    from pypdf import PdfReader
    from zipfile import ZipFile
    import re
    pdf,bullets,docx,metadata=artifact
    if len(PdfReader(io.BytesIO(pdf)).pages)!=1:raise ValueError("Expected one-page CV")
    with ZipFile(io.BytesIO(docx)) as z:
        if "word/document.xml" not in z.namelist():raise ValueError("Missing editable CV")
    if metadata.get("template_sha256")!=row["template_hash"]:raise ValueError("Template metadata changed")
    evidence={f["id"]:f["text"] for f in profile["facts"] if f["role"]}
    if len(bullets)!=len(evidence) or {b["id"] for b in bullets}!=set(evidence):raise ValueError("Incomplete evidence mapping")
    for b in bullets:
        if set(re.findall(r"\d+(?:[.,]\d+)*",b["text"]))-set(re.findall(r"\d+(?:[.,]\d+)*",evidence[b["id"]])):
            raise ValueError("Unsupported numeric claim")
    return pdf,bullets,docx,metadata

def existing_document(c,row):
    for doc in c.execute("""SELECT d.id,a.metadata FROM documents d JOIN document_assets a ON a.document=d.id
        WHERE d.job=? AND d.kind='CV' AND d.source_hash=? AND d.jd_hash=? ORDER BY d.rowid DESC""",(row["job"],row["cv_hash"],row["jd_hash"])):
        if json.loads(doc["metadata"]).get("template_sha256")==row["template_hash"]:return doc["id"]
    return None

def consume(store,*,adapter=None,test_mode=False):
    fixture=test_mode and runtime_config.fixture_mode() and adapter is not None
    if (test_mode or adapter is not None) and not fixture:raise ValueError("Injected adapters require explicit fixture mode")
    if not fixture and not runtime_config.worker_status()["enabled"]:return []
    status=cv_queue.reconcile(store)
    if status["state"] in {"disabled","blocked"}:return []
    outcomes=[]
    for _ in range(20):
        if not fixture and not runtime_config.worker_status()["enabled"]:break
        row=claim(store)
        if row is None:break
        try:
            import matching
            profile=matching.candidate()
            job=checked_job(store,row,profile)
            with store.connect() as c:existing=existing_document(c,row)
            artifact=None if existing else validate_artifact((adapter or production_adapter)(job,profile),profile,row)
            if not fixture and not runtime_config.worker_status()["enabled"]:raise ValueError("Authorization changed")
            with store.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                attempt=c.execute("SELECT state FROM cv_queue_attempts WHERE token=?",(row["token"],)).fetchone()
                state=c.execute("SELECT state FROM cv_queue WHERE key=?",(row["key"],)).fetchone()
                if not attempt or attempt["state"]!="running" or not state or state["state"]!="generating":
                    raise ValueError("Claim no longer owned")
                checked_job(store,row,profile)
                doc=existing_document(c,row)
                if not doc:
                    pdf,bullets,docx,metadata=artifact
                    doc=uuid.uuid4().hex
                    mapping=[{"text":b["text"],"facts":[b["id"]]} for b in bullets]
                    c.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)",(doc,row["job"],stamp(),"CV",row["cv_hash"],json.dumps(mapping),pdf,row["jd_hash"]))
                    metadata={**metadata,"queue_key":row["key"],"queue_policy":cv_queue.POLICY,"created":stamp(),"pdf_sha256":hashlib.sha256(pdf).hexdigest(),"fixture":fixture}
                    c.execute("INSERT INTO document_assets VALUES(?,?,?)",(doc,docx,json.dumps(metadata)))
                    store.event(c,row["job"],"CV generated",doc)
                c.execute("UPDATE cv_queue SET state='ready',document=?,reason='Current CV version available for human review',updated=? WHERE key=?",(doc,stamp(),row["key"]))
                c.execute("UPDATE cv_queue_attempts SET state='completed',finished=? WHERE token=?",(stamp(),row["token"]))
            outcomes.append("ready")
        except Exception as error:
            # Never persist provider responses, private text, exception messages or credentials.
            with store.connect() as c:
                c.execute("UPDATE cv_queue_attempts SET state='failed',finished=?,error=? WHERE token=? AND state='running'",(stamp(),type(error).__name__,row["token"]))
                c.execute("UPDATE cv_queue SET state='failed',reason=?,updated=? WHERE key=? AND state='generating'",(type(error).__name__,stamp(),row["key"]))
            outcomes.append("failed")
    return outcomes

def loop(store):
    while True:
        try:
            enabled=runtime_config.worker_status()["enabled"]
            HEALTH.update(state="checking" if enabled else "model_disabled",last_check=stamp(),error=None)
            if enabled:
                outcomes=consume(store)
                HEALTH.update(state="idle" if not outcomes else "completed" if "failed" not in outcomes else "failed")
        except Exception as error:
            HEALTH.update(state="failed",error=type(error).__name__,last_check=stamp())
        time.sleep(30)
