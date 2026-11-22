"""Date evidence and manual queues, independent of auto-apply eligibility."""
import datetime as dt
import json
import re
from calendar import monthrange

from core import TARGET_MARKETS, canonical, within_discovery_window
from matching import candidate, contains


RESUME_QUERIES = {
    "supplier": ("Supplier Performance Analyst", "Procurement Operations Coordinator", "Vendor Manager"),
    "partnerships": ("Partner Enablement Specialist", "Alliance Operations Associate", "Partnerships Manager"),
    "coordination": ("Implementation Coordinator", "Program Delivery Specialist", "Project Coordinator"),
    "logistics": ("Carrier Performance Analyst", "Freight Operations Coordinator", "Logistics Specialist"),
    "campaign": ("Campaign Operations Specialist", "Marketing Operations Coordinator", "Marketing Operations Manager"),
    "research": ("Market Intelligence Analyst", "Competitive Intelligence Associate", "Market Research Analyst"),
    "compliance": ("Compliance Operations Analyst", "Controls Coordinator", "Compliance Specialist"),
    "tableau": ("Reporting and Insights Analyst", "Business Reporting Specialist", "Business Intelligence Analyst"),
}
READ_STATES = {"Login required", "Redirected", "Summary only", "Explicitly closed", "Request failed", "Unknown", "Readable"}


def resume_queries(profile=None):
    from core import norm
    facts = (profile or candidate())["facts"]
    return [query for term, queries in RESUME_QUERIES.items()
            if any(contains(norm(fact["text"]), term) for fact in facts)
            for query in queries]


def date_signal(job, clock):
    observations = [json.loads(event["detail"]) for event in job["events"] if event["kind"] == "Listing date observed"]
    evidence = max(observations, key=lambda item: dt.datetime.fromisoformat(item["viewed"]), default=None)
    original = job["original_posted_at"]
    label, flags, platform_date = "日期待核实", [], None
    if evidence:
        raw = evidence["label"].strip().lower()
        viewed = dt.datetime.fromisoformat(evidence["viewed"])
        if evidence["kind"] == "Reposted" or "reposted" in raw or "重发" in raw:
            flags.append("重发")
        relative = re.fullmatch(r"(?:reposted\s+)?(\d+)\s*(minute|hour|day|week|month)s? ago", raw)
        upper = None
        if evidence.get("time_basis") == "recorded at intake" and (relative or raw in {"just posted", "today", "yesterday"}):
            flags.append("查看时间待核实")
        elif relative:
            n, unit = int(relative[1]), relative[2]
            if unit != "month":
                seconds = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800}[unit]
                platform_date = viewed.astimezone(dt.timezone.utc) - dt.timedelta(seconds=n*seconds)
                upper = platform_date - dt.timedelta(seconds=seconds)
            else:
                flags.append("日期边界")
        elif raw in {"just posted", "today", "yesterday"}:
            platform_date = viewed - dt.timedelta(days=raw == "yesterday")
            upper = platform_date - dt.timedelta(days=1)
        else:
            try:
                platform_date = dt.date.fromisoformat(raw)
            except ValueError:
                pass
        if isinstance(platform_date, dt.datetime):
            if within_discovery_window(platform_date.isoformat(), clock):
                if upper and within_discovery_window(upper.isoformat(), clock):
                    label = "平台显示近期"
                else:
                    flags.append("日期边界")
            platform_date = platform_date.astimezone(clock.tzinfo).date()
        elif platform_date:
            days = (clock.date() - platform_date).days
            if 0 <= days < 3:
                label = "平台显示近期"
            elif days == 3:
                flags.append("日期边界")
    if original:
        date = dt.datetime.fromisoformat(original).astimezone(clock.tzinfo).date()
        if platform_date and abs((date - platform_date).days) > 1 and "重发" not in flags:
            flags.append("日期证据冲突")
        label = "核实为近期" if within_discovery_window(original, clock) else "超过 72 小时"
    else:
        date = None if "重发" in flags else platform_date
    return {"label": label, "flags": flags, "observation": evidence, "date": date.isoformat() if date else None,
            "official": bool(original)}


