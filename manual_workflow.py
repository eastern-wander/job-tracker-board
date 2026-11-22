"""Local drafting and recording. This module has no submission integration."""
import datetime as dt
import io
import json
import uuid
from html import escape

from auto_apply import prior_application
from core import now, stamp
from industry import classify, require_allowed
from matching import MATERIAL_EXECUTION, analyze, candidate, make_document, persist_match


def job_row(store, job_id):
    job = next((job for job in store.jobs() if job["id"] == job_id), None)
    if not job:
        raise ValueError("Job not found.")
    return job


def prepare(store, data):
    jd = data.get("jd", "")
    if not isinstance(jd, str) or not jd.strip() or len(jd) > 100000 or data.get("complete") is not True:
        raise ValueError("Paste the complete JD and confirm it is complete.")
    jd = jd.strip()
    job_id = data.get("id")
    checks = None
    if not job_id:
        item = {key: data.get(key, "") for key in ("title", "company", "location", "country", "url", "apply_url", "requisition",
                                                    "source", "industry_declared")}
        item["country"] = item["country"] or "Unverified"
        item.update(jd=jd, allow_similar=data.get("allow_similar") is True)
        result = store.ingest(item, new_only=True, manual_import=True)
        if result["result"] != "added":
            return result
        job_id = result["id"]
    else:
        job = job_row(store, job_id)
        if job["jd"] == jd:
            checks = (job["match"] or {}).get("checks")
        if classify({**job, "jd": jd})["state"] == "excluded":
            raise ValueError("The supplied JD is excluded by the industry policy.")
        with store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            previous = c.execute("SELECT jd FROM snapshots WHERE job=? ORDER BY rowid DESC LIMIT 1", (job_id,)).fetchone()
            if not previous or previous[0] != jd:
                c.execute("INSERT INTO snapshots VALUES(?,?,?)", (job_id, stamp(), jd))
                c.execute("UPDATE jobs SET match=NULL WHERE id=?", (job_id,))
                store.event(c, job_id, "JD updated", "Complete JD supplied manually")
    job = job_row(store, job_id)
    result = {"id": job_id, "result": "saved", "industry": job["industry"]}
    if job["industry"]["state"] == "allowed":
        match = analyze(job, candidate(), checks)
        persist_match(store, job, match, advance=False)
        result["match"] = match
    return result


def _generate(store, job_id, *, regenerate=False, use_model=False):
    job = job_row(store, job_id)
    require_allowed(job)
    profile = candidate()
    match = analyze(job, profile, (job["match"] or {}).get("checks"))
    if match["score"] is None:
        raise ValueError("A complete JD is required.")
    persist_match(store, job, match, advance=False)
    job["match"] = match
    cv_early = None
    def progress(step):
        with store.connect() as c: store.event(c,job_id,'Generation stage',step)
    if use_model:
        from material_model import plan
        progress('模型选材与CV文字生成')
        def save_cv(selection):
            nonlocal cv_early
            progress('CV原模板导出与保存')
            cv_early=make_document(store,job,'CV',manual=True,regenerate=True,model_plan=selection)
            progress('CV已保存；CL独立事实审核与修订')
        selected, audit = plan(job, profile, on_cv=save_cv)
    else:
        selected, audit = None, MATERIAL_EXECUTION
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        materials = {'CV': cv_early or make_document(store, job, 'CV', manual=True,
                         regenerate=regenerate or use_model, model_plan=selected, connection=c)}
        if selected and selected.get('cl_review'):
            from cl_workflow import save_reviewed
            materials['CL'] = save_reviewed(store, job, profile, selected, materials['CV'], c)
        else:
            materials['CL'] = make_document(store, job, 'CL', manual=True,
                             regenerate=regenerate or use_model, model_plan=selected, connection=c)
        if selected and selected.get("resume_bullets"):
            pdf = c.execute("SELECT pdf FROM documents WHERE id=?", (materials["CV"],)).fetchone()[0]
            tailored = analyze(job, candidate(pdf), match["checks"])
            before = {e["keyword"] for p in match["parts"] for e in p["evidence"] if e.get("cv")}
            after = {e["keyword"] for p in tailored["parts"] for e in p["evidence"] if e.get("cv")}
            assessment = {
                "cv_id": materials["CV"], "main_score": match["score"], "score": tailored["score"],
                "jd_hash": match["jd_hash"], "main_cv_hash": match["source_hash"],
                "added_evidence": sorted(after - before), "lost_evidence": sorted(before - after),
                "gaps": tailored["gaps"], "parts": tailored["parts"],
            }
            store.event(c, job_id, "Tailored CV fit", json.dumps(assessment))
        from core import hashlib
        cl_meta = c.execute("SELECT metadata FROM document_assets WHERE document=?", (materials['CL'],)).fetchone()
        if cl_meta:
            meta = json.loads(cl_meta[0])
            meta.update(paired_cv=materials['CV'], renderer='ReportLab')
            c.execute("UPDATE document_assets SET metadata=? WHERE document=?", (json.dumps(meta),materials['CL']))
        store.event(c, job_id, "Material generation runtime", json.dumps({**audit, "versions": materials}))
    return materials



