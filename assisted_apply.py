"""Local handoff, per-vacancy review and evidence ledger. Never calls an ATS submit endpoint."""
import datetime as dt
import hashlib
import json
import re
from urllib.parse import quote, urlsplit

from auto_apply import prior_application
from core import TARGET_MARKETS, canonical, norm, now, stamp, within_discovery_window
from manual_workflow import job_row
from sponsorship import evidence as sponsorship_evidence
from workflow import application_day, current_documents

MODE = "assisted_apply_mode"
PROFILE = "assisted_application_profile"
NOTICE = "将在我的已登录浏览器中填写真实申请，最终提交前由我确认"
BASE = ("name", "email", "phone", "city", "address", "postal", "education", "gender", "ethnicity")
COUNTRY = ("work_authorization", "sponsorship", "salary", "available", "locations")
FINAL = {"Submitted", "Manually Applied", "Interview", "Offer", "Rejected", "Closed", "Duplicate",
         "Withdrawn", "Not Interested"}
HOSTS = {
    "Greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io"),
    "Lever": ("jobs.lever.co", "jobs.eu.lever.co"),
    "Ashby": ("jobs.ashbyhq.com",),
    "Workday": ("myworkdayjobs.com",),
    "SmartRecruiters": ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"),
}


def setting(c, key, default):
    row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def write_setting(c, key, value):
    c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))


def mode(store, data):
    value = data.get("mode")
    if value not in {"Dry Run", "Assisted Apply"} or (value == "Assisted Apply" and data.get("ack") is not True):
        raise ValueError("Confirm the Assisted Apply browser notice.")
    with store.connect() as c:
        write_setting(c, MODE, value)
        store.event(c, None, "Application mode changed", value)
    return {"mode": value}


def clean(data, fields):
    if not isinstance(data, dict) or set(data) - set(fields):
        raise ValueError("The application profile contains an unknown field.")
    if any(not isinstance(v, str) or len(v) > 1500 for v in data.values()):
        raise ValueError("Application profile fields must be text and no longer than 1,500 characters.")
    return {key: value.strip() for key, value in data.items()}


def profile(store, data=None):
    with store.connect() as c:
        if data is None:
            saved = setting(c, PROFILE, None)
            if saved is not None:
                return saved
            # Offer a draft from previously confirmed settings. Queue evaluation only
            # uses the new profile once the user reviews and saves it.
            legacy = setting(c, "confirmed_screening_answers", {})
            old = setting(c, "application_profile", {})
            answers = old.get("answers", {}) if old.get("confirmed") else {}
            reusable = legacy.get("reusable", {})
            identity = {k: answers[k] for k in ("name", "email", "phone") if answers.get(k)}
            if reusable.get("current_city"):
                identity["city"] = reusable["current_city"]
            countries = {}
            for country, facts in legacy.get("country", {}).items():
                countries[country] = {
                    target: "Yes" if facts[source] else "No"
                    for source, target in (("legal_work_authorization", "work_authorization"),
                                           ("needs_employer_sponsorship", "sponsorship"))
                    if isinstance(facts.get(source), bool)
                }
            return {"identity": identity, "countries": countries, "draft": True}
        country = data.get("country")
        if country not in TARGET_MARKETS or data.get("confirmed") is not True:
            raise ValueError("Choose the country and confirm the information is accurate.")
        base = clean(data.get("identity", {}), BASE)
        answers = clean(data.get("answers", {}), COUNTRY)
        if any(answers.get(k, "") not in {"", "Yes", "No"} for k in ("work_authorization", "sponsorship")):
            raise ValueError("Choose Yes, No, or Unverified.")
        if answers.get("available"):
            dt.date.fromisoformat(answers["available"])
        if base.get("email") and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", base["email"]):
            raise ValueError("Enter a valid email address.")
        c.execute("BEGIN IMMEDIATE")
        result = setting(c, PROFILE, {"identity": {}, "countries": {}})
        result["identity"].update(base)
        result["countries"].setdefault(country, {}).update(answers)
        write_setting(c, PROFILE, result)
        store.event(c, None, "Application profile updated", country)
        return result


