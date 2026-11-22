import json
"""Read-only vacancy preview against employer feeds, with explicit selected-row import."""
import datetime as dt
import re
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from core import TARGET_MARKETS, ALERT_PLATFORMS, TZ, canonical, norm, now, platform_date_label, within_application_window, within_discovery_window
from career_families import classify_roles
from discovery import CANADA, UAE, MARKETS, collect, expanded_settings, location_priority
from email_alerts import job_url
from industry import classify
from matching import analyze, candidate, persist_match
from auto_apply import application_blockers, prior_application
from bulk_intake import prepare_row


def normalize_input(row):
    row = prepare_row(row)
    if not isinstance(row, dict):
        raise ValueError("Each listing must be an object.")
    fields = ("title", "company", "location", "source", "external_id", "url", "apply_url", "requisition", "jd", "jd_quality", "platform_date_kind", "platform_date_evidence", "industry_declared", "platform_apply", "closure_url")
    limits = {"url": 3000, "apply_url": 3000, "jd": 100000}
    item = {}
    for field in fields:
        value = row.get(field, "")
        if not isinstance(value, str) or len(value) > limits.get(field, 500):
            raise ValueError(f"Invalid listing field {field}.")
        item[field] = value.strip()
    if not item["title"] or not item["company"] or not item["source"] or not item["url"]:
        raise ValueError("Title, company, source and a listing URL are required.")
    platform = item["source"]
    if item["platform_apply"] not in {"", "On platform", "External"}:
        raise ValueError("Choose a valid observed application route.")
    if item["platform_apply"] and platform not in ALERT_PLATFORMS:
        raise ValueError("Platform application observations require LinkedIn or Indeed.")
    if item["closure_url"]:
        item["closure_url"] = canonical(item["closure_url"])
        if not item["closure_url"].startswith("https://"):
            raise ValueError("A verified employer closure requires its HTTPS link.")
    if platform in ALERT_PLATFORMS:
        identity = job_url(item["url"], platform)
        if not identity or (item["external_id"] and item["external_id"].casefold() != identity[0]):
            raise ValueError("Platform URL and job ID do not identify the same listing.")
        item["external_id"], item["url"] = identity
    else:
        item["url"] = canonical(item["url"])
    item["apply_url"] = canonical(item["apply_url"]) or ""
    platform_date_label(item["platform_date_kind"], item["platform_date_evidence"])
    if item["industry_declared"] not in {"", "traditional", "web3"}:
        raise ValueError("Invalid industry classification.")
    if item["jd_quality"] not in {"", "Partial", "Full"}:
        raise ValueError("Invalid job description completeness.")
    return item


def keys(item):
    urls = {canonical(item[field]) for field in ("url", "apply_url") if item.get(field)}
    result = {("url", url) for url in urls}
    for url in urls:
        parts = urlsplit(url)
        if parts.hostname in {"boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io"}:
            match = re.fullmatch(r"/([a-z0-9][a-z0-9_-]*)/jobs/(\d+)", parts.path)
            if match:
                result.add(("greenhouse", *match.groups()))
        if parts.hostname in {"jobs.lever.co", "jobs.eu.lever.co"}:
            match = re.fullmatch(r"/([a-z0-9._-]+)/([a-f0-9-]{36})(?:/apply)?", parts.path)
            if match:
                result.add(("lever", *match.groups()))
    if item.get("external_id"):
        result.add(("id", item["source"], item["external_id"]))
    if item.get("requisition") and norm(item["company"]):
        result.add(("requisition", norm(item["company"]), norm(item["requisition"])))
    return result


def similar(left, right):
    company = norm(left["company"])
    return bool(company and company != "employer unverified" and company == norm(right["company"])
                and SequenceMatcher(None, norm(left["title"]), norm(right["title"])).ratio() >= .8)


