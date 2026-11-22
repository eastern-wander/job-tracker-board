"""Read-only high-fit review and explicit country profile confirmation."""
import datetime as dt
import json
import re
import subprocess

from auto_apply import application_blockers, prior_application
from core import TARGET_MARKETS, TZ, now, stamp, within_application_window
from discovery import fetch_json
from import_preview import employer_preview, keys
from matching import EMPLOYER_RESTRICTIONS, SPONSORSHIP, WORK_AUTHORIZATION

COUNTRIES = TARGET_MARKETS
PROFILE_KEY = "work_authorization_profiles"
PROFILE_STATES = ("Authorized", "Requires sponsorship", "Not authorized")


def save_profile(store, data):
    country, state = data.get("country"), data.get("state")
    evidence, expires = data.get("evidence", ""), data.get("expires", "")
    if country not in COUNTRIES or state not in PROFILE_STATES or data.get("confirmed") is not True:
        raise ValueError("Explicitly confirm a country and work authorization status.")
    if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 1500 or not isinstance(expires, str):
        raise ValueError("Provide a brief basis and any work restrictions.")
    if expires and dt.date.fromisoformat(expires).isoformat() != expires:
        raise ValueError("Use an ISO expiry date.")
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute("SELECT value FROM settings WHERE key=?", (PROFILE_KEY,)).fetchone()
        profiles = json.loads(existing[0]) if existing else {}
        profiles[country] = dict(state=state, evidence=evidence.strip(), expires=expires, confirmed_at=stamp())
        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (PROFILE_KEY, json.dumps(profiles)))


def posting_evidence(job, today):
    published = job.get("first_published") or ""
    evidence = {"posted": job.get("posted") or "", "original": published,
                "updated": job.get("updated_at") or "", "source": job["url"],
                "detail_original": "", "confidence": "Official feed" if published else "Unverified",
                "note": ""}
    ident = re.fullmatch(r"([a-z0-9][a-z0-9_-]{0,59}):(\d+)", job.get("external_id") or "")
    if job["source"] != "Greenhouse" or not ident:
        evidence["note"] = "This feed does not provide an original publication date."
        return evidence
    endpoint = f"https://boards-api.greenhouse.io/v1/boards/{ident[1]}/jobs/{ident[2]}"
    evidence["detail_url"] = endpoint
    try:
        detail = fetch_json(endpoint)
        if str(detail.get("id")) != ident[2]:
            raise ValueError("Official detail did not match the listing ID.")
        evidence["updated"] = detail.get("updated_at") or evidence["updated"]
        confirmed = detail.get("first_published")
        if not confirmed:
            evidence["note"] = "The detail endpoint supplied no original posting timestamp."
            return evidence
        evidence["detail_original"] = confirmed
        date = dt.datetime.fromisoformat(confirmed.replace("Z", "+00:00"))
        if date.tzinfo is None or date.astimezone(TZ).date() > today:
            raise ValueError("The detail timestamp is invalid.")
        if published and date != dt.datetime.fromisoformat(published.replace("Z", "+00:00")):
            evidence.update(posted="", confidence="Conflicting evidence",
                            note="The original timestamps in the listing feed and detail endpoint differ.")
        else:
            evidence.update(posted=date.astimezone(TZ).date().isoformat(),
                            confidence="Cross-checked" if published else "Official job detail")
    except (AttributeError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        evidence["note"] = "The official detail endpoint could not confirm the publication timestamp."
    return evidence


def review(store):
    report, accepted = employer_preview(store)
    profiles = store.settings().get(PROFILE_KEY, {})
    today = now().date()
    candidates = []
    tracked = [(job, {key for key in keys(job) if key[0] != "requisition"}) for job in store.jobs()]
    blocked = {}
    for row in report["jobs"]:
        if (row["score"] or 0) < 80:
            continue
        job, _, match = accepted[row["index"]]
        exact = [existing for existing, identity in tracked if identity & keys(job)]
        existing = exact[0] if len(exact) == 1 else None
        saved_match = (existing or {}).get("match") or {}
        if saved_match and existing["country"] == job["country"] and all(
                saved_match.get(field) == match.get(field) for field in ("jd_hash", "source_hash")):
            match = saved_match
        dates = posting_evidence(job, today)
        recent = within_application_window(dates["posted"], today)
        blockers = application_blockers({**job, "posted": dates["posted"], "match": match}, today)
        if existing:
            with store.connect() as c:
                if prior_application(c, existing):
                    blockers.append("A previous or unresolved application exists for this vacancy.")
        if not dates["posted"]:
            next_action = "Find the original posting date on the employer’s listing."
        elif not recent:
            next_action = "Review as expired under the 14-day rule."
        elif job["vacancy"] != "Active":
            next_action = "Verify the vacancy with the employer."
        elif blockers:
            next_action = "Confirm country work status and check the employer’s sponsorship and restrictions."
        else:
            next_action = "Review the application materials."
        screening = {}
        for key in (WORK_AUTHORIZATION, SPONSORSHIP, EMPLOYER_RESTRICTIONS):
            check = match["checks"].get(key, {})
            screening[key] = {"state": check.get("state", "Unverified"), "reason": check.get("reason", ""),
                              "listing_evidence": check.get("jd", [])}
        for reason in blockers:
            blocked[reason] = blocked.get(reason, 0) + 1
        candidates.append({**row, "official_url": row["employer_url"] or row["url"], "dates": dates,
                           "recent": recent, "vacancy": job["vacancy"], "screening": screening,
                           "blockers": blockers, "next_action": next_action,
                           "discovered": existing["first_seen"] if existing else ""})
    candidates.sort(key=lambda row: (not (row["recent"] and row["vacancy"] == "Active"),
                                     -row["score"], row["company"], row["title"]))
    return {"jobs": candidates, "blocked": blocked, "profiles": profiles, "checked_at": stamp(),
            "counts": {"High fit": len(candidates), "Verified recent original dates": sum(row["recent"] for row in candidates),
                       "Confirmed eligibility": sum(not row["blockers"] for row in candidates)},
            "unavailable_feeds": sum(feed["state"] == "Failed" for feed in report["source_health"].values())}