def route(job):
    url = job.get("apply_url") or job.get("url") or ""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or not host:
            return "", "", "Missing URL"
    except ValueError:
        return "", "", "Missing URL"
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return url, "LinkedIn", "Platform review"
    if re.fullmatch(r"(?:[a-z0-9-]+\.)*indeed\.(?:com|ca|ae|co\.uk|co\.jp)", host):
        return url, "Indeed", "Platform review"
    for ats, hosts in HOSTS.items():
        if host in hosts or (ats == "Workday" and host.endswith(".myworkdayjobs.com")):
            return url, ats, "ATS review"
    return url, "Employer website", "Manual application required"


def read_attempt(c, ident):
    row = c.execute("SELECT * FROM assisted_attempts WHERE job=?", (ident,)).fetchone()
    return {**dict(row), "payload": json.loads(row["payload"])} if row else {}


def blockers(job, saved, attempt, *, duplicate=False):
    url, _, kind = route(job)
    jd = job.get("jd") or ""
    match = job.get("match") or {}
    generation = job.get("generation") or {}
    reasons = []
    p = saved.get("countries", {}).get(job["country"], {})
    identity = saved.get("identity", {})
    checks = match.get("checks") or {}
    if job["status"] == "Submission Confirmation Unknown" or attempt.get("stage") in {"Submission unverified", "Submitted"}:
        reasons.append("Submission outcome is unverified. Do not reapply.")
    elif duplicate or job["status"] in FINAL:
        reasons.append("An application or duplicate listing already exists. Do not reapply.")
    if job["vacancy"] == "Closed":
        reasons.append("The job is closed.")
    if not jd.strip() or jd.startswith("[Partial JD]"):
        reasons.append("The full job description is missing.")
    if not url:
        reasons.append("A valid application link is missing.")
    elif kind == "Manual application required":
        reasons.append("Apply manually on the employer’s website.")
    if job["industry"]["state"] != "allowed":
        reasons.append("The industry is excluded or unverified.")
    if not job.get("location") or job["country"] not in TARGET_MARKETS:
        reasons.append("The job location is unverified.")
    elif p.get("locations"):
        wanted = [norm(part) for part in p["locations"].split(",") if norm(part)]
        if wanted and not any(term in norm(job["location"]) for term in wanted):
            reasons.append("The job location does not match the confirmed preferences.")
    if p.get("work_authorization") not in {"Yes", "No"}:
        reasons.append("Work authorization is unknown.")
    if p.get("sponsorship") not in {"Yes", "No"}:
        reasons.append("Employer sponsorship need is unknown.")
    if sponsorship_evidence(jd, p.get("sponsorship") == "Yes")["excluded"]:
        reasons.append("The role explicitly does not offer the required sponsorship.")
    if p.get("work_authorization") == "No" and re.search(
        r"\bmust\s+(?:(?:already|currently)\s+)?(?:be\s+(?:(?:already|currently|legally)\s+)*(?:authorized|eligible)\s+to\s+work|have\s+(?:(?:existing|valid)\s+)?work\s+authori[sz]ation)",
        jd, re.I
    ):
        reasons.append("The job description explicitly requires existing work authorization.")
    for label, check in checks.items():
        if check.get("state") == "Failed":
            reasons.append(label + ": Does not meet a verified requirement.")
    if not all(identity.get(k) for k in ("name", "email", "phone")):
        reasons.append("The application profile is missing a name, email address, or phone number.")
    specific = attempt.get("payload", {}).get("precheck", {})
    if specific.get("salary_required") and not (specific.get("salary") or p.get("salary")):
        reasons.append("This job requires a salary answer")
    if specific.get("address_required") and not (specific.get("address_authorized") and identity.get("address") and identity.get("postal")):
        reasons.append("Address and postal code require job-specific authorization")
    if specific.get("captcha_required") and not specific.get("captcha_cleared"):
        reasons.append("Manual verification required; no bypass")
    if job["status"] == "Manual Action Required":
        reasons.append("The current record requires manual action.")
    if attempt.get("stage") == "Blocked":
        reasons.append(attempt["payload"].get("reason") or "A browser step was blocked.")
    if generation.get("state") == "failed":
        reasons.append("Material generation failed: " + generation.get("error", "")[:140])
    return list(dict.fromkeys(reasons))