def recent_platform_display(evidence, today):
    evidence = evidence.casefold().strip()
    if evidence in {"today", "just posted", "yesterday", "1 week ago"}:
        return True
    relative = re.fullmatch(r"(\d+) (hour|day)s? ago", evidence)
    if relative:
        return int(relative[1]) < (24 * 14 if relative[2] == "hour" else 14)
    try:
        if "t" in evidence:
            value = dt.datetime.fromisoformat(evidence.upper().replace("Z", "+00:00"))
            return bool(value.tzinfo and within_application_window(value.astimezone(TZ).date().isoformat(), today))
        return within_application_window(evidence, today)
    except ValueError:
        return False


def preview(store, rows, *, employer_feeds=None, sample_platform=None):
    if not isinstance(rows, list) or (employer_feeds is None and not 1 <= len(rows) <= 500):
        raise ValueError("Provide an array of 1 to 500 listings.")
    if sample_platform is not None and sample_platform not in ALERT_PLATFORMS:
        raise ValueError("Choose LinkedIn or Indeed for the manual search sample.")
    inputs, rejected = [], 0
    for row in rows:
        try:
            item = normalize_input(row)
            if sample_platform and item["source"] != sample_platform:
                raise ValueError("This listing is outside the selected sample platform.")
            inputs.append(item)
        except ValueError:
            rejected += 1
    if employer_feeds is None:
        health = {}
        has_employer_identity = any(row["source"] not in ALERT_PLATFORMS or row["apply_url"] or row["requisition"] or (row["company"] != "Employer unverified" and row["location"])
                                    for row in inputs)
        boards = collect(expanded_settings(store.settings()), health, verification=True) if has_employer_identity else []
    else:
        boards, health = employer_feeds
    board_keys = [keys(board) for board in boards]
    existing = store.jobs()
    by_id = {job["id"]: keys(job) for job in existing}
    records = {job["id"]: job for job in existing}
    with store.connect() as c:
        for row in c.execute("SELECT * FROM sources"):
            by_id[row["job"]].update(keys(dict(source=row["platform"], external_id=row["external_id"], url=row["url"])))
    accepted, seen, entries = {}, {}, []
    profile = None
    today = now().date()
    resolved = []
    for item in inputs:
        identity = keys(item)
        direct = {key for key in identity if key[0] != "requisition"}
        matches = [i for i, lookup in enumerate(board_keys) if direct & lookup]
        if not matches:
            matches = [i for i, lookup in enumerate(board_keys) if identity & lookup]
        resolved.append((item, identity, matches))
    # Use the copy with employer evidence as the primary row when alert
    # variants carry different amounts of detail.
    for item, identity, matches in sorted(resolved, key=lambda row: (len(row[2]) != 1, row[0]["jd_quality"] != "Full",
                                                           row[0]["company"] == "Employer unverified")):
        board = boards[matches[0]] if len(matches) == 1 else None
        candidate_matches = [board] if board else [b for b in boards if similar(item, b)]
        if board:
            identity |= board_keys[matches[0]]
        source_identity = {key for key in identity if key[0] != "requisition"}
        prior = {seen[key] for key in source_identity if key in seen}
        existing_ids = [job_id for job_id, lookup in by_id.items() if identity & lookup]
        exact = bool(existing_ids)
        if len(prior) == 1 and len(matches) <= 1:
            # Keep source attribution if the user approves this vacancy.
            primary = next(iter(prior))
            accepted[primary][1].append(item)
            entries[primary]["existing_ids"] = sorted(set(entries[primary]["existing_ids"]) | set(existing_ids))
            for key in source_identity:
                seen[key] = primary
            if exact and entries[primary]["selectable"]:
                entries[primary].update(status="Already tracked", selectable=False)
            continue
        index = len(entries)
        for key in source_identity:
            seen.setdefault(key, index)
        ambiguous = len(prior) > 1 or len(matches) > 1 or (not board and bool(candidate_matches)) or (
            not exact and (any(similar(item, job) for job in existing)
                           or (not board and any(similar(item, previous) for previous, _, _ in accepted.values()))))
        markets = [name for name, pattern in MARKETS
                   if re.search(pattern, item["location"], re.I)]
        job = {**item, "apply_url": "", "posted": "", "vacancy": "Unverified",
               "allow_similar": item["company"] == "Employer unverified",
               "country": markets[0] if len(markets) == 1 else "Unverified",
               "jd": item["jd"] or "Verify the listing and obtain the original job description.",
               "jd_quality": "Full" if item["jd"] and item["jd_quality"] == "Full" else "Partial"}
        if board:
            job.update(board, source=item["source"], external_id=item["external_id"], url=item["url"])
            if board["jd_quality"] != "Full" and item["jd"] and item["jd_quality"] == "Full":
                job.update(jd=item["jd"], jd_quality="Full")
        if item["closure_url"]:
            job["vacancy"] = "Closed"
        industry = classify(item)["state"]
        excluded = industry == "excluded" or classify(job)["state"] == "excluded"
        posted = job.get("posted") or ""
        recent = within_application_window(posted, today)
        fresh_discovery = within_discovery_window(job.get("original_posted_at"), now())
        expired = bool(posted and dt.date.fromisoformat(posted) < today and not recent)
        match = None
        if not excluded and job["jd_quality"] == "Full" and classify(job)["state"] == "allowed":
            profile = profile or candidate()
            match = analyze(job, profile)
        enrich = next((old["id"] for old in existing if old["url"] and canonical(old["url"]) == canonical(item["url"])
                       and old["industry"]["state"] != "excluded" and (not old["jd"] or old["jd"].startswith("[Partial JD]"))
                       and job["jd_quality"] == "Full" and old["status"] in {"Discovered", "Saved", "Pending Review"}), None)
        link_id = existing_ids[0] if len(existing_ids) == 1 and (
            ("url", canonical(item["url"])) not in by_id[existing_ids[0]]) and not enrich else None
        reason = ("Excluded industry" if excluded else "Employer closed" if item["closure_url"] else "Add missing JD to existing job" if enrich else "Attach source to existing job" if link_id else "Already tracked" if exact
                  else "Possible duplicate" if ambiguous else "Historical listing" if expired else "Manual review")
        coverage_notes = []
        if not exact:
            if ambiguous:
                coverage_notes.append("Possible duplicate requires review")
            if not board:
                coverage_notes.append("No exact vacancy match in the configured official feeds")
            if job["country"] == "Unverified":
                coverage_notes.append("Target region not verified")
            if job["jd_quality"] != "Full":
                coverage_notes.append("Complete JD missing")
            elif not classify_roles(job["title"], job["jd"]):
                coverage_notes.append("No matching career family from title or responsibilities")
            if match and match["score"] is not None and match["score"] < 60:
                coverage_notes.append("Main CV score below 60")
        blockers = application_blockers({**job, "match": match}, today)
        entries.append(dict(index=index, title=job["title"], company=job["company"], source=job["source"],
                            country=job["country"], location=job["location"],
                            date_evidence=job.get("posting_date_evidence", ""), blockers=blockers, coverage_notes=coverage_notes,
                            platform_date_label=platform_date_label(job["platform_date_kind"], job["platform_date_evidence"]),
                            platform_date_evidence=job["platform_date_evidence"], complete_jd=job["jd_quality"] == "Full",
                            fit_evidence=sorted({evidence["keyword"] for part in match["parts"]
                                                 for evidence in part["evidence"] if evidence.get("cv")}) if match else [],
                            fit_gaps=match["gaps"] if match else [],
                            fit_points=[{key: part[key] for key in ("name", "points", "weight")}
                                        for part in match["parts"]] if match else [],
                            url=job["url"], employer_url=board["url"] if board else "",
                            possible_employer_urls=[candidate["url"] for candidate in candidate_matches[:5]] if not board else [],
                            active=bool(board and job["vacancy"] == "Active"), platform_open=bool(item["platform_apply"] and job["jd_quality"] == "Full" and job["vacancy"] != "Closed"), posted=posted, recent=recent,
                            fresh_discovery=fresh_discovery,
                            platform_recent=recent_platform_display(job["platform_date_evidence"], today),
                            score=match["score"] if match else None, work_authorization=False,
                            status=reason, existing_ids=existing_ids, enrich_id=enrich, link_id=link_id, selectable=not (excluded or (exact and not (enrich or link_id or (len(existing_ids) == 1 and (item["platform_apply"] or item["closure_url"])))) or ambiguous)))
        accepted[index] = (job, [item, board] if board else [item], match)
    counts = {
        "Total unique jobs": len(entries),
        "Verified active jobs": sum(row["active"] for row in entries),
        "Verified dates within 14 days": sum(row["recent"] for row in entries),
        "Verified original posting dates": sum(bool(row["posted"]) for row in entries),
        "Jobs scoring 80+": sum((row["score"] or 0) >= 80 for row in entries),
        "Blocked by application checks": sum(bool(row["blockers"]) for row in entries),
        "Verified work authorization": 0,
        "Possible duplicates": sum(row["status"] == "Possible duplicate" for row in entries),
        "Already tracked": sum(row["status"] == "Already tracked" for row in entries),
        "Manual review": sum(row["selectable"] or row["status"] == "Possible duplicate" for row in entries),
        "Rejected or expired": rejected + sum(row["status"] in {"Excluded industry"}
                                               for row in entries),
    }
    counts["Duplicates"] = len(inputs) - len(entries) + counts["Already tracked"]
    counts["Missing JD"] = sum(not row["complete_jd"] for row in entries)
    counts["Missing original date"] = sum(not row["posted"] for row in entries)
    counts["Verified originals within 72 hours"] = sum(row["fresh_discovery"] for row in entries)
    counts["Input listing rows"] = len(rows)
    counts["Recent platform dates, original unverified"] = sum(
        not row["posted"] and row["platform_recent"] for row in entries)
    counts["Complete job descriptions"] = sum(row["complete_jd"] for row in entries)
    counts["Application eligible"] = sum(not row["blockers"] for row in entries)
    counts["Indeed cross-verified"] = sum(row["active"] and any(
        alias["source"] == "Indeed" for alias in accepted[row["index"]][1]) for row in entries)
    report = {"counts": counts, "jobs": entries, "source_health": health}
    if sample_platform:
        complete = fresh = qualified = 0
        with store.connect() as c:
            for row in entries:
                job, aliases, match = accepted[row["index"]]
                sample_has_jd = any(alias["source"] == sample_platform and alias.get("jd_quality") == "Full"
                                    and bool(alias.get("jd")) for alias in aliases)
                complete += sample_has_jd
                existing = records[row["existing_ids"][0]] if len(row["existing_ids"]) == 1 else None
                evidence = job if job.get("original_posted_at") else existing or job
                verified_fresh = within_discovery_window(evidence.get("original_posted_at"), now())
                fresh += verified_fresh
                previous = (existing or {}).get("match") or {}
                if not (sample_has_jd and verified_fresh and match and existing and previous and
                        job["country"] == existing["country"] and
                        all(match.get(key) == previous.get(key) for key in ("source_hash", "jd_hash"))):
                    continue
                assessed = {**job, "match": previous, "posted": evidence["posted"], "vacancy": evidence["vacancy"]}
                in_scope = assessed["country"] in TARGET_MARKETS and bool(classify_roles(assessed["title"], assessed["jd"]))
                qualified += bool(in_scope and not application_blockers(assessed, today)
                                  and not prior_application(c, existing) and row["status"] not in
                                  {"Excluded industry", "Possible duplicate"})
        report["manual_sample"] = {"platform": sample_platform, "raw_rows": len(rows),
            "unique_jobs": len(entries), "already_tracked": sum(bool(row["existing_ids"]) for row in entries),
            "complete_jds": complete, "verified_originals_72h": fresh, "qualified": qualified,
            "new_fit_60": sum(not row["existing_ids"] and row["status"] != "Possible duplicate"
                              and (row["score"] or 0) >= 60 for row in entries),
            "out_of_scope_or_invalid": rejected, "has_20_complete_jds": complete >= 20}
    return report, accepted


