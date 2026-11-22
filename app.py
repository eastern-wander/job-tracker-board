import argparse
import hashlib
import base64
import datetime as dt
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from core import ALERT_PLATFORMS, DEFAULT, MAIN, ROOT, STATES, Store, alert_needs_review, canonical, now, stamp, within_discovery_window
from matching import MATCH_EXECUTION, MATERIAL_EXECUTION, SCREEN, analyze, candidate, make_document, persist_match
from industry import classify, require_allowed
from discovery import LEVER_EMPLOYERS, TOKEN, collect, expanded_settings, location_priority
import email_alerts
import bulk_intake
import link_intake
import import_preview
import candidate_review
import workflow
import manual_workflow
import opportunity_queues
import rehearsal
import auto_apply
import assisted_apply
from run_diagnostics import load_cadence, FailureLog, successful
import runtime_config
import product_policy
import cv_queue

PORT = 8136
RUN_LOCK = threading.Lock()
SCHEDULER_HEALTH = {"state":"not_started", "last_check":None, "error":None}
FINISHED = {"Submitted", "Interview", "Offer", "Rejected", "Withdrawn", "Closed", "Not Interested", "Duplicate", "Application Failed", "Submission Confirmation Unknown", "Manually Applied"}


def assess(store, job, checks=None, profile=None):
    result = analyze(job, profile or candidate(), checks)
    persist_match(store, job, result)
    return {"match": result}


def batch_match(store):
    summary = dict(scored=0, high_fit=0, missing_jd=0, industry_review=0, excluded=0)
    profile = None
    for job in store.jobs():
        if job["status"] in FINISHED or job["vacancy"] == "Closed":
            continue
        industry = job["industry"]["state"]
        missing_jd = not job["jd"] or job["jd"].startswith("[Partial JD]")
        if industry == "excluded":
            summary["excluded"] += 1
            continue
        summary["missing_jd"] += missing_jd
        if industry == "review":
            summary["industry_review"] += 1
        elif not missing_jd:
            profile = profile or candidate()
            match = assess(store, job, (job["match"] or {}).get("checks"), profile)["match"]
            summary["scored"] += 1
            summary["high_fit"] += (match["score"] or 0) >= 80
    summary["cv_queue"] = cv_queue.reconcile(store)
    return {**summary, "execution": MATCH_EXECUTION}


def run_tasks(store, kind, email_batch=None, active_only=False, expanded=False, resume=False):
    if not RUN_LOCK.acquire(blocking=False):
        raise ValueError("A run is already in progress.")
    try:
        return execute_tasks(store, kind, email_batch, active_only, expanded, resume)
    finally:
        RUN_LOCK.release()


