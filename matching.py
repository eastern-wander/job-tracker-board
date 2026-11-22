import io
from contextlib import nullcontext
import json
import re
import uuid

from core import TARGET_MARKETS, MAIN, hashlib, norm, stamp
from industry import CRYPTO, require_allowed

GROUPS = {
    "Functional responsibilities": (30, ["operations", "partnerships", "project", "stakeholder", "business development", "client", "supplier", "contract", "campaign", "research"]),
    "Transferable experience": (20, ["cross border", "coordination", "negotiation", "vendor", "logistics", "delivery", "onboarding", "budget", "compliance", "due diligence"]),
    "Skills and tools": (20, ["excel", "sql", "tableau", "crm", "bi", "agile", "scrum", "analytics", "commercial analysis", "hubspot", "salesforce", "competitive analysis"]),
    "Industry relevance": (10, ["web3", "trading", "investment", "real estate", "consulting", "tourism", "travel", "decentralised exchange", "adtech", "programmatic advertising", "payments", "brokerage", "fintech", "logistics"]),
    "Seniority": (10, []),
    "Location and working arrangement": (10, []),
}
WORK_AUTHORIZATION = "Work authorization"
SPONSORSHIP = "Visa sponsorship"
EMPLOYER_RESTRICTIONS = "Employer-specific restrictions"
SCREEN = {
    WORK_AUTHORIZATION: r"authori[sz]|right to work|work permit|work eligibility",
    SPONSORSHIP: r"sponsor|visa|work permit",
    EMPLOYER_RESTRICTIONS: r"citizen|nationals? only|emirati|security clearance|residency|local hire",
    "License / certification": r"licen[sc]e|certifi|pmp|cpa|cfa",
    "Languages": r"language|bilingual|fluen|mandarin|arabic|french|japanese|english|日本語|英語",
    "Technical requirements": r"proficien|expertise|required|must have|essential|mandatory",
    "Experience": r"\d+\s*\+?\s*(?:years|yrs)|senior|director|leadership",
    "Location / relocation": r"relocat|on.site|hybrid|remote|based in|勤務地|在宅|出社",
}


def candidate(raw=None):
    from pypdf import PdfReader
    raw = MAIN.read_bytes() if raw is None else raw
    sections = {}
    current = None
    source_pages = {}
    for page_no, page in enumerate(PdfReader(io.BytesIO(raw)).pages, 1):
      for line in (page.extract_text() or "").splitlines():
        line = line.strip()
        heading = " ".join(line.split())
        source_pages.setdefault(line, page_no)
        if heading in {"SUMMARY", "EDUCATION", "PROFESSIONAL EXPERIENCE", "ENTREPRENEURIAL PROJECT", "SKILLS"}:
            current = heading
        elif line:
            sections.setdefault(current, []).append(line)
    if not all(sections.get(k) for k in (None, "SUMMARY", "EDUCATION", "PROFESSIONAL EXPERIENCE", "SKILLS")):
        raise ValueError("Main CV text could not be parsed safely.")
    facts, roles = [], []
    def fact(kind, value, role=None):
        row = {"id": f"F{len(facts)+1:03}", "kind": kind, "text": value, "role": role,
               "page": next((p for line, p in source_pages.items() if line and
                             (value.startswith(line) or line.lstrip("• ").startswith(value.splitlines()[0])
                              or (kind == "Skill" and value in line.split(", ") and line in sections["SKILLS"]))), None)}
        facts.append(row)
        return row
    summary = fact("Summary", " ".join(sections["SUMMARY"]))
    education = fact("Education", "\n".join(sections["EDUCATION"]))
    skills = [fact("Skill", x.strip()) for x in " ".join(sections["SKILLS"]).split(",") if x.strip()]
    for section in ("PROFESSIONAL EXPERIENCE", "ENTREPRENEURIAL PROJECT"):
        role = None
        bullet = None
        for line in sections.get(section, []):
            if "|" in line and not line.startswith(("", "•")):
                role = fact("Role", line)
                roles.append(role)
                bullet = None
            elif line.startswith(("", "•")) and role:
                bullet = fact("Achievement / responsibility", line[1:].strip(), role["id"])
            elif bullet:
                bullet["text"] += (" " if not bullet["text"].endswith("-") else "") + line
    if len(roles) < 4 or not any(f["role"] for f in facts):
        raise ValueError("Main CV employment history could not be parsed safely.")
    return {"sha256": hashlib.sha256(raw).hexdigest(), "identity": sections[None][:2], "summary": summary,
            "education": education, "skills": skills, "roles": roles, "facts": facts, "languages": "Unverified"}


