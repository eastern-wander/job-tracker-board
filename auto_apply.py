"""Dry-run policy; neither adapter has a live submission transport."""
import datetime as dt
import io
import json
import re
from urllib.parse import urlsplit

from core import alert_needs_review, canonical, norm, now, stamp, within_application_window
from industry import classify

LIMITS = {"LinkedIn": 20, "Indeed": 20}
COMBINED = 40


class LinkedInAdapter:
    verified = pilot_passed = False

    @staticmethod
    def owns(url):
        return (urlsplit(url or "").hostname or "") in {"linkedin.com", "www.linkedin.com"}


class IndeedAdapter:
    verified = pilot_passed = False

    @staticmethod
    def owns(url):
        return bool(re.fullmatch(r"(?:[a-z0-9-]+\.)*indeed\.(?:com|ca|ae|co\.uk)", urlsplit(url or "").hostname or ""))


ADAPTERS = {"LinkedIn": LinkedInAdapter(), "Indeed": IndeedAdapter()}


def live_allowed(adapter, authorized=False, mode="Dry Run"):
    return mode == "Live" and authorized is True and adapter.verified and adapter.pilot_passed


def tally(c, local):
    counters = {platform: {"confirmed": 0, "reserved": 0, "unknown": 0, "failed": 0, "manual": 0,
                           "limit": limit, "logs": []} for platform, limit in LIMITS.items()}
    today = local.date()
    for row in c.execute("SELECT platform,state,created,confirmed_at,detail FROM apply_attempts ORDER BY id DESC"):
        state = row["state"]
        instant = dt.datetime.fromisoformat(row["confirmed_at"] if state == "confirmed" else row["created"])
        current = instant.astimezone(local.tzinfo).date() == today
        bucket = counters[row["platform"]]
        if current or state in {"reserved","unknown"}:
            bucket[state] += 1
        if state in {"failed","manual","unknown"} and len(bucket["logs"]) < 10:
            bucket["logs"].append(dict(row))
    manual_jobs = set()
    for row in c.execute("""SELECT job,detail FROM events e WHERE kind='Manually Applied'
        AND NOT EXISTS (SELECT 1 FROM apply_attempts a WHERE a.job=e.job AND a.state='confirmed') ORDER BY rowid"""):
        if c.execute("SELECT 1 FROM application_records WHERE job=?", (row["job"],)).fetchone() or row["job"] in manual_jobs:
            continue
        manual_jobs.add(row["job"])
        record = json.loads(row["detail"])
        platform = record.get("channel")
        if platform in counters and record.get("date") == today.isoformat():
            counters[platform]["confirmed"] += 1
    for record in c.execute("SELECT job,date,channel FROM application_records WHERE active=1"):
        if record["date"] == today.isoformat() and record["channel"] in counters and not c.execute(
                "SELECT 1 FROM apply_attempts WHERE job=? AND state='confirmed'", (record["job"],)).fetchone():
            counters[record["channel"]]["confirmed"] += 1
    combined = {key: sum(x[key] for x in counters.values()) for key in ("confirmed","reserved","unknown","failed","manual")}
    combined["limit"] = COMBINED
    return {**counters, "Combined":combined}


def has_capacity(counters, platform):
    def used(row):
        return row["confirmed"] + row["reserved"] + row["unknown"]
    return platform in LIMITS and used(counters[platform]) < LIMITS[platform] and used(counters["Combined"]) < COMBINED