def execute_tasks(store, kind, email_batch=None, active_only=False, expanded=False, resume=False):
    ident = uuid.uuid4().hex
    result = {"added": 0, "duplicates": 0, "industry_excluded": 0, "review": [], "prepared": {}, "errors": [],
              "source_health": {}, "markets": {}, "qualified": {}, "matching_execution": MATCH_EXECUTION}
    with store.connect() as c:
        c.execute("INSERT INTO runs VALUES(?,?,?,?)", (ident, stamp(), kind, '{"running":true}'))
    try:
        settings = store.settings()
        clock = now()
        added_ids, seen_ids = set(), set()
        channels = {}
        def ingest(item, source, index):
            out = store.ingest(item)
            label = out["result"]
            if label in {"added", "duplicate"}:
                seen_ids.add(out["id"])
                channels.setdefault(item["source"], set()).add(out["id"])
            if label == "added":
                result["added"] += 1
                added_ids.add(out["id"])
                market = item.get("country") or "Unverified"
                result["markets"][market] = result["markets"].get(market, 0) + 1
            elif label == "duplicate":
                result["duplicates"] += 1
            elif label == "excluded":
                result["industry_excluded"] += 1
            else:
                result["review"].append({"file": source, "row": index, **out})
            return label

        search_settings = expanded_settings(settings) if expanded else settings
        if resume:
            search_settings = {**search_settings, "resume_queries": opportunity_queues.resume_queries()}
        board_jobs = collect(search_settings, result["source_health"])
        if resume:
            profile = candidate()
            board_jobs = [job for job in board_jobs if job["jd_quality"] == "Full"
                          and classify(job)["state"] == "allowed"
                          and (analyze(job, profile)["score"] or 0) >= 60]
        trusted = {canonical(item["url"]): item for item in board_jobs if item["jd_quality"] == "Full"}
        for index, item in enumerate(board_jobs if email_batch is None else [], 1):
            try:
                ingest(item, item["external_id"], index)
            except (ValueError, TypeError) as error:
                result["errors"].append(f"{item['external_id']}: {error}")
        for source, status in result["source_health"].items():
            if status["state"] == "Failed":
                result["errors"].append(f"{source}: {status['error']}")
        try:
            cfg = {} if active_only else email_alerts.load()
            if cfg.get("label"):
                mailbox, messages, errors = email_batch if email_batch is not None else email_alerts.scan(store)
                if cfg["mailbox"] != mailbox:
                    raise ValueError("Mailbox changed; preview again.")
                errors = list(errors)
                platforms = {
                    platform: dict(emails=0, jobs=0, duplicates=0, rejected=0,
                                   missing_dates=0, parsing_errors=0, intake_errors=0)
                    for platform in (*ALERT_PLATFORMS, "Unknown")
                }
                platforms["Unknown"]["intake_errors"] = len(errors)
                report = {"state": "No new alerts", "emails": 0, "jobs": 0, "unparsed": 0,
                          "last_sync": stamp(), "reauthorize": False, "platforms": platforms}
                with store.connect() as c:
                    processed = {r[0] for r in c.execute("SELECT message FROM email_processed WHERE mailbox=?", (mailbox,))}
                for key, jobs, parsed in messages:
                    if key in processed:
                        continue
                    counts = platforms[parsed["platform"]]
                    counts["emails"] += 1
                    counts["jobs"] += len(jobs)
                    counts["missing_dates"] += sum(not job.get("posted") for job in jobs)
                    for field in ("duplicates", "rejected", "parsing_errors"):
                        counts[field] += parsed[field]
                    report["emails"] += 1
                    report["jobs"] += len(jobs)
                    report["unparsed"] += not jobs
                    try:
                        for job in jobs:
                            official = trusted.get(canonical(job.get("apply_url")))
                            if official and all(job.get(field) for field in ("posted", "location")) and job["company"] != "Employer unverified":
                                job = {**job, **official, "source": job["source"], "external_id": job["external_id"],
                                       "url": job["url"], "posted": official.get("posted") or job["posted"],
                                       "vacancy": "Unverified"}
                            try:
                                outcome = ingest(job, job["source"] + " alert", 0)
                            except ValueError:
                                counts["rejected"] += 1
                                continue
                            if outcome == "duplicate":
                                counts["duplicates"] += 1
                            elif outcome == "excluded":
                                counts["rejected"] += 1
                        if parsed["parsing_errors"]:
                            errors.append(f"{parsed['platform']} alert body could not be fully decoded.")
                            continue
                        with store.connect() as c:
                            c.execute("INSERT OR IGNORE INTO email_processed VALUES(?,?,?)", (mailbox,key,stamp()))
                        processed.add(key)
                    except (sqlite3.Error, OSError):
                        counts["intake_errors"] += 1
                        errors.append(f"{parsed['platform']} alert intake failed and will retry.")
                report["failures"] = len(errors)
                report["state"] = "Partial failure" if errors else "Alerts processed" if report["emails"] else "No new alerts"
                result["source_health"]["Gmail alerts"] = report
                result["errors"].extend("Gmail: " + error for error in errors)
        except (ValueError, OSError, KeyError, TypeError) as error:
            result["source_health"]["Gmail alerts"] = {"state": "Reauthorization required" if isinstance(error,email_alerts.Reauthorize)
                                                       else "Failed", "failures": 1, "reauthorize": isinstance(error,email_alerts.Reauthorize),
                                                       "last_sync": stamp()}
            result["errors"].append("Gmail: " + str(error))
        inbox = store.folder / "inbox"
        inbox.mkdir(exist_ok=True)
        files = sorted(inbox.glob("*.json")) if email_batch is None and not active_only else []
        result["source_health"]["Authorized JSON inbox"] = {"state": "Configured", "files": len(files)}
        for file in files:
            try:
                if file.stat().st_size > 5_000_000:
                    raise ValueError("Inbox file exceeds 5 MB.")
                rows = json.loads(file.read_text())
                if not isinstance(rows, list):
                    raise ValueError("Expected an array of job objects.")
                for index, item in enumerate(rows):
                    try:
                        if not isinstance(item, dict) or not (item.get("url") or item.get("external_id") or item.get("requisition")):
                            raise ValueError("Inbox jobs need a stable source identifier.")
                        ingest(item, file.name, index + 1)
                    except Exception as error:
                        result["errors"].append(f"{file.name}:{index+1}: {error}")
            except Exception as error:
                result["errors"].append(f"{file.name}: {error}")
        allowed = [j for j in store.jobs() if j["industry"]["state"] == "allowed"]
        profile = None
        if allowed:
            try:
                profile = candidate()
            except (OSError, ValueError) as error:
                result["errors"].append("Matching blocked: resume unavailable or invalid (" + type(error).__name__ + ")")
        result["matching_status"] = "ready" if profile or not allowed else "blocked"
        for job in allowed if profile else []:
            if email_batch is not None and job["id"] not in added_ids:
                continue
            if (not job["match"] or job["match"].get("source_hash") != profile["sha256"]) and job["status"] not in FINISHED and job["vacancy"] != "Closed":
                assessment = assess(store, job, (job["match"] or {}).get("checks"), profile)
                if (job["id"] in added_ids and job["status"] in {"Discovered", "Scored", "Eligibility Review"} and
                        (assessment["match"]["score"] or 0) >= settings["pending"] and
                        assessment["match"]["eligibility"] != "Failed" and re.search(
                            r"\b(?:screening questions?|captcha|(?:sign|log) in to apply|create an account to apply)\b",
                            job["jd"] or "", re.I)):
                    store.update(job["id"], {"status": "Manual Action Required"})
        for job in store.jobs():
            if job["id"] in added_ids and not auto_apply.application_blockers(job, now().date()):
                market = job["country"]
                result["qualified"][market] = result["qualified"].get(market, 0) + 1
        clock = now()
        with store.connect() as c:
            result["submissions"] = manual_workflow.daily_submissions(c, clock.date().isoformat())
        result["cv_queue"] = cv_queue.reconcile(store)
        state = dashboard(store)
        result["platform_daily_gap"] = state["platform_daily_gap"]
        result["workflow"] = {
            "待我投递": state["counts"]["待我投递"], "需我处理": state["counts"]["需我处理"],
            "材料完成数": sum(e["kind"] == "Material generation runtime" and e["created"].startswith(clock.date().isoformat())
                             for j in state["jobs"] for e in j["events"]),
            "60分新候选": sum(j["id"] in added_ids and ((j["match"] or {}).get("score") or 0) >= 60 for j in state["jobs"]),
        }
        discovered = [j for j in state["jobs"] if j["id"] in seen_ids]
        from career_families import names
        result["career_family_coverage"] = {
            family: {country: sum(j["country"] == country and family in j["career_families"] for j in discovered)
                     for country in candidate_review.COUNTRIES}
            for family in names()
        }
        result["coverage"] = {
            channel: {"unique": len(jobs), "complete_jd": sum(bool(j["jd"] and not j["jd"].startswith("[Partial JD]")) for j in jobs),
                      "new_fit_60": sum(j["id"] in added_ids and ((j["match"] or {}).get("score") or 0) >= 60 for j in jobs)}
            for channel, ids in sorted(channels.items())
            for jobs in [[j for j in discovered if j["id"] in ids]]
        }
        result["discovery"] = {
            "Unique jobs discovered": len(discovered), "Newly added": len(added_ids),
            "Previously known": len(seen_ids - added_ids),
            "Confirmed recent": sum(j["vacancy"] == "Active" and within_discovery_window(j["original_posted_at"], clock, store.settings()["fresh_hours"])
                                    for j in discovered),
            "Date unverified": sum(not j["original_posted_at"] for j in discovered),
            "High fit (80+)": sum(((j["match"] or {}).get("score") or 0) >= 80 for j in discovered),
            "CVs generated": 0,
            "Applications already submitted": sum(any(e["kind"] in {"Submitted", "Manually Applied"} for e in j["events"]) for j in discovered),
            "Awaiting manual review": sum(j["status"] not in FINISHED and (not j["original_posted_at"] or
                                           bool(auto_apply.application_blockers(j, clock.date()))) for j in discovered),
            "Ambiguous listing rows": len(result["review"]),
        }
    except Exception as error:
        result["errors"].append(str(error))
        logging.exception("Run failed")
    finally:
        with store.connect() as c:
            c.execute("UPDATE runs SET result=? WHERE id=?", (json.dumps(result), ident))
        store.backup()
    return result


