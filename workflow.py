"""Manual handoff and pre-submit review. This module never submits applications."""
import json
from core import TARGET_MARKETS, now, stamp
from manual_workflow import job_row

FINISHED = {"Submitted", "Manually Applied", "Interview", "Offer", "Rejected", "Withdrawn", "Closed", "Duplicate"}


def current_documents(job):
    result = {}
    for kind in ("CV", "CL"):
        documents = [doc for doc in job["documents"] if doc["kind"] == kind and doc.get("metadata")]
        result[kind] = documents[0] if documents else None
    return result


def display_state(job):
    record = job.get("application_record")
    if record and record["active"]:
        return "已投递"
    if job["status"] in {"Submitted", "Manually Applied", "Interview", "Offer", "Rejected"} and not (record and not record["active"]):
        return {"Interview": "面试中", "Offer": "已获邀约", "Rejected": "被拒"}.get(job["status"], "已投递")
    if job["vacancy"] == "Closed" or job["status"] == "Closed":
        return "已关闭"
    if job["status"] == "Submission Confirmation Unknown":
        return "提交结果待核实"
    if job["status"] == "Manual Action Required":
        return "需我处理"
    generation = job.get("generation")
    if generation and generation["state"] == "failed":
        return "需我处理"
    docs = current_documents(job)
    if not all(docs.values()):
        return "待生成材料"
    match = job["match"] or {}
    if any(doc["jd_hash"] != match.get("jd_hash") or doc["source_hash"] != match.get("source_hash") for doc in docs.values()):
        return "待生成材料"
    approved = next((json.loads(e["detail"]) for e in job["events"] if e["kind"] == "Materials approved"), None)
    if approved and all(approved.get(kind) == docs[kind]["id"] for kind in docs):
        return "待我投递"
    return "待审核"


def approve_materials(store, job_id, data):
    job = job_row(store, job_id)
    docs = current_documents(job)
    if not all(docs.values()) or any(data.get(kind) != docs[kind]["id"] for kind in docs):
        raise ValueError("请审核当前两份材料，再确认对应版本。")
    review=(docs['CL'].get('metadata') or {}).get('cl_review',{})
    from cl_workflow import POLICY_VERSION, confirmed_facts
    if review.get('policy')!=POLICY_VERSION or review.get('status')!='待我审阅' or review.get('facts_sha256')!=confirmed_facts()['sha256']:
        raise ValueError('求职信尚有未完成的事实核对，请先修订；不能将通用草稿当作完成岗位定制。')
    if job["vacancy"] == "Closed":
        raise ValueError("岗位已关闭。")
    match = job["match"] or {}
    if any(doc["jd_hash"] != match.get("jd_hash") or doc["source_hash"] != match.get("source_hash") for doc in docs.values()):
        raise ValueError("材料已过期，请根据最新 JD 和主简历重新生成。")
    with store.connect() as c:
        store.event(c, job_id, "Materials approved", json.dumps({kind: docs[kind]["id"] for kind in docs}))
    return {"saved": True}