def contains(text, term):
    aliases = {"partnerships": r"partnerships?", "project": r"projects?", "client": r"clients?",
               "supplier": r"suppliers?", "stakeholder": r"stakeholders?",
               "negotiation": r"negotiat(?:ion|ions|e|ed|ing)", "coordination": r"coordinat(?:ion|e|ed|ing)",
               "vendor": r"vendors?", "contract": r"contracts?", "campaign": r"campaigns?",
               "bi": r"bi|business intelligence", "analytics": r"analytics|data analysis",
               "adtech": r"adtech|ad tech", "web3": r"web3|web 3",
               "decentralised exchange": r"decentrali[sz]ed exchanges?",
               "competitive analysis": r"competitive analysis|benchmark\w* competitor"}
    return bool(re.search(r"\b(?:" + aliases.get(term, re.escape(term)) + r")\b", text))


MATCH_EXECUTION = {"implementation": "Local keyword and CV-evidence matching", "model": None, "reasoning_effort": None}
MATERIAL_EXECUTION = {"implementation": "Local verified-fact selection and ReportLab templates", "model": None,
                      "reasoning_effort": None}


def extract_jd_sections(jd):
    sections = {"responsibilities": [], "mandatory_requirements": [], "preferred_requirements": []}
    headings = {
        "responsibilities": r"(?:key |core |main |job )?responsibilities|duties|what you(?:'ll| will) do",
        "mandatory_requirements": r"(?:basic|required|minimum|mandatory) (?:qualifications|requirements)|must have",
        "preferred_requirements": r"(?:preferred|desired) (?:qualifications|requirements)|nice to have|bonus points",
    }
    current = ""
    for paragraph in jd.splitlines():
        line = paragraph.strip(" •-–	")
        if not line:
            continue
        label, separator, remainder = line.partition(":")
        heading = next((name for name, pattern in headings.items()
                        if re.fullmatch(pattern, label, re.I)), "")
        if heading:
            current = heading
            line = remainder.strip() if separator else ""
        elif re.fullmatch(r"about (?:us|you|the company)|benefits|compensation|how to apply|qualifications|requirements", label, re.I):
            current = ""
            continue
        if not line:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if re.search(r"\b(?:preferred|a plus|nice to have|desirable|an asset)\b", sentence, re.I):
                target = "preferred_requirements"
            elif re.search(r"\b(?:required|must|mandatory|minimum)\b", sentence, re.I):
                target = "mandatory_requirements"
            else:
                target = current
            if target and sentence[:600] not in sections[target] and len(sections[target]) < 20:
                sections[target].append(sentence[:600])
    return sections