def rank(job):
    return (job["match"]["score"] or 0 if job["match"] else 0, job["posted"] or "", location_priority(job["location"]))


def fresh(job, settings):
    return not job["posted"] or (now().date() - dt.date.fromisoformat(job["posted"])).days <= min(settings["days"], 30)


def runs(store):
    with store.connect() as c:
        return [{**dict(r), "result": json.loads(r["result"])} for r in c.execute(
            "SELECT * FROM runs ORDER BY rowid DESC LIMIT 30")]


def dashboard(store):
    settings, all_jobs, history = store.settings(), store.jobs(), runs(store)
    settings.pop(assisted_apply.PROFILE, None)
    settings.pop("confirmed_screening_answers", None)
    rows = [j for j in all_jobs if j["industry"]["state"] == "allowed"]
    clock = now()
    local = clock.date()
    today = local.isoformat()
    main_cv_hash = cv_queue.digest_file(MAIN)
    template_hash = cv_queue.digest_file(runtime_config.resume_docx())
    for job in all_jobs:
        if job.get('generation'):
            g=job['generation'];g['elapsed_seconds']=max(0,int(((dt.datetime.fromisoformat(g['finished']) if g.get('finished') else clock)-dt.datetime.fromisoformat(g['started'])).total_seconds()))
            g['step']=next((e['detail'] for e in job['events'] if e['kind']=='Generation stage' and e['created']>=g['started']), '等待处理')
        from sponsorship import evidence as sponsor_evidence
        country_profile=settings.get('work_authorization_profiles',{}).get(job['country'],{})
        job['sponsorship_evidence']=sponsor_evidence(job['jd'],country_profile.get('state') in {'Requires sponsorship','Not authorized'})
        job["application_blockers"] = auto_apply.application_blockers(job, local)
        job["retention_blocker"] = cv_queue.gate(job,{**settings,"cv_queue_threshold":settings["high"]})
        if job['sponsorship_evidence']['excluded']:job['application_blockers'].append('本人需要雇主赞助，但JD明确不提供。')
        if job["country"] == "Japan":
            job["japan_review"] = workflow.japan_review(job, settings.get("japan_application_preferences", {}), job["sponsorship_evidence"])
            job["application_blockers"].extend(job["japan_review"])
        open_signal = next((e for e in job["events"] if e["kind"] == "Platform shows applications open"), None)
        job["platform_application"] = json.loads(open_signal["detail"]) if open_signal and job["vacancy"] != "Closed" else None
        job["workflow_state"] = workflow.display_state(job)
        job["current_documents"] = workflow.current_documents(job)
        job["materials_stale"] = any(doc and (doc["source_hash"] != main_cv_hash or
            doc["jd_hash"] != (job["match"] or {}).get("jd_hash") or
            (doc['kind']=='CV' and (doc["metadata"] or {}).get("template_sha256") != template_hash) or
            (doc['kind']=='CL' and (doc.get('metadata') or {}).get('cl_review',{}).get('facts_sha256') != __import__('cl_workflow').confirmed_facts()['sha256']))
            for doc in job["current_documents"].values())
        if job["materials_stale"] and job["workflow_state"] in {"待审核", "待我投递"}:
            job["workflow_state"] = "待生成材料"
        job["date_signal"] = opportunity_queues.date_signal(job, clock)
        job["fresh_discovery"] = job["vacancy"] == "Active" and within_discovery_window(job["original_posted_at"], clock, settings["fresh_hours"])
    eligible = [job["id"] for job in rows if not job["application_blockers"] and job["status"] not in FINISHED
                and not any(event["kind"] in {"Submitted", "Manually Applied"} for event in job["events"])]
    visible = [job for job in all_jobs if job["industry"]["state"] != "excluded" and job["status"] not in FINISHED]
    counts = {"New in last 72 hours": sum(job["fresh_discovery"] for job in visible),
              "Date verification needed": sum(not job["original_posted_at"] for job in visible),
              "High fit (80+)": sum(((job["match"] or {}).get("score") or 0) >= 80 for job in visible),
              "CV ready": sum(job["status"] == "CV Ready" for job in rows),
              "Interviewing": sum(job["status"] == "Interview" for job in all_jobs),
              "Offers": sum(job["status"] == "Offer" for job in all_jobs),
              "Previously seen / duplicates": history[0]["result"].get("duplicates", 0) if history else 0,
              "New today": sum(j["first_seen"].startswith(today) for j in rows)}
    for label, a, b in [("High match", settings["high"], 101), ("Pending review", settings["pending"], settings["high"]),
                        ("Saved opportunities", settings["saved"], settings["pending"]), ("Below threshold", 0, settings["saved"])]:
        counts[label] = sum(j["match"] is not None and j["match"]["score"] is not None
                            and a <= j["match"]["score"] < b for j in rows)
    counts.update({"Application eligible": len(eligible),
                   "High fit — needs verification": sum(((j["match"] or {}).get("score") or 0) >= 80 and bool(j["application_blockers"])
                       and j["status"] not in FINISHED for j in rows),
                   "CVs generated": sum(d["kind"] == "CV" for j in rows for d in j["documents"]),
                   "Ready to apply": sum(j["status"] == "Ready to Apply" for j in rows),
                   "Applied": sum(any(e["kind"] in {"Submitted", "Manually Applied"} for e in j["events"]) for j in all_jobs),
                   "Industry review": sum(j["industry"]["state"] == "review" for j in all_jobs),
                   "Manual action": sum(j["status"] == "Manual Action Required" for j in rows),
                   "Failed runs (last 30)": sum(bool(r["result"].get("errors")) for r in history)})
    counts["Confirmed submitted"] = sum(any(e["kind"] == "Submitted" for e in j["events"]) for j in all_jobs)
    pending = [j["id"] for j in sorted(rows, key=rank, reverse=True)
               if not j["sponsorship_evidence"]["excluded"] and not alert_needs_review(j) and j["status"] not in FINISHED and j["vacancy"] != "Closed" and fresh(j, settings)
               and not any(e["kind"] in {"Submitted", "Manually Applied"} for e in j["events"])
               and j["match"] and j["match"]["eligibility"] != "Failed" and (j["match"]["score"] or 0) >= settings["pending"]]
    from career_families import names
    candidate_pool = [j["id"] for j in sorted(visible, key=rank, reverse=True)
                      if not j["sponsorship_evidence"]["excluded"] and j["industry"]["state"] == "allowed" and (j["vacancy"] == "Active" or j["platform_application"])
                      and ((j["match"] or {}).get("score") or 0) >= settings["saved"]]
    candidate_ids = set(candidate_pool)
    queues = opportunity_queues.queues([job for job in rows if job["id"] in candidate_ids], clock)
    counts["Candidate pool (60+)"] = len(candidate_pool)
    counts["待我投递"] = sum(job["workflow_state"] == "待我投递" for job in all_jobs)
    counts["需我处理"] = sum(job["workflow_state"] == "需我处理" for job in all_jobs)
    eligible_ids = set(eligible)
    qualified_today = {j["id"] for j in rows if j["id"] in eligible_ids and j["first_seen"].startswith(today)}
    quotas = {country: {"target": settings[key], "tracked": sum(j["country"] == country for j in rows),
                        "qualified": sum(j["country"] == country and j["id"] in qualified_today for j in rows),
                        "prepared": sum(j["country"] == country and any(e["kind"] == "Prepared" and e["created"].startswith(today)
                                                                       for e in j["events"]) for j in rows)}
              for country, key in (("Canada", "canada"), ("UAE", "uae"))}
    with store.connect() as c:
        start = c.execute("SELECT value FROM settings WHERE key='scheduler_started'").fetchone()
        counts["Industry excluded"] = c.execute("SELECT COUNT(*) FROM exclusions").fetchone()[0] + sum(
            j["industry"]["state"] == "excluded" for j in all_jobs)
    first = dt.date.fromisoformat(json.loads(start[0])) if start else now().date()
    with store.connect() as c:
        cadence = load_cadence(c, first, product_policy.local_clock(settings,clock), settings["schedule"])
    missed = cadence["missing_dates"]
    sources = {s: sum(j["source"] == s for j in rows) for s in sorted({j["source"] for j in rows if j["source"]})}
    health = {"LinkedIn alerts": {"state": "Awaiting verified Gmail ingestion"},
              "Indeed alerts": {"state": "Awaiting verified Gmail ingestion"},
              "Manual URL / JD": {"state": "Available"}}
    for token in settings["boards"].split(","):
        if token.strip():
            health["Greenhouse: " + token.strip()] = {"state": "Configured; awaiting run"}
    for token in settings["lever_boards"].split(","):
        if token.strip():
            health["Lever: " + token.strip()] = {"state": "Configured; awaiting run"}
    health["Authorized JSON inbox"] = {"state": "Available"}
    last = next((r for r in history if "source_health" in r["result"]), None)
    if last:
        health.update(last["result"]["source_health"])
    try:
        config = email_alerts.load()
        email_status = {"state": "Authorized; select label" if config else "Authorization required",
                        "authorized": bool(config), "label": config.get("label")}
        if config.get("label"):
            email_status["state"] = "Configured; awaiting sync"
            last_email = next((r["result"]["source_health"]["Gmail alerts"] for r in history
                               if "Gmail alerts" in r["result"].get("source_health", {})), {})
            email_status.update(last_email)
            for platform in ("LinkedIn", "Indeed"):
                stats = last_email.get("platforms", {}).get(platform)
                if isinstance(stats, dict) and stats["emails"]:
                    health[platform + " alerts"] = {"state": f"{stats['emails']} email(s), {stats['jobs']} job(s) parsed"}
                elif isinstance(stats, int) and stats:
                    health[platform + " alerts"] = {"state": "Previously processed via Gmail"}
    except (ValueError, OSError):
        email_status = {"state": "Local credential configuration error"}
    health["Gmail alerts"] = email_status
    local = product_policy.local_clock(settings, now())
    next_run = local.replace(hour=int(settings["schedule"][:2]), minute=int(settings["schedule"][3:]), second=0, microsecond=0)
    if next_run <= local:
        next_run += dt.timedelta(days=1)
    with store.connect() as c:
        application_summary = workflow.application_day(c, now().date().isoformat())
        apply_stats = auto_apply.tally(c,local)
        submissions = manual_workflow.daily_submissions(c, today)
    return dict(jobs=all_jobs, environment="模拟数据" if runtime_config.fixture_mode() else "正式数据" if store.folder.resolve() == runtime_config.data_dir().resolve() else "隔离验收",
                dependency_health=runtime_config.dependency_health(), scheduler_health=dict(SCHEDULER_HEALTH),
                discovery_health=product_policy.relevant_run_health(history,settings,now()),
                cv_queue=cv_queue.panel(store), markets=list(product_policy.COUNTRIES),
                receipt_summary={key:len(rows) for key,rows in application_summary.items()}, submissions=submissions, queues=queues,
                platform_daily_gap=opportunity_queues.daily_gap(all_jobs, queues, submissions), candidate_pool=candidate_pool, career_families=names(), settings=settings, counts=counts, pending=pending, application_eligible=eligible, quotas=quotas, source_health=health,
                work_profiles=settings.get(candidate_review.PROFILE_KEY, {}), today=today,
                alert_review=[j["id"] for j in all_jobs if j["industry"]["state"] != "excluded"
                              and j["status"] not in FINISHED and alert_needs_review(j)],
                auto_apply={"mode":"Dry Run","stats":apply_stats,"pending":len(eligible),
                            "manual":counts["Manual action"],
                            "platforms":{key:{"verified":a.verified,"pilot":a.pilot_passed,"authorized":False}
                                         for key,a in auto_apply.ADAPTERS.items()}},
                next_run=next_run.isoformat(), last_discovery=last["created"] if last else None,
                runs=history, sources=sources, missed=missed, cadence=cadence, states=STATES, checks=list(SCREEN))