def reserve(store, job, platform, *, mode="Dry Run", authorized=False):
    """Reserve atomically before any future transport call; unresolved holds survive midnight."""
    adapter = ADAPTERS.get(platform)
    if not adapter or not live_allowed(adapter, authorized, mode):
        raise ValueError("Live authorization, verified integration and successful pilot are required.")
    from matching import candidate
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        current = next((row for row in store.jobs() if row["id"] == job), None)
        if not current or current["source"] != platform or not adapter.owns(current["apply_url"] or current["url"]):
            raise ValueError("Platform or application destination is unsupported.")
        local = now()
        reasons = requirements(c,current,candidate(),local)
        if reasons:
            raise ValueError(" ".join(reasons))
        if not has_capacity(tally(c,local),platform):
            raise ValueError("Daily application capacity exhausted.")
        return c.execute("INSERT INTO apply_attempts(job,platform,state,created,detail) VALUES(?,?,'reserved',?,?)",
                         (job,platform,stamp(),"Capacity reserved")).lastrowid


def identity(c, job):
    urls, ids = set(), set()
    for source in c.execute("SELECT platform,external_id,url FROM sources WHERE job=?", (job["id"],)):
        if source["external_id"]:
            ids.add((source["platform"].casefold(),source["external_id"]))
        if source["url"]:
            urls.add(source["url"])
    if job.get("apply_url"):
        urls.add(canonical(job["apply_url"]))
    return urls, ids


def prior_application(c, job, *, reconciling=False):
    urls, ids = identity(c, job)
    for row in c.execute("""SELECT * FROM jobs j WHERE j.status IN ('Submitted','Manually Applied','Interview','Offer','Submission Confirmation Unknown')
        OR EXISTS(SELECT 1 FROM events e WHERE e.job=j.id AND e.kind IN ('Submitted','Manually Applied'))
        OR EXISTS(SELECT 1 FROM apply_attempts a WHERE a.job=j.id AND a.state IN ('confirmed','reserved','unknown'))"""):
        corrected = c.execute("SELECT active FROM application_records WHERE job=?", (row["id"],)).fetchone()
        if corrected and not corrected[0] and not c.execute("SELECT 1 FROM apply_attempts WHERE job=? AND state IN ('confirmed','reserved','unknown')", (row["id"],)).fetchone():
            continue
        other = dict(row)
        if other["id"] == job["id"]:
            if reconciling and other["status"] == "Submission Confirmation Unknown" and not c.execute(
                    """SELECT 1 FROM events WHERE job=? AND kind IN ('Submitted','Manually Applied')
                       UNION ALL SELECT 1 FROM apply_attempts WHERE job=? AND state IN ('confirmed','reserved','unknown')""",
                    (job["id"], job["id"])).fetchone():
                continue
            return True
        a_urls, a_ids = identity(c, other)
        if urls & a_urls or ids & a_ids:
            return True
        if norm(job["company"]) != norm(other["company"]):
            continue
        req, other_req = norm(job.get("requisition") or ""), norm(other.get("requisition") or "")
        if req and other_req:
            if req == other_req:
                return True
        elif norm(job["title"]) == norm(other["title"]) and norm(job["location"]) == norm(other["location"]):
            return True
    return False


def application_blockers(job, today):
    match = job.get("match") or {}
    reasons = []
    if alert_needs_review(job):
        reasons.append("Verify the alert details and supply the full job description.")
    if classify(job)["state"] != "allowed":
        reasons.append("Industry is excluded or unverified.")
    if (match.get("score") or 0) < 80:
        reasons.append("Match score must be at least 80.")
    checks = match.get("checks") or {}
    from matching import EMPLOYER_RESTRICTIONS, SCREEN, SPONSORSHIP, WORK_AUTHORIZATION
    authorization_checks = {
        WORK_AUTHORIZATION: "Work authorization needs verified evidence.",
        SPONSORSHIP: "Visa sponsorship compatibility needs verified evidence.",
        EMPLOYER_RESTRICTIONS: "Employer-specific restrictions need verified evidence.",
    }
    for key, reason in authorization_checks.items():
        allowed = {"Met"} if key == WORK_AUTHORIZATION else {"Met", "Not required"}
        check = checks.get(key, {})
        if check.get("state") not in allowed or not check.get("reason", "").strip():
            reasons.append(reason)
    if match.get("eligibility") != "Verified" or any(
        checks.get(key, {}).get("state") not in {"Met","Not required"} or not checks.get(key, {}).get("reason","").strip()
        for key in SCREEN
    ):
        reasons.append("Mandatory eligibility is not fully verified.")
    if job["country"] == "Japan" and any(checks.get(key, {}).get("state") != "Met"
            or not checks[key].get("reason", "").strip() for key in ("Languages", "Location / relocation")):
        reasons.append("Japan: working language and location need verified evidence.")
    if job["vacancy"] != "Active":
        reasons.append("Active vacancy needs verification.")
    if not within_application_window(job.get("posted"), today):
        reasons.append("Verify an original posting date within 14 days.")
    return reasons