def materials(job):
    match = job.get("match") or {}
    return {k: d["id"] for k, d in current_documents(job).items()
            if d and d.get("jd_hash") == match.get("jd_hash") and d.get("source_hash") == match.get("source_hash")}


def panel(store, jobs=None):
    jobs = store.jobs() if jobs is None else jobs
    clock = now()
    today = clock.date().isoformat()
    with store.connect() as c:
        config = setting(c, PROFILE, {"identity": {}, "countries": {}})
        current = setting(c, MODE, "Dry Run")
        historical = application_day(c, today)
        legacy_receipts = {r["job"] for r in historical["automatic"] + historical["manual"] if r["receipt"]}
        rows = []
        for job in jobs:
            attempt = read_attempt(c, job["id"])
            record = job.get("application_record") or {}
            confirmed = bool(record.get("active") and record.get("receipt")) or any(
                e["kind"] == "Manual submission receipt" and e["detail"].strip() for e in job["events"]
            ) and not (record and not record.get("active"))
            pending = job["status"] == "Submission Confirmation Unknown"
            if (job["status"] in FINAL or job["vacancy"] == "Closed") and not (attempt or confirmed or pending):
                continue
            score = (job.get("match") or {}).get("score")
            if score is None and not (pending or confirmed or attempt or job.get("manual_import")):
                continue
            url, channel, kind = route(job)
            docs = materials(job)
            reasons = [] if confirmed else blockers(job, config, attempt, duplicate=prior_application(c, job))
            stage = ("Receipt verified" if confirmed else
                     "Submission unverified" if pending and not attempt else
                     attempt.get("stage") or ("Blocked" if reasons else "Materials ready" if docs.get("CV") else
                                              "Reviewed" if score is not None else "Discovered"))
            rows.append(dict(id=job["id"], title=job["title"], company=job["company"], country=job["country"],
                             location=job["location"], score=score, url=url, channel=channel, route=kind,
                             stage=stage, blockers=reasons, documents=docs, attempt=attempt,
                             receipt=attempt.get("payload", {}).get("receipt") or record.get("receipt") or next(
                                 (e["detail"] for e in job["events"] if e["kind"] == "Manual submission receipt"), "") if confirmed else "",
                             fresh=within_discovery_window(job["original_posted_at"], clock),
                             queue_ready=not reasons and stage not in {"Assisted filling", "Awaiting my confirmation", "Receipt verified"},
                             search_mail="https://mail.google.com/mail/u/0/#search/" + quote(
                                 f'"{job["company"]}" "{job["title"]}" {{subject:application subject:received subject:thank}}', safe="")))
        backlog = [dict(r) for r in c.execute("SELECT url,reason,created,updated FROM intake_backlog ORDER BY updated DESC")]
    rows.sort(key=lambda r: (not r["fresh"], -(r["score"] or 0), not r["queue_ready"], r["title"]))
    verified = legacy_receipts | {r["id"] for r in rows if r["stage"] == "Receipt verified"
                                  and (r["attempt"].get("submitted") or "").startswith(today)}
    counts = dict(discovered=sum(j["first_seen"].startswith(today) for j in jobs),
                  actionable=sum(r["queue_ready"] for r in rows),
                  awaiting=sum(r["stage"] == "Awaiting my confirmation" for r in rows),
                  submitted=len(verified),
                  unverified=sum(r["stage"] in {"Submission unverified", "Submitted"} for r in rows),
                  blocked=sum(r["stage"] == "Blocked" for r in rows))
    return dict(mode=current, notice=NOTICE, today=today, counts=counts, jobs=rows, backlog=backlog)