def scheduled_kind(store, local):
    settings=store.settings()
    local=product_policy.local_clock(settings,local)
    due=local.strftime("%H:%M") >= settings["schedule"]
    day=local.date().isoformat()
    with store.connect() as c:
        records=list(c.execute("SELECT kind,result,created FROM runs WHERE kind IN ('Scheduled','Recovery','Catch-up') ORDER BY rowid DESC"))
        today=[r for r in records if product_policy.run_day(r["created"],settings)==day]
        scheduled=[r for r in today if r["kind"]=="Scheduled"]
        if due:
            if not scheduled: return "Scheduled"
            latest=json.loads(scheduled[0]["result"])
            if len(scheduled)<3 and (latest.get("errors") or latest.get("running")) and (
                    local-dt.datetime.fromisoformat(scheduled[0]["created"])).total_seconds()>=600:
                return "Scheduled"
        elif not any(r["kind"] in {"Scheduled","Recovery"} for r in today):
            yesterday=(local.date()-dt.timedelta(days=1)).isoformat()
            started=c.execute("SELECT value FROM settings WHERE key='scheduler_started'").fetchone()
            previous=[r for r in records if product_policy.run_day(r["created"],settings)==yesterday]
            if started and json.loads(started[0])<=yesterday and not any(successful(json.loads(r["result"])) for r in previous):
                return "Recovery"
    return None