def analyze(job, profile, checks=None, *, preview_industry=False):
    from industry import classify
    if not preview_industry or classify(job)["state"] == "excluded":
        require_allowed(job)
    jd = job.get("jd") or ""
    title = norm(job["title"])
    subject = norm(jd)
    lines = [x.strip() for x in re.split(r"\n+|(?<=[.!?])\s+", jd) if x.strip()]
    facts = profile["facts"]
    parts, gaps = [], []
    complete = bool(jd.strip()) and not jd.startswith("[Partial JD]")
    for name, (weight, terms) in GROUPS.items():
        evidence = []
        diagnostic = None
        if terms:
            for term in terms:
                if contains(subject, term):
                    hits = [f for f in facts if contains(norm(f["text"]), term)]
                    if hits:
                        evidence.append({"keyword": term, "facts": [f["id"] for f in hits[:3]],
                                         "jd": next((x for x in lines if contains(norm(x), term)), "")[:600],
                                         "cv": [{"id": f["id"], "page": f["page"], "text": f["text"]} for f in hits[:2]],
                                         "reason": "The same responsibility, tool or industry term appears in the source CV."})
                    else:
                        gaps.append(term)
            requested = sum(contains(subject, term) for term in terms)
            denominator = max(requested, 3 if weight >= 30 else 1)
            points = round(weight * len(evidence) / denominator)
            requested_terms = [term for term in terms if contains(subject, term)]
            matched_terms = [entry["keyword"] for entry in evidence]
            diagnostic = {
                "requested_terms": requested_terms, "matched_terms": matched_terms,
                "unmatched_terms": [term for term in requested_terms if term not in matched_terms],
                "denominator": denominator,
                "basis": "No recognized JD terms; zero is not evidence of missing qualifications"
                         if not requested_terms else "Recognized JD terms matched to verified CV facts",
                "formula": f"round({weight} * {len(evidence)} / {denominator})",
            }
        elif name == "Seniority":
            junior = bool(re.search(r"\b(coordinator|associate|assistant|specialist|analyst)\b", title))
            senior = bool(re.search(r"\b(senior|director|head|principal|lead)\b", title))
            points = 8 if junior and not senior else 2 if senior else 5
            evidence = [{"keyword": "Title-based estimate; verify scope and years", "facts": [r["id"] for r in profile["roles"]]}]
        else:
            points = 10 if job["country"] in TARGET_MARKETS else 0
            evidence = [{"keyword": job["country"] + " matches target market, not work authorization", "facts": []}] if points else []
        part = {"name": name, "weight": weight, "points": points, "evidence": evidence}
        if diagnostic is not None:
            part["diagnostic"] = diagnostic
        parts.append(part)
    screening = {}
    for name, pattern in SCREEN.items():
        check = (checks or {}).get(name, {})
        state, reason = check.get("state"), check.get("reason", "")
        allowed_states = {"Met", "Failed"} if name == WORK_AUTHORIZATION else {"Met", "Failed", "Not required"}
        if state not in allowed_states or not isinstance(reason, str) or not reason.strip():
            state, reason = "Unverified", ""
        screening[name] = {"state": state, "reason": reason, "jd": [x.strip()[:500] for x in lines if re.search(pattern, x, re.I)][:5]}
    states = {x["state"] for x in screening.values()}
    eligibility = "Failed" if "Failed" in states else "Unverified" if "Unverified" in states or not complete else "Verified"
    if not complete:
        gaps.append("Full JD required")
    sections = extract_jd_sections(jd) if complete else {}
    qualifications = [x[:600] for x in lines if re.search(r"\b(required|must|qualifications?|experience|preferred|degree|proficien\w*)\b", x, re.I)]
    duties = [x[:600] for x in lines if any(contains(norm(x), term) for term in GROUPS["Functional responsibilities"][1])]
    return {"score": sum(p["points"] for p in parts) if complete else None, "parts": parts,
            "gaps": sorted(set(gaps)), "eligibility": eligibility, "checks": screening,
            "requirements": qualifications[:20], "responsibilities": sections.get("responsibilities") or duties[:20],
            "mandatory_requirements": sections.get("mandatory_requirements", []),
            "preferred_requirements": sections.get("preferred_requirements", []),
            "jd_status": "Complete" if complete else "Needs complete JD", "execution": MATCH_EXECUTION,
            "source_hash": profile["sha256"], "jd_hash": hashlib.sha256(jd.encode()).hexdigest(),
            "method": "Explainable keyword overlap; not a hiring probability"}