def employer_preview(store):
    settings = store.settings()
    health = {}
    boards = collect(expanded_settings(settings), health)
    allowed = [job for job in boards if classify(job)["state"] != "excluded"]
    report, accepted = preview(store, allowed, employer_feeds=(allowed, health))
    markets = {}
    shortlist = []
    for country, field in (("Canada", "canada"), ("UAE", "uae")):
        rows = [row for row in report["jobs"] if row["country"] == country]
        candidates = [row for row in rows if row["selectable"]]
        candidates.sort(key=lambda row: (not row["fresh_discovery"], -location_priority(row["location"]),
                                         -(row["score"] or 0)))
        chosen = candidates[:settings[field]]
        markets[country] = {"discovered": len(rows), "target": settings[field], "shortlisted": len(chosen),
                            "dated": sum(bool(row["posted"]) for row in rows),
                            "high_fit": sum((row["score"] or 0) >= 80 for row in rows),
                            "blocked": sum(bool(row["blockers"]) for row in rows)}
        shortlist.extend(chosen)
    shortlisted_ids = {row["index"] for row in shortlist}
    for row in shortlist:
        row["shortlisted"] = True
    report.update(jobs=shortlist + [row for row in report["jobs"] if row["index"] not in shortlisted_ids],
                  markets=markets)
    return report, accepted


