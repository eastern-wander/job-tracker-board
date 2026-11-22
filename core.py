import csv
import datetime as dt
import hashlib
import io
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo
from industry import classify
import runtime_config
from product_policy import DEFAULTS as PRODUCT_DEFAULTS

ROOT = Path(__file__).resolve().parent
MAIN = runtime_config.resume_pdf()
TZ = ZoneInfo("UTC")
TARGET_MARKETS = ("Canada", "United States", "Japan", "UAE", "UK")
DEFAULT = {"canada": 10, "uae": 10, "days": 30, "high": 80, "pending": 75,
           "boards": "",
           "lever_boards": "",
           "saved": 60, "schedule": "09:00", "locations": "",
           "roles": "Operations Coordinator"}
DEFAULT.update(PRODUCT_DEFAULTS)
STATES = ("Discovered", "Saved", "CV Ready", "Pending Review", "Ready to Apply", "Manual Action Required",
          "Submitted", "Interview", "Offer", "Rejected", "Withdrawn", "Closed", "Scored", "Eligibility Review",
          "Not Interested", "Duplicate", "Application Failed", "Submission Confirmation Unknown", "Manually Applied")
SCHEMA = """
CREATE TABLE jobs(id TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT NOT NULL, location TEXT NOT NULL,
 country TEXT NOT NULL, vacancy TEXT NOT NULL, first_seen TEXT NOT NULL, posted TEXT, salary TEXT, arrangement TEXT,
 apply_url TEXT, requisition TEXT, status TEXT NOT NULL, notes TEXT NOT NULL, match TEXT);
CREATE TABLE sources(job TEXT NOT NULL REFERENCES jobs(id), platform TEXT NOT NULL, external_id TEXT, url TEXT,
 UNIQUE(platform, external_id), UNIQUE(url));
CREATE TABLE snapshots(job TEXT NOT NULL REFERENCES jobs(id), captured TEXT NOT NULL, jd TEXT NOT NULL);
CREATE TABLE documents(id TEXT PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs(id), created TEXT NOT NULL,
 kind TEXT NOT NULL, source_hash TEXT NOT NULL, mapping TEXT NOT NULL, pdf BLOB NOT NULL);
CREATE TABLE events(job TEXT REFERENCES jobs(id), created TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE runs(id TEXT PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL, result TEXT NOT NULL);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
PRAGMA user_version = 1;
"""


def now():
    return dt.datetime.now(TZ)


def stamp():
    return now().isoformat(timespec="seconds")


def norm(value):
    return " ".join(re.findall(r"\w+", value.casefold()))