def persist_match(store, job, result, *, advance=True):
    with store.connect() as c:
        jd = c.execute("SELECT jd FROM snapshots WHERE job=? ORDER BY rowid DESC LIMIT 1", (job["id"],)).fetchone()
        if (jd[0] if jd else None) != job["jd"]:
            raise ValueError("JD changed during analysis. Retry.")
        current = c.execute("SELECT match FROM jobs WHERE id=?", (job["id"],)).fetchone()
        if current and current[0] and json.loads(current[0]) == result:
            return
        c.execute("UPDATE jobs SET match=? WHERE id=?", (json.dumps(result), job["id"]))
        store.event(c, job["id"], "Scored", str(result["score"]))
        if advance and result["score"] is not None:
            status = "Eligibility Review" if result["eligibility"] != "Verified" else "Scored"
            changed = c.execute("UPDATE jobs SET status=? WHERE id=? AND status='Discovered'", (status, job["id"]))
            if changed.rowcount and status != "Scored":
                store.event(c, job["id"], status, "Mandatory checks require review")


def make_document(store, job, kind="CV", *, manual=False, regenerate=False, model_plan=None, connection=None):
    require_allowed(job)
    from html import escape
    from pypdf import PdfReader
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph

    profile = candidate()
    if kind == 'CL':
        from cl_workflow import cl_profile
        profile = cl_profile(profile)
    match = job["match"]
    if not match or match["source_hash"] != profile["sha256"] or match["score"] is None or (
            not manual and (match["eligibility"] == "Failed" or match["score"] < store.settings()["pending"])):
        raise ValueError("A current qualifying match without a hard failure is required.")
    if not manual and job["vacancy"] == "Closed":
        raise ValueError("Vacancy is closed.")
    with nullcontext(connection) if connection is not None else store.connect() as c:
        existing = c.execute("""SELECT d.id FROM documents d JOIN jobs j ON j.id=d.job
            WHERE j.id=? AND d.kind=? AND d.source_hash=? AND d.jd_hash=? AND j.match=? AND j.vacancy<>'Closed' AND d.mapping<>'[]'
            ORDER BY d.rowid DESC LIMIT 1""",
            (job["id"], kind, profile["sha256"], match["jd_hash"], json.dumps(match))).fetchone()
        if existing and kind=='CL':
            from cl_workflow import POLICY_VERSION, confirmed_facts
            cached=c.execute('SELECT metadata FROM document_assets WHERE document=?',(existing[0],)).fetchone()
            reviewed=json.loads(cached[0]).get('cl_review',{}) if cached else {}
            if reviewed.get('policy')!=POLICY_VERSION or reviewed.get('facts_sha256')!=confirmed_facts()['sha256']:
                existing=None
        if existing and not regenerate:
            return existing[0]
    jd = norm(job["jd"])
    words = set(jd.split()) - set("this that with from your will have role team work and the for you are our of to in".split())
    bullets = [f for f in profile["facts"] if f["role"]]
    def relevance(fact):
        return len(words.intersection(norm(fact["text"]).split()))
    bullets.sort(key=lambda fact: relevance(fact) - 3 * bool(re.search(r"\b(?:" + CRYPTO + r")\b", fact["text"], re.I)), reverse=True)
    def concise(fact):
        original = fact["text"]
        sentences = re.split(r"(?<=\.)\s+", original)
        if len(sentences) > 1 and len(original) > 220 and not re.search(r"\d", " ".join(sentences[1:])):
            if relevance({"text": sentences[0]}) >= relevance({"text": " ".join(sentences[1:])}):
                return sentences[0]
        return original
    skills = sorted(profile["skills"], key=relevance, reverse=True)
    if model_plan:
        order = model_plan["cv_facts" if kind == "CV" else "cl_facts"]
        by_id = {fact["id"]: fact for fact in profile["facts"]}
        bullets = [by_id[key] for key in order]
        if kind == "CV":
            skills = [by_id[key] for key in model_plan["cv_skills"]]
    summary = re.split(r"(?<=\.)\s", profile["summary"]["text"], maxsplit=1)[0]
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=13, spaceAfter=5)
    heading = ParagraphStyle("heading", parent=body, fontName="Helvetica-Bold", spaceBefore=7)
    name = ParagraphStyle("name", parent=heading, fontSize=18, leading=22)
    def render(limit):
        chosen = bullets[:limit]
        mapping = []
        story = []
        def add(value, style=body, refs=()):
            story.append(Paragraph(escape(value.replace("（", "(").replace("）", ")")).replace("\n", "<br/>"), style))
            if refs:
                mapping.append({"text": value, "facts": list(refs)})
        add(profile["identity"][0], name)
        if len(profile["identity"]) > 1:
            add(profile["identity"][1])
        if kind == "CL" and model_plan and model_plan.get("letter"):
            add("Application: " + job["title"] + " | " + job["company"], heading)
            add("Dear Hiring Team,")
            letter_style = ParagraphStyle("letter", parent=body, fontSize=12, leading=18, spaceAfter=15)
            for paragraph in model_plan["letter"]:
                add(paragraph["text"], letter_style, paragraph["refs"])
            add("Kind regards,\n" + profile["identity"][0])
        elif kind == "CL":
            add("Application: " + job["title"] + " | " + job["company"], heading)
            add("Dear Hiring Team,")
            add("I am applying for the " + job["title"] + " position at " + job["company"] + ".")
            if model_plan and model_plan["focus"]:
                add("One responsibility that draws me to this role is: " + model_plan["focus"])
            add(summary, refs=[profile["summary"]["id"]])
            for f in chosen[:2]:
                add(f["text"], refs=[f["id"], f["role"]])
            add("I would welcome the opportunity to discuss how this experience could contribute to your team.")
            add("Kind regards,\n" + profile["identity"][0])
        else:
            add("SUMMARY", heading)
            focus = (skills if model_plan else [s for s in skills if relevance(s)])[:3]
            value = summary + (" Relevant skills: " + "; ".join(s["text"] for s in focus) + "." if focus else "")
            add(value, refs=[profile["summary"]["id"]] + [s["id"] for s in focus])
            add("EXPERIENCE", heading)
            roles = profile["roles"]
            if model_plan:
                role_order = list(dict.fromkeys(fact["role"] for fact in chosen))
                roles = [by_id[key] for key in role_order]
            for role in roles:
                relevant = [f for f in chosen if f["role"] == role["id"]]
                if relevant:
                    add(role["text"], heading, [role["id"]])
                    for f in relevant:
                        add("• " + concise(f), refs=[f["id"]])
            add("EDUCATION", heading)
            add(profile["education"]["text"], refs=[profile["education"]["id"]])
            add("SKILLS", heading)
            if skills:
                add(" | ".join(s["text"] for s in skills), refs=[s["id"] for s in skills])
        output = io.BytesIO()
        long_letter = kind == "CL" and model_plan and model_plan.get("letter")
        SimpleDocTemplate(output, leftMargin=66 if long_letter else 43, rightMargin=66 if long_letter else 43,
                          topMargin=50 if long_letter else 35, bottomMargin=45 if long_letter else 35,
                          title=profile["identity"][0] + " - " + kind).build(story)
        return output.getvalue(), mapping
    planned_text = bool(model_plan and model_plan.get("letter"))
    docx_data, asset_metadata = None, None
    if kind == "CV":
        from resume_template import render as render_template
        selected = model_plan if planned_text else {
            "local_source": True,
            "resume_summary": re.split(r"(?<=\.)\s", profile["summary"]["text"])[0],
            "resume_bullets": [{"id": fact["id"], "text": fact["text"],
                                "compact": " ".join(fact["text"].split()[:16]).rstrip(",;") + ("." if not fact["text"].split()[:16][-1].endswith(".") else "")}
                               for fact in profile["facts"] if fact["role"]],
            "cv_facts": [fact["id"] for fact in bullets[:8]],
        }
        pdf, applied_bullets, docx_data, asset_metadata = render_template(profile, selected, with_source=True)
        mapping = [{"text": row["text"], "facts": [row["id"]]} for row in applied_bullets]
    else:
        for limit in range(2, 0, -1):
            pdf, mapping = render(limit)
            reader = PdfReader(io.BytesIO(pdf))
            if len(reader.pages) == 1 and len(reader.pages[0].extract_text() or "") > 100:
                break
        else:
            raise ValueError("Unable to render a readable one-page PDF.")
    by_id = {fact["id"]: fact["text"] for fact in profile["facts"]}
    for line in mapping:
        refs = line["facts"]
        if not refs or any(ref not in by_id for ref in refs):
            raise ValueError("Invalid source-fact mapping.")
        source = " ".join(by_id[ref] for ref in refs)
        tokens = re.findall(r"\d+(?:[.,]\d+)*", line["text"])
        if any(token not in re.findall(r"\d+(?:[.,]\d+)*", source) for token in tokens):
            raise ValueError("A generated number or date is not supported by the Main CV.")
        expected = by_id[refs[0]]
        rendered = line["text"].removeprefix("• ")
        short_bullet = line["text"].startswith("• ") and rendered == concise({"text": expected})
        if kind != "CV" and not planned_text and len(refs) == 1 and rendered != expected and line["text"] != summary and not short_bullet:
            raise ValueError("Generated text does not match its verified fact.")
    if kind=='CL' and asset_metadata is None:
        from cl_workflow import POLICY_VERSION, confirmed_facts
        asset_metadata={'template':POLICY_VERSION,'cl_review':{'policy':POLICY_VERSION,'status':'草稿／待核实',
            'tailored':False,'translation_zh':[],'requirements':[], 'facts_sha256':confirmed_facts()['sha256'],
            'unverified':['本地模板草稿尚未完成岗位事实审核'], 'resume_sha256':profile['sha256']}}
    doc = uuid.uuid4().hex
    with nullcontext(connection) if connection is not None else store.connect() as c:
        if connection is None:
            c.execute("BEGIN IMMEDIATE")
        latest = c.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
        if not latest or (not manual and latest["vacancy"] == "Closed") or json.loads(latest["match"] or "null") != match:
            raise ValueError("Job changed during generation. Reopen and retry.")
        require_allowed({**dict(latest), "jd": job["jd"]})
        existing = c.execute("""SELECT id FROM documents WHERE job=? AND kind=? AND source_hash=? AND jd_hash=? AND mapping<>'[]'
                                ORDER BY rowid DESC LIMIT 1""",
                             (job["id"], kind, profile["sha256"], match["jd_hash"])).fetchone()
        if existing and kind=='CL':
            from cl_workflow import POLICY_VERSION, confirmed_facts
            cached=c.execute('SELECT metadata FROM document_assets WHERE document=?',(existing[0],)).fetchone()
            reviewed=json.loads(cached[0]).get('cl_review',{}) if cached else {}
            if reviewed.get('policy')!=POLICY_VERSION or reviewed.get('facts_sha256')!=confirmed_facts()['sha256']:
                existing=None
        if existing and not regenerate:
            return existing[0]
        c.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)",
                  (doc, job["id"], stamp(), kind, profile["sha256"], json.dumps(mapping), pdf, match["jd_hash"]))
        if asset_metadata:
            import hashlib
            asset_metadata.update(pdf_sha256=hashlib.sha256(pdf).hexdigest(), created=stamp(),
                                  generator="high" if planned_text else "原简历原文")
            c.execute("INSERT INTO document_assets VALUES(?,?,?)", (doc, docx_data, json.dumps(asset_metadata)))
        store.event(c, job["id"], kind + " generated", doc)
        if kind == "CV" and not manual:
            changed = c.execute("""UPDATE jobs SET status='CV Ready' WHERE id=?
                    AND status IN ('Discovered','Scored','Eligibility Review','Pending Review')""", (job["id"],))
            if changed.rowcount:
                store.event(c, job["id"], "CV Ready", doc)
    return doc