def record_observation(store, job_id, data, clock):
    from manual_workflow import job_row

    job = job_row(store, job_id)
    url = canonical(data.get("url") or "")
    if not url or url not in {canonical(link["url"]) for link in job["source_links"] if link["url"]}:
        raise ValueError("Select a source link already attached to this job.")
    state, detail = data.get("state"), data.get("detail", "")
    label, kind = data.get("label", ""), data.get("kind", "Displayed")
    if state not in READ_STATES or not isinstance(detail, str) or not detail.strip() or len(detail) > 2000:
        raise ValueError("Provide the observed result and evidence.")
    if not isinstance(label, str) or len(label) > 500 or kind not in {"Displayed", "Reposted"}:
        raise ValueError("Provide a valid platform date label.")
    viewed = data.get("viewed") or clock.isoformat()
    if not isinstance(viewed, str):
        raise ValueError("Provide the viewing time with a timezone.")
    observed = dt.datetime.fromisoformat(viewed)
    if observed.tzinfo is None or observed > clock:
        raise ValueError("Viewing time must include a timezone and cannot be in the future.")
    with store.connect() as c:
        payload = {"url": url, "state": state, "detail": detail.strip(), "viewed": observed.isoformat()}
        store.event(c, job_id, "Listing read observation", json.dumps(payload))
        if label.strip():
            store.event(c, job_id, "Listing date observed",
                        json.dumps({"url": url, "label": label.strip(), "kind": kind, "viewed": payload["viewed"]}))
    return {"saved": True}


def queues(jobs, clock):
    today = clock.date()
    last_month = today.replace(day=1) - dt.timedelta(days=1)
    month_start = last_month.replace(day=min(today.day, monthrange(last_month.year, last_month.month)[1]))
    groups = {key: [] for key in ("recent", "week", "month", "unknown", "high", "resume")}
    for job in jobs:
        match = job["match"] or {}
        score = match.get("score") or 0
        if score < 60 or not job["jd"] or job["jd"].startswith("[Partial JD]"):
            continue
        signal = job["date_signal"]
        date = dt.date.fromisoformat(signal["date"]) if signal["date"] else None
        if signal["label"] in {"核实为近期", "平台显示近期"} and "重发" not in signal["flags"]:
            groups["recent"].append(job)
        elif date and 0 <= (today-date).days <= 7:
            groups["week"].append(job)
        elif date and month_start <= date <= today:
            groups["month"].append(job)
        elif not date:
            groups["unknown"].append(job)
        if score > 80:
            groups["high"].append(job)
        examples = {}
        for part in match.get("parts", []):
            for item in part["evidence"]:
                for fact in item.get("cv", []):
                    examples.setdefault(fact["id"], fact["text"])
        job["resume_examples"] = list(examples.values())[:3]
        if len(examples) >= 2 and job["country"] in TARGET_MARKETS and any(link["platform"] in {"Greenhouse", "Lever", "Ashby"} for link in job["source_links"]):
            groups["resume"].append(job)
    def ranked(job):
        evidence = job["date_signal"]
        return (evidence["official"], not evidence["flags"], job["match"]["score"],
                job["match"]["eligibility"] == "Verified", evidence["date"] or "")
    return {key: [j["id"] for j in sorted(rows, key=ranked if key != "resume" else
            lambda j: (j["match"]["score"], len(j["resume_examples"])), reverse=True)] for key, rows in groups.items()}


def daily_gap(jobs, groups, submissions):
    from auto_apply import LIMITS

    available = set(groups["recent"] + groups["week"] + groups["month"])
    report = {}
    for platform, limit in LIMITS.items():
        counters = {"岗位不足": 0, "资格待核实": 0, "页面不可读": 0, "待手动完成": 0}
        pool = [job for job in jobs if any(link["platform"] == platform for link in job["source_links"])]
        done = submissions["channels"].get(platform, 0)
        gap = max(0, limit - done)
        for job in pool:
            observed = (json.loads(event["detail"]) for event in job["events"] if event["kind"] == "Listing read observation")
            platform_urls = {canonical(link["url"]) for link in job["source_links"] if link["platform"] == platform and link["url"]}
            observation = next((item for item in observed if item["url"] in platform_urls), None)
            if job["vacancy"] == "Closed" or job["status"] in {"Manually Applied", "Submitted", "Rejected", "Withdrawn"}:
                continue
            reason = None
            if observation and observation["state"] not in {"Readable", "Explicitly closed"}:
                reason = "页面不可读"
            elif job["id"] in available:
                reason = "资格待核实" if job["match"]["eligibility"] != "Verified" else "待手动完成"
            if reason and sum(counters.values()) < gap:
                counters[reason] += 1
        counters["岗位不足"] = gap - sum(counters.values())
        report[platform] = {"limit": limit, "completed": done, "gap": gap, "reasons": counters}
    return report
