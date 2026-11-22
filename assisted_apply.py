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
        raise ValueError("请明确确认 Assisted Apply 的浏览器操作说明。")
    with store.connect() as c:
        write_setting(c, MODE, value)
        store.event(c, None, "Application mode changed", value)
    return {"mode": value}


def clean(data, fields):
    if not isinstance(data, dict) or set(data) - set(fields):
        raise ValueError("申请资料含未知字段。")
    if any(not isinstance(v, str) or len(v) > 1500 for v in data.values()):
        raise ValueError("申请资料须为不超过 1500 字的文字。")
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
            raise ValueError("请选择国家并确认资料真实准确。")
        base = clean(data.get("identity", {}), BASE)
        answers = clean(data.get("answers", {}), COUNTRY)
        if any(answers.get(k, "") not in {"", "Yes", "No"} for k in ("work_authorization", "sponsorship")):
            raise ValueError("请选择是、否或待核实。")
        if answers.get("available"):
            dt.date.fromisoformat(answers["available"])
        if base.get("email") and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", base["email"]):
            raise ValueError("请输入有效邮箱。")
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
        reasons.append("提交结果待核实，禁止重投")
    elif duplicate or job["status"] in FINAL:
        reasons.append("已有申请或重复岗位，禁止重投")
    if job["vacancy"] == "Closed":
        reasons.append("岗位已关闭")
    if not jd.strip() or jd.startswith("[Partial JD]"):
        reasons.append("缺完整 JD")
    if not url:
        reasons.append("缺有效申请链接")
    elif kind == "Manual application required":
        reasons.append("其他官网，需人工投递")
    if job["industry"]["state"] != "allowed":
        reasons.append("行业排除或待核实")
    if not job.get("location") or job["country"] not in TARGET_MARKETS:
        reasons.append("工作地点待核实")
    elif p.get("locations"):
        wanted = [norm(part) for part in p["locations"].split(",") if norm(part)]
        if wanted and not any(term in norm(job["location"]) for term in wanted):
            reasons.append("岗位地点不在已确认地点偏好内")
    if p.get("work_authorization") not in {"Yes", "No"}:
        reasons.append("工签状态未知")
    if p.get("sponsorship") not in {"Yes", "No"}:
        reasons.append("是否需要雇主赞助未知")
    if sponsorship_evidence(jd, p.get("sponsorship") == "Yes")["excluded"]:
        reasons.append("岗位明确不提供所需赞助")
    if p.get("work_authorization") == "No" and re.search(
        r"\bmust\s+(?:(?:already|currently)\s+)?(?:be\s+(?:(?:already|currently|legally)\s+)*(?:authorized|eligible)\s+to\s+work|have\s+(?:(?:existing|valid)\s+)?work\s+authori[sz]ation)",
        jd, re.I
    ):
        reasons.append("JD 明确要求已有工作许可")
    for label, check in checks.items():
        if check.get("state") == "Failed":
            reasons.append(label + "：不符合已核实要求")
    if not all(identity.get(k) for k in ("name", "email", "phone")):
        reasons.append("Application Profile 缺姓名、邮箱或电话")
    specific = attempt.get("payload", {}).get("precheck", {})
    if specific.get("salary_required") and not (specific.get("salary") or p.get("salary")):
        reasons.append("This job requires a salary answer")
    if specific.get("address_required") and not (specific.get("address_authorized") and identity.get("address") and identity.get("postal")):
        reasons.append("Address and postal code require job-specific authorization")
    if specific.get("captcha_required") and not specific.get("captcha_cleared"):
        reasons.append("Manual verification required; no bypass")
    if job["status"] == "Manual Action Required":
        reasons.append("现有记录标记为需人工处理")
    if attempt.get("stage") == "Blocked":
        reasons.append(attempt["payload"].get("reason") or "浏览器步骤受阻")
    if generation.get("state") == "failed":
        reasons.append("材料生成失败：" + generation.get("error", "")[:140])
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
            raise ValueError("该岗位已结案或已投递。")
        time = stamp()
        opened, submitted = attempt.get("opened"), attempt.get("submitted")
        if action == "open":
            if setting(c, MODE, "Dry Run") != "Assisted Apply":
                raise ValueError("请先确认切换到 Assisted Apply。")
            if uncertain or prior_application(c, job):
                raise ValueError("该岗位或重复岗位已投递或结果待核实。")
            saved = setting(c, PROFILE, {"identity": {}, "countries": {}})
            reasons = blockers(job, saved, attempt)
            if reasons:
                raise ValueError("；".join(reasons))
            docs = materials(job)
            if not docs.get("CV"):
                raise ValueError("请先生成当前岗位的定制 CV。")
            if data.get("reviewed") is not True:
                raise ValueError("请先复核本岗位、接收方、资料及材料版本。")
            if stage in {"Assisted filling", "Awaiting my confirmation"}:
                raise ValueError("已有打开的申请，请使用原表单。")
            reviewed_profile = {**saved.get("identity", {}), **saved.get("countries", {}).get(job["country"], {})}
            payload = dict(url=url, channel=channel, docs=docs, precheck=payload.get("precheck", {}), profile_hash=hashlib.sha256(
                json.dumps(reviewed_profile, sort_keys=True).encode()).hexdigest())
            stage, opened, submitted = "Assisted filling", time, None
        elif action == "review":
            if stage != "Assisted filling" or uncertain:
                raise ValueError("请先打开当前申请。")
            review_profile = setting(c, PROFILE, {"identity": {}, "countries": {}})
            reviewed_profile = {**review_profile.get("identity", {}), **review_profile.get("countries", {}).get(job["country"], {})}
            revision = hashlib.sha256(json.dumps(reviewed_profile, sort_keys=True).encode()).hexdigest()
            if revision != payload.get("profile_hash") or payload.get("docs") != materials(job) or payload.get("url") != url:
                raise ValueError("资料、材料或申请入口已变化，请重新开启并复核。")
            if data.get("reviewed") is not True:
                raise ValueError("请在浏览器复核实际填写资料与附件后确认。")
            used = data.get("docs", {})
            if not isinstance(used, dict) or used.get("CV") != payload["docs"].get("CV") or any(
                kind not in {"CV", "CL"} or payload["docs"].get(kind) != version for kind, version in used.items()
            ):
                raise ValueError("请选择网站实际使用的 CV 和可选 CL。")
            payload["used_docs"] = used
            stage = "Awaiting my confirmation"
        elif action == "submitted":
            if stage != "Awaiting my confirmation" or uncertain or data.get("confirmed") is not True:
                raise ValueError("仅在你确认已于网站点击提交后记录。")
            stage, submitted = "Submitted", time
            c.execute("UPDATE jobs SET status='Submission Confirmation Unknown' WHERE id=?", (ident,))
        elif action == "precheck":
            if uncertain or data.get("confirmed") is not True or stage in {"Assisted filling", "Awaiting my confirmation"}:
                raise ValueError("请在开启填写前确认该岗位的专属资料。")
            salary = data.get("salary", "")
            if not isinstance(salary, str) or len(salary) > 120:
                raise ValueError("薪资答案无效。")
            payload["precheck"] = dict(salary=salary.strip(), address_authorized=data.get("address_authorized") is True,
                                       captcha_cleared=data.get("captcha_cleared") is True)
            stage = "Reviewed"
        elif action == "blocked":
            if uncertain:
                raise ValueError("该岗位提交结果待核实。")
            reason = str(data.get("reason") or "").strip()[:1000]
            if not reason:
                raise ValueError("请记录验证、缺失答案或其他阻断。")
            stage, payload = "Blocked", {**payload, "reason": reason}
        elif action == "resume":
            if uncertain or stage != "Blocked" or data.get("confirmed") is not True:
                raise ValueError("仅能在确认阻断已解除后恢复。")
            stage, payload = "Reviewed", {"precheck": payload.get("precheck", {})}
        elif action in {"receipt", "requeue"}:
            if not uncertain:
                raise ValueError("此操作仅用于提交结果待核实的记录。")
            proof = str(data.get("proof") or "").strip()[:2000]
            if len(proof) < 8 or data.get("confirmed") is not True:
                raise ValueError("请提供核实依据并确认。")
            payload = {**payload, "url": url, "channel": channel}
            if action == "requeue":
                if data.get("proof_kind") not in {"Platform rejected", "Employer confirmed no application", "Platform confirms no application"}:
                    raise ValueError("缺少招聘系统或雇主明确证实未投的依据。")
                if prior_application(c, job, reconciling=True):
                    raise ValueError("已有平台回执、保留锁或重复申请，不能解除。")
                stage = "Reviewed"
                payload["not_submitted_evidence"] = proof
                submitted = None
                c.execute("UPDATE jobs SET status='Eligibility Review' WHERE id=?", (ident,))
            else:
                proof_kind = data.get("proof_kind")
                if proof_kind not in {"Success page", "Application number", "Confirmation email"}:
                    raise ValueError("成功记录必须有确认页、申请编号或确认邮件。")
                # A resolved record can be old. Never attribute a historic attempt to today implicitly.
                submitted = submitted or data.get("submitted_at")
                try:
                    at = dt.datetime.fromisoformat(submitted)
                    if at.tzinfo is None or at > now():
                        raise ValueError()
                    from core import TZ
                    submitted = at.astimezone(TZ).isoformat()
                except (TypeError, ValueError):
                    raise ValueError("请填写可核实的投递时间（含时区）。") from None
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
                                raise ValueError("材料版本不属于此岗位。")
                            docs[key.upper()] = version
                record = dict(date=submitted[:10], submitted_at=submitted,
                              channel=channel if channel in {"LinkedIn", "Indeed"} else "Employer website / ATS",
                              CV=docs.get("CV"), CL=docs.get("CL"), receipt=proof,
                              discovery_sources=[r["platform"] for r in job["source_links"]])
                c.execute("UPDATE jobs SET status='Manually Applied' WHERE id=?", (ident,))
                store.event(c, ident, "Manually Applied", json.dumps(record, ensure_ascii=False))
                store.event(c, ident, "Manual submission receipt", proof)
        else:
            raise ValueError("未知申请操作。")
        c.execute("""INSERT OR REPLACE INTO assisted_attempts VALUES(?,?,?,?,?,?)""",
                  (ident, stage, time, opened, submitted, json.dumps(payload, ensure_ascii=False)))
        store.event(c, ident, "Assisted Apply " + stage, json.dumps(payload, ensure_ascii=False))
        return dict(stage=stage, url=url, channel=channel, docs=payload.get("docs", {}))