def import_selected(store, report, accepted, selected, *, manual_import=False):
    allowed = {row["index"]: row for row in report["jobs"] if row["selectable"]}
    if not isinstance(selected, list) or not selected or any(type(i) is not int or i not in allowed for i in selected):
        raise ValueError("Select eligible import rows from the preview.")
    results = []
    for index in dict.fromkeys(selected):
        job, aliases, match = accepted[index]
        try:
            enrich_id = allowed[index].get("enrich_id")
            link_id = allowed[index].get("link_id")
            if link_id and not job["apply_url"]:
                job = {**job, "apply_url": aliases[0]["apply_url"]}
            result = store.ingest(job, new_only=not enrich_id, aliases=aliases[1:], enrich_id=enrich_id, link_id=link_id, manual_import=manual_import)
        except ValueError as error:
            results.append({"index": index, "result": "rejected", "reason": str(error)})
            continue
        if result["result"] in {"added", "enriched", "duplicate", "linked"}:
            saved = next(row for row in store.jobs() if row["id"] == result["id"])
            if not saved["match"] and saved["jd"] and not saved["jd"].startswith("[Partial JD]") and saved["industry"]["state"] == "allowed":
                persist_match(store, saved, analyze(saved, candidate()))
        if result["result"] in {"added", "enriched", "duplicate", "linked"}:
            with store.connect() as c:
                for observed in aliases:
                    if observed.get("platform_apply") and observed["jd_quality"] == "Full":
                        detail = json.dumps({"url": observed["url"], "route": observed["platform_apply"]})
                        if not c.execute("SELECT 1 FROM events WHERE job=? AND kind='Platform shows applications open' AND detail=?",
                                         (result["id"], detail)).fetchone():
                            store.event(c, result["id"], "Platform shows applications open", detail)
                if job.get("closure_url"):
                    c.execute("UPDATE jobs SET vacancy='Closed' WHERE id=?", (result["id"],))
                    store.event(c, result["id"], "Employer vacancy closed", job["closure_url"])
        results.append({"index": index, **result})
    return results