def pilot_review(store, job_id):
    from auto_apply import application_blockers, prior_application
    from matching import candidate
    job = job_row(store, job_id)
    docs = current_documents(job)
    blockers = application_blockers(job, now().date())
    from sponsorship import evidence
    country_profile=store.settings().get('work_authorization_profiles',{}).get(job['country'],{})
    if evidence(job['jd'],country_profile.get('state') in {'Requires sponsorship','Not authorized'})['excluded']:
        blockers.append('本人需要赞助，雇主JD明确不提供赞助。')
    if not all(docs.values()):
        blockers.append("请先生成并审核当前 CV 和求职信。")
    if display_state(job) != "待我投递":
        blockers.append("材料版本尚未审核。")
    if (job.get("platform_application") or {}).get("route") != "On platform" and not any(
            e["kind"] == "Platform shows applications open" and json.loads(e["detail"]).get("route") == "On platform" for e in job["events"]):
        blockers.append("尚未核实为平台内申请。")
    if job["match"] and job["match"].get("source_hash") != candidate()["sha256"]:
        blockers.append("主简历已更新，需重新评分并生成材料。")
    with store.connect() as c:
        if prior_application(c, job):
            blockers.append("该岗位已有已提交或结果未明的申请。")
        profile = store.settings().get("application_profile", {})
        if not profile.get("confirmed") or profile.get("country") != job["country"]:
            blockers.append("个人申请资料与必填问题答案尚未由你确认。")
        record = {"job": job_id, "created": stamp(), "stage": "blocked" if blockers else "awaiting_user_confirmation",
                  "blockers": blockers, "versions": {kind: doc["id"] if doc else None for kind, doc in docs.items()},
                  "answers": profile.get("answers", {}), "live_enabled": False}
        store.event(c, job_id, "Pilot review", json.dumps(record))
        if blockers and job["status"] not in FINISHED and job["status"] != "Submission Confirmation Unknown" and job["vacancy"] != "Closed":
            c.execute("UPDATE jobs SET status='Manual Action Required' WHERE id=?", (job_id,))
    return record


def handoff(store, job_id):
    job = job_row(store, job_id)
    if job["vacancy"] == "Closed":
        raise ValueError("岗位已关闭，不能继续投递。")
    observations = [json.loads(e["detail"]) for e in job["events"] if e["kind"] == "Platform shows applications open"]
    platform = observations[0] if observations else None
    destination = platform["url"] if platform and platform["route"] == "On platform" else job["apply_url"] or job["url"]
    if not destination:
        raise ValueError("缺少可打开的岗位链接，请先核对来源。")
    with store.connect() as c:
        store.event(c, job_id, "Application page opened", destination)
    return {"url": destination}


def save_profile(store, data):
    country, answers = data.get("country"), data.get("answers")
    if country not in TARGET_MARKETS or not isinstance(answers, dict) or data.get("confirmed") is not True:
        raise ValueError("请选择国家，并明确确认个人申请资料。")
    fields = {"name", "email", "phone", "work_authorization", "sponsorship", "salary", "other"}
    if set(answers) != fields or any(not isinstance(v, str) or len(v) > 2000 for v in answers.values()):
        raise ValueError("请核对申请资料字段。")
    if any(not answers[key].strip() for key in ("name", "email", "phone", "work_authorization", "sponsorship")):
        raise ValueError("姓名、联系方式、工作许可和赞助需求需要明确答案。")
    record = {"confirmed": True, "country": country, "answers": answers, "confirmed_at": stamp()}
    with store.connect() as c:
        c.execute("INSERT OR REPLACE INTO settings VALUES('application_profile',?)", (json.dumps(record),))
    return {"saved": True}



def japan_review(job, preferences, sponsorship):
    import re

    checks = (job.get("match") or {}).get("checks") or {}
    blockers = []
    clauses = re.split(r"[;；\n]+", job["jd"])
    required_japanese = (r"日本語.{0,15}(?:必須|母国語|ネイティブ|N[1-3])|"
        r"(?:native.level|business.level|fluent|proficiency|business|fluency) (?:in )?Japanese|"
        r"(?:bilingual|skills in both).{0,40}Japanese|Japanese.{0,35}(?:native|business level|required|fluency)")
    language = next((clause.strip() for clause in clauses
        if re.search(required_japanese, clause, re.I)
        and not re.search(r"preferred|nice to have|a plus|not required|尚可|歓迎", clause, re.I)), "")
    if preferences.get("japanese") == "none" and language:
        blockers.append("JD 明确要求日语：" + language[:300])
    elif checks.get("Languages", {}).get("state") != "Met":
        blockers.append("待我确认 · 岗位工作语言")
    if not job["location"] or checks.get("Location / relocation", {}).get("state") != "Met":
        blockers.append("待我确认 · 实际工作地点及办公安排")
    if preferences.get("work_authorized") is False:
        blockers.append("目前无日本工作许可")
    elif checks.get("Work authorization", {}).get("state") != "Met":
        blockers.append("待我确认 · 日本工作许可")
    if preferences.get("requires_sponsorship") is not False:
        if sponsorship["excluded"]:
            blockers.append("雇主明确不提供签证支持")
        elif not sponsorship["evidence"] or checks.get("Visa sponsorship", {}).get("state") != "Met":
            blockers.append("待我确认 · 雇主签证支持及适用条件")
    return blockers