def generate(store, job_id, *, regenerate=False, use_model=False, claimed=False):
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        job_row(store, job_id)
        previous = c.execute("SELECT * FROM generation_jobs WHERE job=?", (job_id,)).fetchone()
        if not claimed and previous and previous["state"] == "running" and (now() - dt.datetime.fromisoformat(previous["started"])).total_seconds() < 900:
            raise ValueError("材料仍在生成，请等待本次任务完成。")
        c.execute("INSERT OR REPLACE INTO generation_jobs VALUES(?,'running',?,NULL,'')", (job_id, stamp()))
    try:
        result = _generate(store, job_id, regenerate=regenerate, use_model=use_model)
    except Exception as error:
        with store.connect() as c:
            store.event(c, job_id, "Material generation failed", str(error)[:1500])
            c.execute("UPDATE generation_jobs SET state='failed',finished=?,error=? WHERE job=?",
                      (stamp(), str(error)[:1500], job_id))
        raise
    with store.connect() as c:
        c.execute("UPDATE generation_jobs SET state='completed',finished=? WHERE job=?", (stamp(), job_id))
    return result

def document_text(store, doc_id):
    from pypdf import PdfReader
    with store.connect() as c:
        row = c.execute("SELECT id,job,kind,pdf FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise ValueError("Material version not found.")
    with store.connect() as c:
        asset = c.execute("SELECT metadata FROM document_assets WHERE document=?", (doc_id,)).fetchone()
    meta = json.loads(asset[0]) if asset else {}
    return {"id": row["id"], "job": row["job"], "kind": row["kind"], "metadata": meta,
            "body": meta.get('cl_review', {}).get('body'), "text": "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(row["pdf"])).pages).strip()}


def edit_document(store, doc_id, body):
    from pypdf import PdfReader
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    if not isinstance(body, str) or not body.strip() or len(body) > 12000:
        raise ValueError("Enter nonempty material text, up to 12,000 characters.")
    original_text = document_text(store, doc_id)
    if original_text["kind"] == "CV":
        if body.strip() != original_text["text"].strip():
            raise ValueError("CV必须在原模板的要点中编辑，请按岗位重新生成，避免破坏版式。")
        new_id = uuid.uuid4().hex
        with store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            c.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)",
                      (new_id, old["job"], stamp(), old["kind"], old["source_hash"], old["mapping"], old["pdf"], old["jd_hash"]))
            asset = c.execute("SELECT * FROM document_assets WHERE document=?", (doc_id,)).fetchone()
            if asset:
                c.execute("INSERT INTO document_assets VALUES(?,?,?)", (new_id, asset["docx"], asset["metadata"]))
            store.event(c, old["job"], "Material edited", json.dumps({"version": new_id, "parent": doc_id, "kind": "CV"}))
        return {"id": new_id, "job": old["job"]}
    output = io.BytesIO()
    style = ParagraphStyle("edited", fontName="Helvetica", fontSize=10, leading=13, spaceAfter=4)
    SimpleDocTemplate(output, leftMargin=43, rightMargin=43, topMargin=35, bottomMargin=35).build(
        [Paragraph(escape(line.strip()) or "&#160;", style) for line in body.splitlines()])
    pdf = output.getvalue()
    if original_text.get('body'):
        from cl_workflow import render_letter
        paragraphs=[{'text':text.strip()} for text in body.split('\n\n') if text.strip()]
        pdf=render_letter(candidate(),job_row(store,original_text['job']),paragraphs,
                          original_text['metadata']['cl_review'].get('language','en'))
    if len(PdfReader(io.BytesIO(pdf)).pages) != 1:
        raise ValueError("Edited text must fit on one page.")
    new_id = uuid.uuid4().hex
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        old = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not old:
            raise ValueError("Material version not found.")
        c.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)",
                  (new_id, old["job"], stamp(), old["kind"], old["source_hash"], "[]", pdf, old["jd_hash"]))
        from cl_workflow import validate_metric, POLICY_VERSION
        validate_metric(body)
        asset = c.execute("SELECT metadata FROM document_assets WHERE document=?", (doc_id,)).fetchone()
        meta = json.loads(asset[0]) if asset else {'template': POLICY_VERSION}
        review = meta.get('cl_review', {})
        review.update(status='草稿／待核实', body=body.strip(), translation_zh=[],
                      unverified=['手动修改后的内容与中文对照需要重新审核'], checks={}, manually_edited=True)
        meta.update(cl_review=review, parent=doc_id, created=stamp(), pdf_sha256=__import__('hashlib').sha256(pdf).hexdigest())
        c.execute("INSERT INTO document_assets VALUES(?,NULL,?)", (new_id, json.dumps(meta)))
        store.event(c, old["job"], "Material edited", json.dumps({"version": new_id, "parent": doc_id, "kind": old["kind"]}))
    return {"id": new_id, "job": old["job"]}