def scheduler(store):
    with store.connect() as c:
        c.execute("INSERT OR IGNORE INTO settings VALUES('scheduler_started',?)", (json.dumps(now().date().isoformat()),))
    failures = FailureLog()
    while True:
        try:
            SCHEDULER_HEALTH.update(state="checking",last_check=stamp(),error=None)
            kind = scheduled_kind(store, now())
            if kind:
                run_tasks(store, kind, expanded=True)
            SCHEDULER_HEALTH.update(state="healthy",last_check=stamp(),error=None)
            recovered = failures.recovered()
            if recovered:
                logging.warning("Scheduler storage/check recovered after %s failed checks; run outcome remains separate", recovered)
        except Exception as error:
            category = ("database_error" if isinstance(error, sqlite3.OperationalError)
                        else "filesystem_access" if isinstance(error, OSError)
                        else type(error).__name__)
            SCHEDULER_HEALTH.update(state="failed",last_check=stamp(),error=category)
            if failures.failed(category, time.monotonic()):
                logging.error("Scheduler check failed: category=%s attempts=%s; retrying in 30s; repeated logs limited to 10m",
                              category, failures.count)
        threading.Event().wait(30)


def handler(store, port):
    previews = {}
    preview_lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def reply(self, value, status=200, media="application/json", disposition=None):
            if not isinstance(value, bytes):
                value = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", media)
            self.send_header("Content-Length", str(len(value)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            if disposition:
                self.send_header("Content-Disposition", disposition)
            self.end_headers()
            self.wfile.write(value)

        def do_GET(self):
            self.dispatch(False)

        def do_POST(self):
            self.dispatch(True)

        def dispatch(self, post):
            host = f"127.0.0.1:{port}"
            if self.headers.get("Host") != host or (post and self.headers.get("Origin") != "http://" + host):
                return self.reply({"error": "Local application origin required."}, 403)
            path = urlsplit(self.path).path
            try:
                if not post:
                    assets = {"/": ("index.html", "text/html"), "/ui.js": ("ui.js", "text/javascript"),
                              "/style.css": ("style.css", "text/css"), "/mark.svg": ("mark.svg", "image/svg+xml")}
                    if path in assets:
                        file, mime = assets[path]
                        return self.reply((ROOT / file).read_bytes(), media=mime + "; charset=utf-8")
                    if path == "/api/health":
                        return self.reply({"scheduler":dict(SCHEDULER_HEALTH),"dependencies":runtime_config.dependency_health(),"fixture_mode":runtime_config.fixture_mode()})
                    if path == "/api/cv-queue/status":
                        panel=cv_queue.panel(store)
                        return self.reply({key:panel[key] for key in ("counts","worker","used_today","remaining_today")})
                    if path == "/api/state":
                        return self.reply(dashboard(store))
                    if path == "/api/assisted":
                        return self.reply(assisted_apply.panel(store))
                    if path == "/api/assisted/profile":
                        return self.reply(assisted_apply.profile(store))
                    if path == "/api/application-day":
                        day = parse_qs(urlsplit(self.path).query).get("date", [now().date().isoformat()])[0]
                        if dt.date.fromisoformat(day).isoformat() != day:
                            raise ValueError("请选择有效日期。")
                        with store.connect() as c:
                            return self.reply(workflow.application_day(c, day))
                    if path == "/api/email/labels":
                        return self.reply(email_alerts.labels(email_alerts.load()))
                    if path == "/api/facts":
                        return self.reply(candidate())
                    if path == "/main.pdf":
                        return self.reply(MAIN.read_bytes(), media="application/pdf")
                    if path in {"/export.json", "/export.csv"}:
                        if path.endswith("csv"):
                            return self.reply(store.csv().encode("utf-8-sig"), media="text/csv", disposition='attachment; filename="tracker.csv"')
                        value = store.export()
                        for doc in value["documents"]:
                            doc["pdf"] = base64.b64encode(doc["pdf"]).decode()
                        return self.reply(value, disposition='attachment; filename="tracker.json"')
                    if path.startswith("/api/material/"):
                        return self.reply(manual_workflow.document_text(store, path.split("/")[-1]))
                    screenshot = re.fullmatch(r"/import-evidence/([a-f0-9]{32}\.(?:png|jpg))", path)
                    if screenshot:
                        file = store.folder / "import-evidence" / screenshot[1]
                        if file.is_file():
                            return self.reply(file.read_bytes(), media="image/png" if file.suffix == ".png" else "image/jpeg")
                    if path.startswith("/docx/"):
                        key = path.split("/")[-1]
                        with store.connect() as c:
                            asset = c.execute("SELECT a.docx,d.kind FROM document_assets a JOIN documents d ON d.id=a.document WHERE a.document=?", (key,)).fetchone()
                        if asset and asset["docx"]:
                            return self.reply(asset["docx"], media="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                              disposition=f'attachment; filename="Tracker-{asset["kind"]}-{key[:8]}.docx"')
                    if path.startswith("/pdf/"):
                        key = path.split("/")[-1]
                        with store.connect() as c:
                            doc = c.execute("SELECT pdf,kind FROM documents WHERE id=?", (key,)).fetchone()
                        if doc:
                            return self.reply(doc["pdf"], media="application/pdf",
                                              disposition=f'{("attachment" if urlsplit(self.path).query=="download=1" else "inline")}; filename="Tracker-{doc["kind"]}-{key[:8]}.pdf"')
                else:
                    size = int(self.headers.get("Content-Length", 0))
                    if not 0 < size <= 500_000 or self.headers.get_content_type() != "application/json":
                        raise ValueError("Invalid JSON request size or type.")
                    data = json.loads(self.rfile.read(size))
                    if not isinstance(data, dict):
                        raise ValueError("Expected a JSON object.")
                    if path == "/api/assisted/mode":
                        return self.reply(assisted_apply.mode(store, data))
                    if path == "/api/assisted/profile":
                        return self.reply(assisted_apply.profile(store, data))
                    if path == "/api/assisted/action":
                        return self.reply(assisted_apply.apply_action(store, data))
                    if path == "/api/rehearsal/checkpoint":
                        return self.reply(rehearsal.checkpoint(store, data.get("id"), data))
                    if path == "/api/listing/observe":
                        return self.reply(opportunity_queues.record_observation(store, data.get("id"), data, now()))
                    if path == "/api/resume/search-terms":
                        return self.reply({"queries": opportunity_queues.resume_queries()})
                    if path == "/api/resume/discover":
                        return self.reply(run_tasks(store, "Resume discovery", active_only=True, expanded=True, resume=True))
                    if path == "/api/manual/jd":
                        return self.reply(manual_workflow.prepare(store, data))
                    if path == "/api/match/batch":
                        return self.reply(batch_match(store))
                    if path == "/api/manual/generate":
                        use_model = data.get("use_model") is True
                        materials = manual_workflow.start_generation(store, data.get("id"), regenerate=data.get("regenerate") is True,
                                                             use_model=use_model)
                        return self.reply(materials if use_model else {**materials, "execution": MATERIAL_EXECUTION})
                    if path == "/api/cl/review":
                        from cl_workflow import generate_cl
                        original=manual_workflow.document_text(store, data.get('id'))
                        if original['kind']!='CL':
                            raise ValueError('请选择求职信版本。')
                        return self.reply(generate_cl(store, original['job'], parent=original['id']))
                    if path == "/api/cl/generate":
                        from cl_workflow import generate_cl
                        return self.reply(generate_cl(store, data.get('id')))
                    if path == "/api/manual/edit":
                        return self.reply(manual_workflow.edit_document(store, data.get("id"), data.get("text")))
                    if path == "/api/manual/open":
                        return self.reply(manual_workflow.official_application(store, data.get("id")))
                    if path == "/api/manual/receipt":
                        return self.reply(manual_workflow.confirm_receipt(store, data.get("id"), data.get("receipt")))
                    if path == "/api/manual/handoff":
                        return self.reply(workflow.handoff(store, data.get("id")))
                    if path == "/api/materials/approve":
                        return self.reply(workflow.approve_materials(store, data.get("id"), data))
                    if path == "/api/application-profile":
                        return self.reply(workflow.save_profile(store, data))
                    if path == "/api/pilot/review":
                        return self.reply(workflow.pilot_review(store, data.get("id")))
                    if path == "/api/manual/correct":
                        return self.reply(manual_workflow.correct_application(store, data.get("id"), data))
                    if path == "/api/manual/application":
                        return self.reply(manual_workflow.record_application(store, data.get("id"), data))
                    if path == "/api/import/screenshot":
                        image = base64.b64decode(data.get("image", ""), validate=True)
                        if not image or len(image) > 350_000:
                            raise ValueError("请选择不超过 350 KB 的 PNG 或 JPEG 截图。")
                        extension = ".png" if image.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg" if image.startswith(b"\xff\xd8\xff") else ""
                        if not extension:
                            raise ValueError("截图必须是 PNG 或 JPEG。")
                        folder = store.folder / "import-evidence"
                        folder.mkdir(mode=0o700, exist_ok=True)
                        name = uuid.uuid4().hex + extension
                        with store.connect() as c:
                            if not c.execute("SELECT 1 FROM jobs WHERE id=?", (data.get("id"),)).fetchone():
                                raise ValueError("请先保存岗位。")
                            (folder / name).write_bytes(image)
                            store.event(c, data["id"], "Import screenshot", name)
                        return self.reply({"saved": True})
                    if path in {"/api/import", "/api/import/link"}:
                        if path == "/api/import/link":
                            url = data.get("url")
                            if not isinstance(url, str) or not url.strip() or len(url) > 3000:
                                raise ValueError("请输入有效的岗位链接。")
                            result = link_intake.import_link(store, url.strip())
                            if result["result"] == "unreadable":
                                assisted_apply.save_backlog(store, url.strip(), result["reason"])
                            elif result["result"] in {"added", "duplicate", "enriched", "linked", "excluded"}:
                                assisted_apply.save_backlog(store, url.strip())
                        else:
                            result = store.ingest(data, manual_import=True, edit_id=data.get("edit_id"))
                            if result["result"] in {"added", "duplicate", "enriched", "linked"}:
                                assisted_apply.save_backlog(store, data.get("url") or "")
                        if result.get("id") and result["result"] in {"added", "duplicate", "enriched", "linked"}:
                            job = next(j for j in store.jobs() if j["id"] == result["id"])
                            try:
                                prior = (job["match"] or {}).get("checks")
                                result["industry"] = job["industry"]
                                full = bool(job["jd"] and not job["jd"].startswith("[Partial JD]"))
                                result["complete_jd"] = full
                                if full and job["industry"]["state"] != "excluded":
                                    if not job["match"] and job["industry"]["state"] == "review":
                                        match = analyze(job, candidate(), prior, preview_industry=True)
                                        persist_match(store, job, match, advance=False)
                                        result["match"] = match
                                    elif not job["match"]:
                                        result.update(assess(store, job, prior))
                                    else:
                                        result["match"] = job["match"]
                            except Exception as error:
                                result["analysis_error"] = str(error)
                                with store.connect() as c:
                                    store.event(c, job["id"], "Analysis failed", str(error))
                        return self.reply(result)
                    if path == "/api/cv-queue/retry":
                        if data.get("confirmed") is not True:
                            raise ValueError("Explicit retry confirmation required.")
                        import cv_worker
                        cv_worker.retry(store,data.get("key"))
                        return self.reply({"queued":True})
                    if path == "/api/run":
                        return self.reply(run_tasks(store, "Catch-up", active_only=data.get("active_only") is True, expanded=True))
                    if path == "/api/auto-apply/dry-run":
                        state = dashboard(store)
                        pending = set(state["application_eligible"])
                        jobs = [j for j in sorted(state["jobs"], key=lambda row: (row["fresh_discovery"], rank(row)), reverse=True) if j["id"] in pending]
                        return self.reply({"mode":"Dry Run","results":auto_apply.dry_run(store,jobs)})
                    if path == "/api/email/label":
                        email_alerts.select_label(data.get("label"))
                        with preview_lock:
                            previews.clear()
                        return self.reply({"saved": True})
                    if path == "/api/import/read-export":
                        return self.reply({"jobs": bulk_intake.parse_export(data.get("content"), data.get("format"))})
                    if path in {"/api/email/preview", "/api/import/preview", "/api/employers/preview"}:
                        label = None
                        rows = data.get("jobs")
                        if path == "/api/email/preview":
                            label = email_alerts.load().get("label")
                            _, messages, errors = email_alerts.scan(store, historical=True)
                            if label != email_alerts.load().get("label"):
                                raise ValueError("Gmail label changed; preview again.")
                            rows = [job for _, jobs, _ in messages for job in jobs]
                            if not rows:
                                return self.reply({"id": None, "jobs": [], "counts": {}, "failures": len(errors)})
                        if path == "/api/employers/preview":
                            report, accepted = import_preview.employer_preview(store)
                        else:
                            report, accepted = import_preview.preview(store, rows, sample_platform=data.get("sample_platform"))
                        key = uuid.uuid4().hex
                        with preview_lock:
                            previews.clear()
                            previews[key] = (time.monotonic() + 900, label, report, accepted, path == "/api/import/preview")
                        return self.reply({"id": key, **report})
                    if path == "/api/import/confirm":
                        with preview_lock:
                            item = previews.get(data.get("id"))
                            if not item or time.monotonic() > item[0] or (
                                    item[1] and item[1] != email_alerts.load().get("label")):
                                raise ValueError("Preview expired or label changed. Preview again.")
                            results = import_preview.import_selected(store, item[2], item[3], data.get("selected"), manual_import=len(item) > 4 and item[4])
                            previews.pop(data["id"], None)
                        return self.reply({"results": results, "added": sum(r["result"] == "added" for r in results)})
                    if path == "/api/candidates/review":
                        return self.reply(candidate_review.review(store))
                    if path == "/api/work-authorization/profile":
                        candidate_review.save_profile(store, data)
                        return self.reply({"saved": True})
                    if path == "/api/backup":
                        return self.reply({"path": str(store.backup())})
                    if path == "/api/cv-queue/reconcile":
                        return self.reply(cv_queue.reconcile(store))
                    if path == "/api/cv-queue/mock":
                        return self.reply({"outcomes":cv_queue.run_mock(store)})
                    if path == "/api/settings":
                        current = store.settings()
                        values = {k: data.get(k, current[k]) for k in DEFAULT}
                        for key in ("fresh_hours","cv_queue_threshold","cv_queue_daily_limit","saved","pending","high"):
                            if isinstance(values[key],str) and values[key].isdigit(): values[key]=int(values[key])
                        for key in ("enabled_countries","priority_locations"):
                            if isinstance(values[key],str): values[key]=[x.strip() for x in values[key].split(",") if x.strip()]
                        product_policy.validate(values)
                        boards = values["boards"]
                        lever = values["lever_boards"]
                        if not isinstance(lever,str) or any(x.strip() not in LEVER_EMPLOYERS for x in lever.split(",") if x.strip()):
                            raise ValueError("Choose verified Lever boards: " + ", ".join(LEVER_EMPLOYERS))
                        if not isinstance(boards, str) or len(boards) > 1000 or len(boards.split(",")) > 15 or any(
                            not TOKEN.fullmatch(x.strip()) for x in boards.split(",") if x.strip()):
                            raise ValueError("Enter up to 15 Greenhouse board tokens, separated by commas.")
                        if any(type(values[k]) is not int or not 0 <= values[k] <= 100 for k in ("canada", "uae", "days", "high", "pending", "saved")):
                            raise ValueError("Invalid quota, threshold or date range.")
                        if not 1 <= values["days"] <= 30 or not 0 <= values["saved"] < values["pending"] < values["high"] <= 100:
                            raise ValueError("Thresholds must be ordered; lookback is 1–30 days.")
                        dt.time.fromisoformat(values["schedule"])
                        if len(values["schedule"]) != 5 or any(not isinstance(values[k], str) or len(values[k]) > 5000 for k in ("locations", "roles")):
                            raise ValueError("Invalid schedule, locations or categories.")
                        with store.connect() as c:
                            c.executemany("INSERT OR REPLACE INTO settings VALUES(?,?)", [(k,json.dumps(v)) for k,v in values.items()])
                        return self.reply({"saved": True})
                    job = next((j for j in store.jobs() if j["id"] == data.get("id")), None)
                    if not job:
                        raise ValueError("Job not found.")
                    if path == "/api/update":
                        store.update(job["id"], data)
                        return self.reply({"saved": True})
                    if path == "/api/industry" and job["industry"]["state"] == "review":
                        store.review_industry(job["id"], data.get("decision"))
                        updated = next(j for j in store.jobs() if j["id"] == job["id"])
                        return self.reply(assess(store, updated) if updated["industry"]["state"] == "allowed" else {})
                    if path == "/api/score":
                        require_allowed(job)
                        result = analyze(job, candidate(), data.get("checks"))
                        persist_match(store, job, result)
                        return self.reply(result)
                    if path == "/api/document" and data.get("kind") in {"CV", "CL"}:
                        return self.reply({"id": make_document(store, job, data["kind"])})
                self.reply({"error": "Not found."}, 404)
            except (ValueError, TypeError, AttributeError, FileNotFoundError) as error:
                self.reply({"error": str(error)}, 400)
            except Exception:
                logging.exception("Request failed")
                self.reply({"error": "Request failed; check the local log."}, 500)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=runtime_config.data_dir())
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--restore", nargs=2, metavar=("BACKUP", "NEW_DATABASE"))
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--no-scheduler", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    if args.restore:
        Store.restore(*args.restore)
        return
    store = Store(args.data)
    logging.basicConfig(filename=store.folder / "errors.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if args.run:
        print(json.dumps(run_tasks(store, "Catch-up"), indent=2))
        return
    cv_queue.reconcile(store)
    with store.connect() as c:
        c.execute("UPDATE generation_jobs SET state='failed',finished=?,error='服务重启中断了生成。已保存材料保留，请重试。' WHERE state='running'",(stamp(),))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(store, args.port))
    cv_queue.recover_interrupted(store)
    import cv_worker
    threading.Thread(target=cv_worker.loop,args=(store,),daemon=True).start()
    if args.port == PORT and store.folder.resolve() == runtime_config.data_dir().resolve():
        (store.folder / "server.pid").write_text(str(os.getpid()) + "\n")
    if not args.no_scheduler:
        threading.Thread(target=scheduler, args=(store,), daemon=True).start()
    if args.no_scheduler:
        SCHEDULER_HEALTH.update(state="disabled",last_check=stamp())
    print(f"http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