def application_day(c, day):
    """Count only evidenced submissions, using UTC calendar dates."""
    import datetime as dt
    from core import TZ

    def local_day(value):
        if not value:
            return ""
        instant = dt.datetime.fromisoformat(value)
        return instant.astimezone(TZ).date().isoformat() if instant.tzinfo else instant.date().isoformat()

    groups = {key: [] for key in ("automatic", "manual", "pending", "blocked")}
    decisions = {}

    def put(job, group, when, channel, detail="", cv="", cl="", receipt=""):
        if job not in decisions:
            decisions[job] = (group, dict(job=job, time=when, channel=channel, detail=detail,
                                          cv=cv, cl=cl, receipt=receipt))

    for row in c.execute("SELECT * FROM apply_attempts WHERE state='confirmed' ORDER BY id DESC"):
        if local_day(row["confirmed_at"]) != day or not row["detail"].strip():
            continue
        try:
            proof = json.loads(row["detail"])
        except ValueError:
            proof = {}
        if not isinstance(proof, dict) or not isinstance(proof.get("receipt"), str) or not proof["receipt"].strip():
            put(row["job"], "pending", row["confirmed_at"], row["platform"], "历史自动记录缺少可核实的回执")
        else:
            put(row["job"], "automatic", row["confirmed_at"], row["platform"], cv=proof.get("cv"),
                cl=proof.get("cl"), receipt=proof["receipt"])
    for row in c.execute("SELECT * FROM application_records WHERE active=1 AND date=?", (day,)):
        if decisions.get(row["job"], ("",))[0] == "pending" and row["receipt"].strip():
            del decisions[row["job"]]
        put(row["job"], "manual" if row["receipt"].strip() else "pending", row["submitted_at"],
            row["channel"], "" if row["receipt"].strip() else "已登记手动投递，待补成功凭据",
            row["cv"], row["cl"], row["receipt"])
    # Older website records can have a verified CV-only submission without an
    # application_records row, whose schema requires a cover letter version.
    for row in c.execute("""SELECT e.job,e.created,e.detail FROM events e
        WHERE e.kind='Manually Applied'
        AND NOT EXISTS (SELECT 1 FROM application_records r WHERE r.job=e.job)
        ORDER BY e.rowid DESC"""):
        try:
            record = json.loads(row["detail"])
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("date") != day:
            continue
        receipt = record.get("receipt") or ""
        put(row["job"], "manual" if receipt else "pending", record.get("submitted_at") or row["created"],
            record.get("channel") or "Other", "" if receipt else "已登记手动投递，待补成功凭据",
            record.get("CV"), record.get("CL"), receipt)
    activity = c.execute("""SELECT job,platform,state,created,detail FROM apply_attempts
        WHERE state IN ('reserved','unknown','failed')
        UNION ALL
        SELECT job,'Employer website / ATS','blocked',created,detail FROM events
        WHERE kind='Official pilot blocked' ORDER BY created DESC""").fetchall()
    for row in activity:
        if local_day(row["created"]) == day:
            detail, versions = row["detail"], {}
            if row["state"] == "blocked":
                try:
                    event = json.loads(detail)
                    detail = event["reason"]
                    versions = {key: event.get(key) for key in ("cv", "cl")}
                except (ValueError, KeyError, TypeError, AttributeError):
                    pass
            put(row["job"], "pending" if row["state"] in {"reserved", "unknown"} else "blocked",
                row["created"], row["platform"], detail, **versions)
    for group, row in sorted(decisions.values(), key=lambda item: item[1]["time"], reverse=True):
        job = c.execute("SELECT title,company,country FROM jobs WHERE id=?", (row["job"],)).fetchone()
        if job:
            groups[group].append({**row, **dict(job)})
    return groups