def save_backlog(store, url, reason=None):
    try:
        key = canonical(url)
        if not key or urlsplit(key).scheme != "https":
            return
    except ValueError:
        return
    with store.connect() as c:
        if reason:
            time = stamp()
            c.execute("""INSERT INTO intake_backlog VALUES(?,?,?,?,?) ON CONFLICT(canonical)
                         DO UPDATE SET url=excluded.url, reason=excluded.reason, updated=excluded.updated""",
                      (key, url, reason[:1000], time, time))
        else:
            c.execute("DELETE FROM intake_backlog WHERE canonical=?", (key,))


def apply_action(store, data):
    ident, action = data.get("id"), data.get("action")
    job = job_row(store, ident)
    url, channel, kind = route(job)
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        attempt = read_attempt(c, ident)
        stage = attempt.get("stage", "")
        payload = attempt.get("payload", {})
        old_status = c.execute("SELECT status FROM jobs WHERE id=?", (ident,)).fetchone()[0]
        uncertain = old_status == "Submission Confirmation Unknown" or stage in {"Submitted", "Submission unverified"}
        if stage == "Receipt verified" or old_status in FINAL:
            raise ValueError("This job is closed or already applied to.")
        time = stamp()
        opened, submitted = attempt.get("opened"), attempt.get("submitted")
        if action == "open":
            if setting(c, MODE, "Dry Run") != "Assisted Apply":
                raise ValueError("Confirm switching to Assisted Apply first.")
            if uncertain or prior_application(c, job):
                raise ValueError("This job or a duplicate already has a submission or an unverified outcome.")
            saved = setting(c, PROFILE, {"identity": {}, "countries": {}})
            reasons = blockers(job, saved, attempt)
            if reasons:
                raise ValueError("；".join(reasons))
            docs = materials(job)
            if not docs.get("CV"):
                raise ValueError("Generate a tailored CV for this job first.")
            if data.get("reviewed") is not True:
                raise ValueError("Review the job, recipient, profile, and document versions first.")
            if stage in {"Assisted filling", "Awaiting my confirmation"}:
                raise ValueError("An application is already open. Use the original form.")
            reviewed_profile = {**saved.get("identity", {}), **saved.get("countries", {}).get(job["country"], {})}
            payload = dict(url=url, channel=channel, docs=docs, precheck=payload.get("precheck", {}), profile_hash=hashlib.sha256(
                json.dumps(reviewed_profile, sort_keys=True).encode()).hexdigest())
            stage, opened, submitted = "Assisted filling", time, None
        elif action == "review":
            if stage != "Assisted filling" or uncertain:
                raise ValueError("Open the application first.")
            review_profile = setting(c, PROFILE, {"identity": {}, "countries": {}})
            reviewed_profile = {**review_profile.get("identity", {}), **review_profile.get("countries", {}).get(job["country"], {})}
            revision = hashlib.sha256(json.dumps(reviewed_profile, sort_keys=True).encode()).hexdigest()
            if revision != payload.get("profile_hash") or payload.get("docs") != materials(job) or payload.get("url") != url:
                raise ValueError("The profile, documents, or application destination changed. Reopen and review the application.")
            if data.get("reviewed") is not True:
                raise ValueError("Review the completed fields and attachments in your browser before confirming.")
            used = data.get("docs", {})
            if not isinstance(used, dict) or used.get("CV") != payload["docs"].get("CV") or any(
                kind not in {"CV", "CL"} or payload["docs"].get(kind) != version for kind, version in used.items()
            ):
                raise ValueError("Choose the CV and optional cover letter used on the website.")
            payload["used_docs"] = used
            stage = "Awaiting my confirmation"
        elif action == "submitted":
            if stage != "Awaiting my confirmation" or uncertain or data.get("confirmed") is not True:
                raise ValueError("Record the submission only after confirming you clicked Submit on the website.")
            stage, submitted = "Submitted", time
            c.execute("UPDATE jobs SET status='Submission Confirmation Unknown' WHERE id=?", (ident,))
        elif action == "precheck":
            if uncertain or data.get("confirmed") is not True or stage in {"Assisted filling", "Awaiting my confirmation"}:
                raise ValueError("Confirm the job-specific information before opening the form.")
            salary = data.get("salary", "")
            if not isinstance(salary, str) or len(salary) > 120:
                raise ValueError("The salary response is invalid.")
            payload["precheck"] = dict(salary=salary.strip(), address_authorized=data.get("address_authorized") is True,
                                       captcha_cleared=data.get("captcha_cleared") is True)
            stage = "Reviewed"
        elif action == "blocked":
            if uncertain:
                raise ValueError("The submission outcome is unverified.")
            reason = str(data.get("reason") or "").strip()[:1000]
            if not reason:
                raise ValueError("Record the verification challenge, missing answer, or other blocker.")
            stage, payload = "Blocked", {**payload, "reason": reason}
        elif action == "resume":
            if uncertain or stage != "Blocked" or data.get("confirmed") is not True:
                raise ValueError("Resume only after confirming the blocker is resolved.")
            stage, payload = "Reviewed", {"precheck": payload.get("precheck", {})}
        elif action in {"receipt", "requeue"}:
            if not uncertain:
                raise ValueError("This action is only for applications with an unverified outcome.")
            proof = str(data.get("proof") or "").strip()[:2000]
            if len(proof) < 8 or data.get("confirmed") is not True:
                raise ValueError("Provide verification evidence and confirm.")
            payload = {**payload, "url": url, "channel": channel}
            if action == "requeue":
                if data.get("proof_kind") not in {"Platform rejected", "Employer confirmed no application", "Platform confirms no application"}:
                    raise ValueError("Evidence from the hiring system or employer that no submission occurred is missing.")
                if prior_application(c, job, reconciling=True):
                    raise ValueError("A platform receipt, retained lock, or duplicate application prevents unlocking.")
                stage = "Reviewed"
                payload["not_submitted_evidence"] = proof
                submitted = None
                c.execute("UPDATE jobs SET status='Eligibility Review' WHERE id=?", (ident,))
            else:
                proof_kind = data.get("proof_kind")
                if proof_kind not in {"Success page", "Application number", "Confirmation email"}:
                    raise ValueError("A successful submission requires a confirmation page, application number, or confirmation email.")
                # A resolved record can be old. Never attribute a historic attempt to today implicitly.
                submitted = submitted or data.get("submitted_at")
                try:
                    at = dt.datetime.fromisoformat(submitted)
                    if at.tzinfo is None or at > now():
                        raise ValueError()
                    from core import TZ
                    submitted = at.astimezone(TZ).isoformat()
                except (TypeError, ValueError):
                    raise ValueError("Enter a verifiable submission time with its time zone.") from None
                stage = "Receipt verified"
                payload.update(receipt=proof, receipt_kind=proof_kind)
                docs = payload.get("used_docs") or payload.get("docs") or {}
                if not docs:
                    for key in ("cv", "cl"):
                        version = data.get(key)
                        if version:
                            found = c.execute("SELECT 1 FROM documents WHERE id=? AND job=? AND kind=?",
                                              (version, ident, key.upper())).fetchone()
                            if not found:
                                raise ValueError("The document version does not belong to this job.")
                            docs[key.upper()] = version
                record = dict(date=submitted[:10], submitted_at=submitted,
                              channel=channel if channel in {"LinkedIn", "Indeed"} else "Employer website / ATS",
                              CV=docs.get("CV"), CL=docs.get("CL"), receipt=proof,
                              discovery_sources=[r["platform"] for r in job["source_links"]])
                c.execute("UPDATE jobs SET status='Manually Applied' WHERE id=?", (ident,))
                store.event(c, ident, "Manually Applied", json.dumps(record, ensure_ascii=False))
                store.event(c, ident, "Manual submission receipt", proof)
        else:
            raise ValueError("Unknown application action.")
        c.execute("""INSERT OR REPLACE INTO assisted_attempts VALUES(?,?,?,?,?,?)""",
                  (ident, stage, time, opened, submitted, json.dumps(payload, ensure_ascii=False)))
        store.event(c, ident, "Assisted Apply " + stage, json.dumps(payload, ensure_ascii=False))
        return dict(stage=stage, url=url, channel=channel, docs=payload.get("docs", {}))