def record_application(store, job_id, data):
    date, channel, receipt = (data.get(field, "") for field in ("date", "channel", "receipt"))
    if data.get("confirmed") is not True or not all(isinstance(v, str) for v in (date, channel, receipt)):
        raise ValueError("Confirm that you submitted this application yourself.")
    if not channel.strip() or len(channel) > 200 or len(receipt) > 2000 or dt.date.fromisoformat(date) > now().date():
        raise ValueError("Provide a valid submission date, channel and optional reference.")
    versions = {kind: data.get(kind.lower()) for kind in ("CV", "CL")}
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        job = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise ValueError("Job not found.")
        for kind, doc_id in versions.items():
            if not isinstance(doc_id, str) or not c.execute(
                    "SELECT 1 FROM documents WHERE id=? AND job=? AND kind=?", (doc_id, job_id, kind)).fetchone():
                raise ValueError("Select the exact CV and cover-letter versions used.")
        sources = [row[0] for row in c.execute("SELECT DISTINCT platform FROM sources WHERE job=? ORDER BY platform", (job_id,))]
        record = dict(date=date, channel=channel.strip(), receipt=receipt.strip(), submitted_at=stamp(), notes=str(data.get("notes") or "")[:3000], **versions)
        payload = json.dumps(dict(record, discovery_sources=sources), sort_keys=True)
        existing = c.execute("SELECT detail FROM events WHERE job=? AND kind='Manually Applied' ORDER BY rowid DESC LIMIT 1", (job_id,)).fetchone()
        current_record = c.execute("SELECT active FROM application_records WHERE job=?", (job_id,)).fetchone()
        if existing and (not current_record or current_record["active"]) and all(json.loads(existing[0]).get(key) == value for key, value in record.items() if key not in {"submitted_at", "notes"}):
            return {"result": "already recorded"}
        if prior_application(c, dict(job)):
            raise ValueError("This vacancy already has a confirmed or unresolved application record.")
        c.execute("UPDATE jobs SET status='Manually Applied' WHERE id=?", (job_id,))
        c.execute("INSERT OR REPLACE INTO application_records VALUES(?,?,?,?,?,?,?,?,1)",
                  (job_id, date, record["submitted_at"], channel.strip(), versions["CV"], versions["CL"], receipt.strip(), record["notes"]))
        store.event(c, job_id, "Manually Applied", payload)
        if receipt.strip():
            store.event(c, job_id, "Manual submission receipt", receipt.strip())
    return {"result": "recorded"}