def requirements(c, job, profile, local):
    from pypdf import PdfReader
    match = job.get("match") or {}
    reasons = application_blockers(job, local.date())
    if job["country"] == "Japan":
        from sponsorship import evidence
        from workflow import japan_review
        saved = c.execute("SELECT value FROM settings WHERE key='japan_application_preferences'").fetchone()
        preferences = json.loads(saved[0]) if saved else {}
        reasons.extend(japan_review(job, preferences, evidence(job["jd"], preferences.get("requires_sponsorship") is True)))
    if prior_application(c,job):
        reasons.append("A previous or unresolved application exists for this vacancy.")
    doc = c.execute("""SELECT pdf,mapping FROM documents WHERE job=? AND kind='CV' AND mapping<>'[]' AND source_hash=?
        AND jd_hash=? ORDER BY rowid DESC LIMIT 1""", (job["id"], profile["sha256"], match.get("jd_hash"))).fetchone()
    valid = False
    if doc and match.get("source_hash") == profile["sha256"]:
        try:
            pages = PdfReader(io.BytesIO(doc["pdf"])).pages
            mapping = json.loads(doc["mapping"])
            facts = {f["id"] for f in profile["facts"]}
            valid = len(pages) == 1 and bool(pages[0].extract_text()) and bool(mapping) and all(
                line["facts"] and set(line["facts"]) <= facts for line in mapping)
        except Exception:
            pass
    if not valid:
        reasons.append("Current fact-checked one-page tailored CV is missing or invalid.")
    return reasons


def dry_run(store, jobs):
    from matching import candidate
    profile = candidate()
    local = now()
    output = []
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        counters = tally(c, local)
        for job in jobs:
            platform = job.get("source")
            adapter = ADAPTERS.get(platform)
            destination = job.get("apply_url") or job.get("url")
            reasons = requirements(c, job, profile, local)
            if adapter and not has_capacity(counters, platform):
                reasons.append("Platform or combined daily capacity is exhausted.")
            if reasons:
                output.append({"id":job["id"],"state":"Pending review","reasons":reasons})
                continue
            reason = ("Automatic submission is disabled for this platform." if not adapter else
                      "External ATS destination is not authorized." if not adapter.owns(destination) else
                      "Submission adapter is unverified; live mode and pilot are disabled.")
            current = c.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()[0]
            if current not in {"Discovered","Saved","CV Ready","Pending Review","Ready to Apply","Manual Action Required","Scored","Eligibility Review"}:
                output.append({"id":job["id"],"state":"Pending review","reasons":["Application status is not actionable."]})
                continue
            if current != "Manual Action Required":
                c.execute("UPDATE jobs SET status='Manual Action Required' WHERE id=?", (job["id"],))
                store.event(c, job["id"], "Manual Action Required", reason)
            if adapter and not c.execute("SELECT 1 FROM apply_attempts WHERE job=? AND platform=? AND state='manual' AND detail=?",
                                        (job["id"],platform,reason)).fetchone():
                c.execute("INSERT INTO apply_attempts(job,platform,state,created,detail) VALUES(?,?,'manual',?,?)",
                          (job["id"],platform,stamp(),reason))
            output.append({"id":job["id"],"state":"Manual Action Required","reasons":[reason]})
    return output