def canonical(value):
    if not value:
        return None
    u = urlsplit(value)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("Use a valid HTTP(S) URL without credentials.")
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"trk", "trackingid", "refid", "fbclid"}]
    return urlunsplit((u.scheme, u.netloc.lower(), u.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def within_discovery_window(timestamp, clock, hours=72):
    if not timestamp:
        return False
    try:
        posted = dt.datetime.fromisoformat(timestamp)
    except (ValueError, TypeError):
        return False
    if posted.tzinfo is None:
        return False
    age = clock.astimezone(dt.timezone.utc) - posted.astimezone(dt.timezone.utc)
    return dt.timedelta(0) <= age <= dt.timedelta(hours=hours)


def within_application_window(posted, today):
    return bool(posted and 0 <= (today - dt.date.fromisoformat(posted)).days < 14)


ALERT_PLATFORMS = ("LinkedIn", "Indeed")
PLATFORM_DATE_LABELS = {"Displayed": "Platform Date — Original Unverified",
                        "Reposted": "Platform Repost — Original Unverified",
                        "Last published": "Platform Last Published — Original Unverified"}


def platform_date_label(kind, evidence):
    if not kind and not evidence:
        return ""
    if kind not in PLATFORM_DATE_LABELS or not evidence:
        raise ValueError("Provide the platform date type and its displayed evidence.")
    return PLATFORM_DATE_LABELS[kind]


def alert_needs_review(job):
    return job.get("source") in ALERT_PLATFORMS and (
        not job["posted"] or not job["location"] or job["company"] == "Employer unverified"
        or not job.get("jd") or job["jd"].startswith("[Partial JD]")
    )


class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = self.folder / "tracker.sqlite3"
        with self.connect() as c:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                c.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
                version = 1
            if version == 1:
                c.executescript("""BEGIN IMMEDIATE;
                  ALTER TABLE sources ADD COLUMN original_url TEXT;
                  ALTER TABLE documents ADD COLUMN jd_hash TEXT;
                  PRAGMA user_version=2;
                  COMMIT;""")
                version = 2
            if version == 2:
                c.executescript("""BEGIN IMMEDIATE;
                  ALTER TABLE jobs ADD COLUMN industry_declared TEXT;
                  CREATE TABLE exclusions(fingerprint TEXT PRIMARY KEY, created TEXT NOT NULL, reason TEXT NOT NULL);
                  PRAGMA user_version=3;
                  COMMIT;""")
                version = 3
            if version == 3:
                c.executescript("""BEGIN IMMEDIATE;
                  CREATE TABLE email_processed(mailbox TEXT NOT NULL, message TEXT NOT NULL,
                    processed TEXT NOT NULL, PRIMARY KEY(mailbox,message));
                  PRAGMA user_version=4;
                  COMMIT;""")
                version = 4
            if version == 4:
                c.executescript("""BEGIN IMMEDIATE;
                  ALTER TABLE jobs ADD COLUMN employment_type TEXT;
                  PRAGMA user_version=5;
                  COMMIT;""")
                version = 5
            if version == 5:
                c.executescript("""BEGIN IMMEDIATE;
                  CREATE TABLE apply_attempts(id INTEGER PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs(id),
                    platform TEXT NOT NULL CHECK(platform IN ('LinkedIn','Indeed')),
                    state TEXT NOT NULL CHECK(state IN ('reserved','unknown','confirmed','failed','manual')),
                    created TEXT NOT NULL, confirmed_at TEXT, detail TEXT NOT NULL);
                  CREATE INDEX apply_platform_state ON apply_attempts(platform,state);
                  PRAGMA user_version=6;
                  COMMIT;""")
                version = 6
            if version == 6:
                c.executescript("""BEGIN IMMEDIATE;
                  ALTER TABLE jobs ADD COLUMN original_posted_at TEXT;
                  ALTER TABLE jobs ADD COLUMN platform_posted_at TEXT;
                  ALTER TABLE jobs ADD COLUMN last_published_at TEXT;
                  ALTER TABLE jobs ADD COLUMN last_seen TEXT;
                  ALTER TABLE jobs ADD COLUMN date_evidence TEXT;
                  UPDATE jobs SET last_seen=first_seen;
                  PRAGMA user_version=7;
                  COMMIT;""")
                version = 7
            if version == 7:
                c.executescript("""BEGIN IMMEDIATE;
                  CREATE TABLE document_assets(document TEXT PRIMARY KEY REFERENCES documents(id),
                    docx BLOB, metadata TEXT NOT NULL);
                  CREATE TABLE application_records(job TEXT PRIMARY KEY REFERENCES jobs(id),
                    date TEXT NOT NULL, submitted_at TEXT NOT NULL, channel TEXT NOT NULL,
                    cv TEXT NOT NULL REFERENCES documents(id), cl TEXT NOT NULL REFERENCES documents(id),
                    receipt TEXT NOT NULL, notes TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
                  CREATE TABLE generation_jobs(job TEXT PRIMARY KEY REFERENCES jobs(id),
                    state TEXT NOT NULL, started TEXT NOT NULL, finished TEXT, error TEXT NOT NULL);
                  PRAGMA user_version=8;
                  COMMIT;""")
                version = 8
            if version == 8:
                c.executescript("""BEGIN IMMEDIATE;
                  CREATE TABLE assisted_attempts(
                    job TEXT PRIMARY KEY REFERENCES jobs(id), stage TEXT NOT NULL,
                    updated TEXT NOT NULL, opened TEXT, submitted TEXT, payload TEXT NOT NULL);
                  CREATE TABLE intake_backlog(
                    canonical TEXT PRIMARY KEY, url TEXT NOT NULL, reason TEXT NOT NULL,
                    created TEXT NOT NULL, updated TEXT NOT NULL);
                  PRAGMA user_version=9;
                  COMMIT;""")
            elif version != 9:
                raise ValueError("Unsupported database version")
            from cv_queue import initialize
            initialize(c)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            with c:
                yield c
        finally:
            c.close()

    def settings(self):
        with self.connect() as c:
            return {**DEFAULT, **{r["key"]: json.loads(r["value"]) for r in c.execute("SELECT * FROM settings")}}

    def jobs(self):
        from career_families import classify_roles
        with self.connect() as c:
            rows = [dict(r) for r in c.execute("""SELECT jobs.*,
              (SELECT jd FROM snapshots WHERE job=jobs.id ORDER BY rowid DESC LIMIT 1) AS jd,
              (SELECT platform FROM sources WHERE job=jobs.id ORDER BY rowid LIMIT 1) AS source,
              (SELECT COALESCE(original_url,url) FROM sources WHERE job=jobs.id ORDER BY rowid LIMIT 1) AS url
              FROM jobs ORDER BY first_seen DESC""")]
            for row in rows:
                row["source_links"] = [dict(link) for link in c.execute(
                    "SELECT platform, external_id, COALESCE(original_url,url) AS url FROM sources WHERE job=? ORDER BY rowid",
                    (row["id"],))]
                row["date_confidence"] = ("Verified original timestamp" if row["original_posted_at"] else
                                          "Date only" if row["posted"] else "Original unverified")
                row["industry"] = classify(row)
                row["career_families"] = classify_roles(row["title"], row["jd"])
                row["match"] = json.loads(row["match"]) if row["match"] else None
                row["documents"] = [dict(r) for r in c.execute(
                    "SELECT d.id,d.kind,d.created,d.source_hash,d.jd_hash,a.metadata FROM documents d LEFT JOIN document_assets a ON a.document=d.id WHERE d.job=? ORDER BY d.rowid DESC", (row["id"],))]
                for doc in row["documents"]:
                    doc["metadata"] = json.loads(doc["metadata"]) if doc["metadata"] else None
                generation = c.execute("SELECT * FROM generation_jobs WHERE job=?", (row["id"],)).fetchone()
                row["generation"] = dict(generation) if generation else None
                application = c.execute("SELECT * FROM application_records WHERE job=?", (row["id"],)).fetchone()
                row["application_record"] = dict(application) if application else None
                row["events"] = [dict(r) for r in c.execute(
                    "SELECT created,kind,detail FROM events WHERE job=? ORDER BY rowid DESC", (row["id"],))]
                row["manual_import"] = next((e["created"] for e in row["events"] if e["kind"] == "Manually imported"), None)
                row["legacy_import"] = not row["manual_import"] and row["source"] in {"Manual", "LinkedIn", "Indeed"}
                row["tailored_fit"] = next((assessment for event in row["events"] if event["kind"] == "Tailored CV fit"
                                            for assessment in (json.loads(event["detail"]),)
                                            if (row["match"] or {}).get("jd_hash") == assessment["jd_hash"]
                                            and row["match"]["source_hash"] == assessment["main_cv_hash"]), None)
            return rows

    def ingest(self, item, *, new_only=False, aliases=(), enrich_id=None, link_id=None, manual_import=False, edit_id=None):
        def get(key, maxlen=500):
            value = item.get(key, "")
            if not isinstance(value, str) or len(value) > maxlen:
                raise ValueError("Invalid " + key)
            return value.strip()
        title, company, location = (get(k) for k in ("title", "company", "location"))
        if not title or not company:
            raise ValueError("Title and company are required.")
        platform = get("source") or "Manual"
        original = get("url", 3000)
        url, apply = canonical(original), canonical(get("apply_url", 3000))
        ext, req = get("external_id") or None, get("requisition") or None
        if not ext and url:
            if re.fullmatch(r"(?:[\w-]+\.)*linkedin\.com", urlsplit(url).hostname or ""):
                found = re.search(r"/jobs/view/(?:[^/]*-)?(\d+)(?:/|$)", urlsplit(url).path)
                ext = found[1] if found else None
            elif re.fullmatch(r"(?:[\w-]+\.)*indeed\.[a-z.]+", urlsplit(url).hostname or ""):
                ext = dict(parse_qsl(urlsplit(url).query)).get("jk")
        posted = get("posted")
        platform_evidence = get("platform_date_evidence")
        platform_kind = get("platform_date_kind")
        platform_label = platform_date_label(platform_kind, platform_evidence)
        def remember_platform_date(c, job):
            if platform not in ALERT_PLATFORMS or not platform_label or not url:
                return
            evidence = {"url": url, "label": platform_evidence, "kind": platform_kind}
            for row in c.execute("SELECT detail FROM events WHERE job=? AND kind='Listing date observed' ORDER BY rowid DESC", (job,)):
                recorded = json.loads(row[0])
                if all(recorded.get(k) == v for k, v in evidence.items()):
                    return
            self.event(c, job, "Listing date observed", json.dumps({**evidence, "viewed": stamp(), "time_basis": "recorded at intake"}))
        if posted and platform_label and not get("posting_date_evidence"):
            raise ValueError("Leave the original date blank until verified independently.")
        if posted and dt.date.fromisoformat(posted) > now().date():
            raise ValueError("Posting date cannot be in the future.")
        original_at = get("original_posted_at")
        evidence = get("posting_date_evidence")
        def timestamp(value):
            if not value or "T" not in value.upper():
                return None
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed > now():
                raise ValueError("Timestamp must include a timezone and cannot be in the future.")
            return parsed.astimezone(dt.timezone.utc).isoformat()
        original_at = timestamp(original_at)
        if original_at:
            if not evidence:
                raise ValueError("Original timestamp requires independently verified evidence.")
            original_date = dt.datetime.fromisoformat(original_at).astimezone(TZ).date().isoformat()
            if posted and posted != original_date:
                raise ValueError("Original timestamp and posting date disagree.")
            posted = original_date
        kind = get("platform_date_kind")
        observed_at = published_at = None
        if kind:
            try:
                captured = timestamp(platform_evidence)
            except ValueError:
                captured = None  # Keep the platform's literal label as an event.
            if kind == "Displayed":
                observed_at = captured
            else:
                published_at = captured
        seen = stamp()
        country = get("country") or "Unverified"
        vacancy = get("vacancy") or "Unverified"
        if country not in (*TARGET_MARKETS, "Other", "Unverified") or vacancy not in {"Active", "Closed", "Unverified"}:
            raise ValueError("Invalid country or vacancy status.")
        jd = get("jd", 100000)
        declared = get("industry_declared")
        if declared not in {"", "traditional", "web3"}:
            raise ValueError("Invalid industry classification.")
        industry = classify(dict(title=title, company=company, jd=jd, industry_declared=declared))
        if industry["state"] == "excluded":
            keys = ([f"url:{url}"] if url else []) + ([f"source:{platform}:{ext}"] if ext else [])
            keys += ([f"req:{norm(company)}:{norm(req)}"] if req else [])
            if not keys:
                keys = [f"job:{norm(company)}:{norm(title)}:{norm(location)}"]
            with self.connect() as c:
                c.execute("""UPDATE jobs SET industry_declared='web3' WHERE id IN
                           (SELECT job FROM sources WHERE url=? OR (platform=? AND external_id=?))""",
                          (url, platform, ext))
                c.executemany("INSERT OR IGNORE INTO exclusions VALUES(?,?,?)",
                              [(hashlib.sha256(k.encode()).hexdigest(), stamp(), industry["reason"]) for k in keys[:1]])
            return {"result": "excluded", "industry": industry}
        if get("jd_quality") == "Partial" and jd:
            jd = "[Partial JD]\n" + jd
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            identities = [(platform, ext, url), *((alias["source"], alias.get("external_id") or None,
                                                   canonical(alias["url"])) for alias in aliases)]
            hits = {row[0] for name, ident, link in identities for row in c.execute(
                "SELECT job FROM sources WHERE url=? OR (platform=? AND external_id=?)", (link, name, ident))}
            if apply:
                hits.update(row[0] for row in c.execute("SELECT job FROM sources WHERE url=?", (apply,)))
            jobs = list(c.execute("SELECT id,title,company,location,requisition,apply_url FROM jobs"))
            hits.update(j["id"] for j in jobs if (req and j["requisition"] and norm(req) == norm(j["requisition"]) and norm(company) == norm(j["company"])) or (j["apply_url"] and j["apply_url"] in {url, apply}))
            if edit_id is not None:
                if not any(j["id"] == edit_id for j in jobs):
                    raise ValueError("岗位已不存在，请刷新后重试。")
                if hits - {edit_id}:
                    return {"result": "conflict", "ids": sorted(hits | {edit_id})}
                hits = {edit_id}
            if link_id is not None:
                if hits != {link_id}:
                    return {"result": "changed", "id": link_id}
                linked = c.executemany("INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?)",
                                      [(link_id, name, ident, link, link) for name, ident, link in identities]).rowcount
                c.execute("UPDATE jobs SET last_seen=? WHERE id=?", (seen, link_id))
                remember_platform_date(c, link_id)
                if linked:
                    self.event(c, link_id, "Source linked", platform)
                if manual_import:
                    self._mark_imported(c, link_id, original)
                return {"result": "linked", "id": link_id}
            if enrich_id is not None:
                latest = c.execute("SELECT jd FROM snapshots WHERE job=? ORDER BY rowid DESC LIMIT 1", (enrich_id,)).fetchone()
                if hits != {enrich_id} or not jd or jd.startswith("[Partial JD]") or (
                        latest and latest[0] and not latest[0].startswith("[Partial JD]")):
                    return {"result": "changed", "id": enrich_id}
            if len(hits) > 1:
                return {"result": "conflict", "ids": sorted(hits)}
            if hits:
                job = hits.pop()
                c.execute("""UPDATE jobs SET last_seen=?,
                    posted=CASE WHEN original_posted_at IS NULL AND ? IS NOT NULL THEN ? ELSE posted END,
                    date_evidence=CASE WHEN original_posted_at IS NULL THEN COALESCE(?,date_evidence) ELSE date_evidence END,
                    original_posted_at=COALESCE(original_posted_at,?),
                    platform_posted_at=COALESCE(MAX(platform_posted_at,?),platform_posted_at,?),
                    last_published_at=COALESCE(MAX(last_published_at,?),last_published_at,?)
                    WHERE id=?""", (seen, original_at, posted, evidence or None, original_at,
                                      observed_at, observed_at, published_at, published_at, job))
                remember_platform_date(c, job)
                if manual_import:
                    self._mark_imported(c, job, original)
                if new_only:
                    return {"result": "duplicate", "id": job}
                if platform in {"Greenhouse", "Lever", "Ashby"} and vacancy == "Active":
                    verified = c.execute("UPDATE jobs SET vacancy='Active' WHERE id=? AND vacancy='Unverified'", (job,))
                    if verified.rowcount:
                        self.event(c, job, "Vacancy", "Active on official " + platform + " feed")
                if platform_label and not c.execute(
                        "SELECT 1 FROM events WHERE job=? AND kind=? AND detail=?",
                        (job, platform_label, platform_evidence)).fetchone():
                    self.event(c, job, platform_label, platform_evidence)
                if url or ext or not edit_id:
                    c.execute("INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?)", (job, platform, ext, url, original or None))
                c.executemany("INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?)",
                              [(job, a["source"], a.get("external_id") or None, canonical(a["url"]), a["url"]) for a in aliases])
                if company != "Employer unverified" and jd and not jd.startswith("[Partial JD]"):
                    c.execute("""UPDATE jobs SET company=?, title=?, location=?, country=?, posted=COALESCE(?,posted)
                                 WHERE id=? AND company='Employer unverified'""",
                              (company, title, location, country, posted or None, job))
                if manual_import:
                    c.execute("""UPDATE jobs SET
                        location=COALESCE(NULLIF(location,''),NULLIF(?,''),location),
                        country=CASE WHEN country='Unverified' THEN ? ELSE country END,
                        requisition=COALESCE(NULLIF(requisition,''),?),
                        apply_url=COALESCE(NULLIF(apply_url,''),?),
                        posted=COALESCE(posted,?)
                        WHERE id=?""", (location, country, req, apply, posted or None, job))
                if edit_id:
                    c.execute("""UPDATE jobs SET title=?,company=?,location=?,country=?,
                        requisition=COALESCE(?,requisition),apply_url=COALESCE(?,apply_url),
                        match=CASE WHEN title<>? OR company<>? OR location<>? OR country<>? THEN NULL ELSE match END
                        WHERE id=?""", (title, company, location, country, req, apply, title, company, location, country, job))
                if (enrich_id or manual_import) and declared:
                    c.execute("UPDATE jobs SET industry_declared=COALESCE(industry_declared,?) WHERE id=?", (declared, job))
                latest = c.execute("SELECT jd FROM snapshots WHERE job=? ORDER BY rowid DESC LIMIT 1", (job,)).fetchone()
                if jd and not (jd.startswith("[Partial JD]") and latest and not latest[0].startswith("[Partial JD]")) and (
                        (edit_id and (not latest or latest[0] != jd)) or
                        (not edit_id and not c.execute("SELECT 1 FROM snapshots WHERE job=? AND jd=?", (job, jd)).fetchone())):
                    c.execute("INSERT INTO snapshots VALUES(?,?,?)", (job, stamp(), jd))
                    c.execute("UPDATE jobs SET match=NULL WHERE id=?", (job,))
                return {"result": "enriched" if enrich_id or edit_id else "duplicate", "id": job}
            from difflib import SequenceMatcher
            similar = [j["id"] for j in jobs if norm(company) == norm(j["company"]) and
                       (not location or not j["location"] or norm(location) == norm(j["location"])) and
                       SequenceMatcher(None, norm(title), norm(j["title"])).ratio() >= .8]
            if similar and item.get("allow_similar") is not True:
                return {"result": "review", "ids": similar}
            job = uuid.uuid4().hex
            c.execute("""INSERT INTO jobs(id,title,company,location,country,vacancy,first_seen,posted,salary,arrangement,
                          apply_url,requisition,status,notes,match,industry_declared,employment_type,original_posted_at,
                          platform_posted_at,last_published_at,last_seen,date_evidence)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (job, title, company, location, country, vacancy, stamp(), posted or None, get("salary"),
                       get("arrangement"), apply, req, "Discovered", get("notes", 10000), None, declared or None,
                       get("employment_type") or None, original_at, observed_at, published_at, seen, evidence or None))
            c.execute("INSERT INTO sources VALUES(?,?,?,?,?)", (job, platform, ext, url, original or None))
            c.executemany("INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?)",
                          [(job, alias["source"], alias.get("external_id") or None, canonical(alias["url"]), alias["url"])
                           for alias in aliases])
            if jd:
                c.execute("INSERT INTO snapshots VALUES(?,?,?)", (job, stamp(), jd))
            self.event(c, job, "Discovered", platform)
            if manual_import:
                self._mark_imported(c, job, original)
            remember_platform_date(c, job)
            if platform_label:
                self.event(c, job, platform_label, platform_evidence)
            evidence = get("posting_date_evidence")
            if posted and evidence:
                self.event(c, job, "Original posting date evidence", evidence)
        return {"result": "added", "id": job}

    @staticmethod
    def _mark_imported(c, job, url):
        if not c.execute("SELECT 1 FROM events WHERE job=? AND kind='Manually imported' AND detail=?", (job, url)).fetchone():
            Store.event(c, job, "Manually imported", url)

    def mark_imported(self, job, url):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self._mark_imported(c, job, url)

    @staticmethod
    def event(c, job, kind, detail):
        c.execute("INSERT INTO events VALUES(?,?,?,?)", (job, stamp(), kind, detail))

    def review_industry(self, job, decision):
        if decision not in {"traditional", "web3"}:
            raise ValueError("Choose a verified industry.")
        with self.connect() as c:
            c.execute("UPDATE jobs SET industry_declared=? WHERE id=?", (decision, job))
            self.event(c, job, "Industry review", decision)

    def update(self, job, data):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            current = c.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
            if not current:
                raise ValueError("Job not found.")
            status = data.get("status", current["status"])
            jd = c.execute("SELECT jd FROM snapshots WHERE job=? ORDER BY rowid DESC LIMIT 1", (job,)).fetchone()
            if status != current["status"] and status in {"CV Ready", "Pending Review", "Ready to Apply", "Manual Action Required", "Submitted"}:
                from industry import require_allowed
                require_allowed({**dict(current), "jd": jd[0] if jd else ""})
            vacancy = data.get("vacancy", current["vacancy"])
            notes = data.get("notes", current["notes"])
            evidence = data.get("evidence", "").strip()
            if status == "Manually Applied" and status != current["status"]:
                raise ValueError("Use the manual application recorder to select the versions actually used.")
            if status not in STATES or vacancy not in {"Active", "Closed", "Unverified"} or not isinstance(notes, str) or len(notes) > 10000:
                raise ValueError("Invalid application update.")
            if status == "Submitted" and status != current["status"] and (not evidence or data.get("confirmed") is not True):
                raise ValueError("Explicit confirmation and submission evidence are required.")
            if current["status"] == "Submission Confirmation Unknown" and status != current["status"] and (
                    status not in {"Submitted", "Application Failed"} or not evidence):
                raise ValueError("Reconcile the outcome with evidence before changing this status.")
            if status == "Submission Confirmation Unknown" and status != current["status"] and not evidence:
                raise ValueError("Describe the unknown submission outcome.")
            if status == "Submitted" and status != current["status"]:
                from auto_apply import prior_application
                if prior_application(c, dict(current), reconciling=current["status"] == "Submission Confirmation Unknown"):
                    raise ValueError("A previous or unresolved application already exists for this vacancy.")
                platform = data.get("submission_platform")
                if platform in {"LinkedIn", "Indeed"}:
                    c.execute("""INSERT INTO apply_attempts(job,platform,state,created,confirmed_at,detail)
                              VALUES(?,?,'confirmed',?,?,?)""", (job,platform,stamp(),stamp(),evidence))
            if status == "Ready to Apply" and status != current["status"]:
                match = json.loads(current["match"] or "{}")
                source = c.execute("SELECT platform FROM sources WHERE job=? ORDER BY rowid LIMIT 1", (job,)).fetchone()
                from auto_apply import application_blockers, prior_application
                if prior_application(c, dict(current)):
                    raise ValueError("A previous or unresolved application exists for this vacancy.")
                blockers = application_blockers({**dict(current), "source": source[0] if source else "",
                                                  "match": match, "vacancy": vacancy, "jd": jd[0] if jd else ""},
                                                 now().date())
                if blockers:
                    raise ValueError(" ".join(blockers))
                if not c.execute(
                    "SELECT 1 FROM documents WHERE job=? AND kind='CV' AND source_hash=? AND jd_hash=? AND mapping<>'[]'",
                    (job, match.get("source_hash"), match.get("jd_hash"))
                ).fetchone():
                    raise ValueError("Approval requires an active vacancy, verified eligibility and a saved CV.")
            c.execute("UPDATE jobs SET status=?,vacancy=?,notes=? WHERE id=?", (status, vacancy, notes, job))
            if status != current["status"]:
                self.event(c, job, status, evidence)
            if vacancy != current["vacancy"]:
                self.event(c, job, "Vacancy", vacancy)

    def backup(self):
        folder = self.folder / "backups"
        folder.mkdir(mode=0o700, exist_ok=True)
        dest = folder / (now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".sqlite3")
        with self.connect() as c, sqlite3.connect(dest) as out:
            c.backup(out)
        return dest

    @staticmethod
    def restore(source, destination):
        source, destination = Path(source).resolve(), Path(destination).resolve()
        if destination.exists():
            raise ValueError("Restore destination already exists. Choose a new path.")
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as incoming:
            if incoming.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or incoming.execute("PRAGMA user_version").fetchone()[0] not in {1, 2, 3, 4, 5, 6, 7, 8, 9}:
                raise ValueError("Invalid backup.")
            if incoming.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Backup has broken references.")
            with destination.open("xb"), sqlite3.connect(destination) as out:
                incoming.backup(out)

    def export(self):
        with self.connect() as c:
            tables = ("jobs", "sources", "snapshots", "documents", "events", "runs", "settings", "exclusions", "apply_attempts")
            return {name: [dict(r) for r in c.execute("SELECT * FROM " + name)] for name in tables}

    def csv(self):
        output = io.StringIO()
        keys = ["title", "company", "location", "country", "source", "url", "posted", "first_seen", "vacancy", "status", "notes"]
        writer = csv.writer(output)
        writer.writerow(keys)
        for row in self.jobs():
            values = [str(row[k] or "") for k in keys]
            writer.writerow(["'" + x if x.lstrip().startswith(("=", "+", "-", "@")) else x for x in values])
        return output.getvalue()