def check_official_destination(url):
    import subprocess
    from urllib.parse import urljoin, urlsplit

    host = urlsplit(url).hostname
    if host not in {"job-boards.greenhouse.io", "job-boards.eu.greenhouse.io", "boards.greenhouse.io",
                    "jobs.lever.co", "jobs.eu.lever.co", "jobs.ashbyhq.com"}:
        return
    # Do not follow redirects or probe arbitrary user-supplied hosts.
    try:
        probe = subprocess.run(["/usr/bin/curl", "--silent", "--max-time", "8", "--proto", "=https",
                                "--head", "--output", "/dev/null", "--write-out", "%{http_code} %{redirect_url}", url],
                               capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return
    status, _, redirect = probe.stdout.strip().partition(" ")
    if status in {"404", "410"}:
        raise ValueError("The official application page is no longer available.")
    if redirect and status.startswith("3"):
        path = urlsplit(urljoin(url, redirect)).path.strip("/").split("/")
        if len(path) < 2 or path[-1].lower() in {"careers", "jobs", "open-positions"}:
            raise ValueError("The official link redirects to a general careers page.")



def official_application(store, job_id):
    """Look up the exact posting on its official feed before handing off to the browser."""
    from discovery import collect, expanded_settings
    from opportunity_queues import record_observation

    job = job_row(store, job_id)
    if job["vacancy"] == "Closed":
        raise ValueError("This vacancy is closed.")
    require_allowed(job)
    fields = {"Greenhouse": "boards", "Lever": "lever_boards", "Ashby": "ashby_boards"}
    settings = expanded_settings(store.settings())
    checked = False
    for source in job["source_links"]:
        platform = source["platform"]
        if platform not in fields or ":" not in (source["external_id"] or ""):
            continue
        token = source["external_id"].split(":", 1)[0]
        field = fields[platform]
        if token not in {item.strip() for item in settings[field].split(",")}:
            continue
        health = {}
        rows = collect({key: token if key == field else "" for key in fields.values()}, health, verification=True)
        checked |= any(item["state"] in {"Retrieved", "Empty"} and not item["invalid"] for item in health.values())
        if source["url"]:
            for result in health.values():
                if result["state"] == "Failed":
                    record_observation(store, job_id, {"url": source["url"], "state": "Request failed",
                        "detail": result.get("error") or "Official feed request failed."}, now())
        found = next((row for row in rows if row["external_id"] == source["external_id"]), None)
        if found:
            try:
                check_official_destination(found["apply_url"])
            except ValueError as error:
                if source["url"]:
                    record_observation(store, job_id, {"url": source["url"], "detail": str(error),
                        "state": "Redirected" if "redirects" in str(error) else "Request failed"}, now())
                store.update(job_id, {"vacancy": "Unverified"})
                raise
            with store.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                if c.execute("SELECT vacancy FROM jobs WHERE id=?", (job_id,)).fetchone()[0] == "Closed":
                    raise ValueError("This vacancy is closed.")
                store.event(c, job_id, "Official application opened", found["apply_url"])
            return {"url": found["apply_url"]}
    if checked:
        store.update(job_id, {"vacancy": "Unverified"})
        raise ValueError("The posting is no longer listed on its official feed. The link may be closed or lead to a careers homepage.")
    raise ValueError("An official vacancy link could not be verified. Check the original source or supply the employer posting.")


def confirm_receipt(store, job_id, receipt):
    if not isinstance(receipt, str) or not receipt.strip() or len(receipt) > 2000:
        raise ValueError("Enter an application number or matching confirmation reference.")
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        if not c.execute("SELECT 1 FROM events WHERE job=? AND kind='Manually Applied'", (job_id,)).fetchone():
            raise ValueError("Record the manual submission first.")
        c.execute("UPDATE application_records SET receipt=? WHERE job=? AND active=1", (receipt.strip(), job_id))
        existing = c.execute("SELECT detail FROM events WHERE job=? AND kind='Manual submission receipt' ORDER BY rowid DESC LIMIT 1",
                             (job_id,)).fetchone()
        if not existing or existing[0] != receipt.strip():
            store.event(c, job_id, "Manual submission receipt", receipt.strip())
    return {"result": "confirmed"}


def daily_submissions(c, day):
    from collections import Counter

    records = [dict(row) for row in c.execute("SELECT * FROM application_records")]
    seen = {row["job"] for row in records}
    channels, sources = Counter(), Counter()
    for row in records:
        if row["active"] and row["date"] == day:
            channels[row["channel"]] += 1
            sources.update(link[0] for link in c.execute("SELECT DISTINCT platform FROM sources WHERE job=?", (row["job"],)))
    for event in c.execute("SELECT job,kind,created,detail FROM events WHERE kind IN ('Submitted','Manually Applied') ORDER BY rowid"):
        job_id = event["job"]
        if job_id in seen:
            continue
        seen.add(job_id)
        if event["kind"] == "Manually Applied":
            data = json.loads(event["detail"])
            if data.get("date") != day:
                continue
            channel = data.get("channel", "Unspecified")
            discovery_sources = data.get("discovery_sources")
        else:
            if not event["created"].startswith(day):
                continue
            attempt = c.execute("SELECT platform FROM apply_attempts WHERE job=? AND state='confirmed' ORDER BY id DESC LIMIT 1",
                                (job_id,)).fetchone()
            channel = attempt[0] if attempt else "Other / unknown"
            discovery_sources = None
        channels[channel] += 1
        if discovery_sources is None:
            discovery_sources = [row[0] for row in c.execute("SELECT DISTINCT platform FROM sources WHERE job=?", (job_id,))]
        sources.update(discovery_sources)
    return {"unique": sum(channels.values()), "channels": dict(channels), "sources": dict(sources)}


def correct_application(store, job_id, data):
    reason = data.get("reason", "")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError("请填写更正原因。")
    job = job_row(store, job_id)
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        record = c.execute("SELECT * FROM application_records WHERE job=?", (job_id,)).fetchone()
        if not record:
            legacy = next((json.loads(e["detail"]) for e in job["events"] if e["kind"] == "Manually Applied"), None)
            if not legacy:
                raise ValueError("该岗位没有可更正的手动投递记录。")
            c.execute("INSERT INTO application_records VALUES(?,?,?,?,?,?,?,?,1)", (job_id, legacy["date"],
                      legacy.get("submitted_at") or stamp(), legacy["channel"], legacy["CV"], legacy["CL"],
                      legacy.get("receipt", ""), legacy.get("notes", "")))
            record = c.execute("SELECT * FROM application_records WHERE job=?", (job_id,)).fetchone()
        if data.get("cancel") is True:
            c.execute("UPDATE application_records SET active=0 WHERE job=?", (job_id,))
            c.execute("UPDATE jobs SET status='Pending Review' WHERE id=?", (job_id,))
        else:
            date, channel = data.get("date", record["date"]), data.get("channel", record["channel"])
            if not isinstance(date, str) or dt.date.fromisoformat(date) > now().date() or not isinstance(channel, str) or not channel.strip() or len(channel) > 200:
                raise ValueError("请填写有效的投递日期和渠道。")
            c.execute("UPDATE application_records SET date=?,channel=?,notes=? WHERE job=?",
                      (date, channel.strip(), str(data.get("notes", record["notes"]))[:3000], job_id))
        store.event(c, job_id, "Manual submission corrected", json.dumps({"before": dict(record),
                    "cancel": data.get("cancel") is True, "reason": reason.strip(), "date": data.get("date"),
                    "channel": data.get("channel")}))
    return {"saved": True}


def start_generation(store, job_id, *, regenerate=False, use_model=True):
    import threading
    job_row(store,job_id)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        prior=c.execute('SELECT * FROM generation_jobs WHERE job=?',(job_id,)).fetchone()
        if prior and prior['state']=='running': return {'accepted':True,'existing':True}
        c.execute("INSERT OR REPLACE INTO generation_jobs VALUES(?,'running',?,NULL,'')",(job_id,stamp()))
        store.event(c,job_id,'Generation stage','后台已接收，等待模型选材')
    def worker():
        try: generate(store,job_id,regenerate=regenerate,use_model=use_model,claimed=True)
        except Exception: pass # generate persists the concrete failure for polling/retry
    threading.Thread(target=worker,daemon=True).start()
    return {'accepted':True}
