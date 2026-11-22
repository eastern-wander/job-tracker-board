import datetime as dt
import json
import re
import subprocess
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from core import TZ, now, norm, within_discovery_window
from career_families import classify_roles

TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]{0,59}")
# Explicit operator-maintained public feed allowlists; no personal employer list.
LEVER_EMPLOYERS = {}
ASHBY_EMPLOYERS = {}
SECTORS = {}
NON_VACANCY = re.compile(r"\b(?:talent pool|talent community|open application|general application)\b", re.I)
CANADA = r"\b(?:canada|vancouver|burnaby|surrey|richmond, bc|coquitlam|new westminster|north van(?:couver)?|langley|delta, bc|toronto|greater toronto area|mississauga|brampton|markham|vaughan|oakville|hamilton|calgary|montr[eé]al|ottawa|waterloo|edmonton|victoria, bc|halifax|winnipeg|british columbia|ontario|alberta|qu[eé]bec|nova scotia|manitoba|saskatchewan)\b"
CANADA = "(?:"+CANADA+r"|\b(?:new brunswick|newfoundland(?: and labrador)?|prince edward island|yukon|northwest territories|nunavut)\b|,\s*(?:BC|AB|SK|MB|ON|QC|NB|NS|PE|NL|NT|YT|NU)\b)"
UAE = r"\b(?:united arab emirates|u\.?a\.?e\.?|dubai|abu dhabi|sharjah|ajman|ras al khaimah|fujairah|umm al quwain|al ain)\b"


JAPAN = r"\b(?:japan|tokyo|yokohama|osaka|kyoto|nagoya|fukuoka|sapporo|kobe|chiba|saitama)\b|日本|東京|横浜|大阪|京都|名古屋|福岡|札幌|神戸|千葉|埼玉"
USA = r"\b(?:united states|usa|u\.s\.a\.?|new york|san francisco|seattle|boston|chicago|austin|los angeles|washington, dc)\b"
UK = r"\b(?:united kingdom|uk|london|manchester|edinburgh|birmingham|bristol|england|scotland|wales|northern ireland)\b"
MARKETS = (("Canada", CANADA), ("UAE", UAE), ("Japan", JAPAN), ("United States", USA), ("UK", UK))
COUNTRY_CODES = {"CA": "Canada", "AE": "UAE", "JP": "Japan", "US": "United States", "GB": "UK"}

def expanded_settings(settings):
    # Public release never silently opts a new user into the personal board list.
    return {**settings,"ashby_boards":settings.get("ashby_boards","")}


def location_priority(location):
    return 0


class Description(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "br", "li", "div", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def fetch_json(url):
    cmd = ["/usr/bin/curl", "--fail", "--silent", "--show-error", "--proto", "=https",
           "--max-time", "15", "--retry", "2", "--retry-max-time", "30", "--max-filesize", "25000000",
           url]
    result = subprocess.run(cmd, capture_output=True, timeout=50)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace").strip()[:300] or "Feed request failed.")
    return json.loads(result.stdout)


def get_board(token):
    if not TOKEN.fullmatch(token):
        raise ValueError("Invalid Greenhouse board token.")
    base = f"https://boards-api.greenhouse.io/v1/boards/{token}"
    board = fetch_json(base)
    jobs = fetch_json(base + "/jobs?content=true")["jobs"]
    if not isinstance(board.get("name"), str) or not board["name"].strip() or not isinstance(jobs, list):
        raise ValueError("Invalid employer board response.")
    return board["name"], jobs


def get_lever(token):
    if token not in LEVER_EMPLOYERS:
        raise ValueError("Unverified Lever employer board.")
    jobs = []
    for offset in range(0, 2000, 100):
        batch = fetch_json(f"https://api.lever.co/v0/postings/{token}?mode=json&limit=100&skip={offset}")
        if not isinstance(batch, list):
            raise ValueError("Invalid Lever response.")
        jobs.extend(batch)
        if len(batch) < 100:
            return LEVER_EMPLOYERS[token], jobs
    raise ValueError("Lever pagination limit reached.")


def normalize(token, employer, row, settings, clock=None, *, verification=False):
    clock = clock or now()
    title = row.get("title", "").strip()
    location = (row.get("location") or {}).get("name", "").strip()
    markets = [market for market, pattern in MARKETS if re.search(pattern, location, re.I)]
    if not row.get("internal_job_id") or not row.get("id") or not title or NON_VACANCY.search(title):
        return None
    url = row.get("absolute_url", "")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    published = row.get("first_published")
    when = dt.datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None
    if when and when.tzinfo is None:
        raise ValueError("Posting timestamp has no timezone.")
    age = (clock - when).total_seconds() / 86400 if when else None
    if age is not None and (age < 0):
        return None
    parser = Description()
    parser.feed(unescape(row.get("content") or ""))
    jd = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
    if not markets and re.search(r"\bremote\b", location, re.I):
        eligible = re.findall(r"(?:remote (?:work )?(?:from|within|in)|(?:candidates|applicants) (?:based|located) in) ([^.;\n]{1,65})", jd, re.I)
        markets = [market for market, pattern in MARKETS
                   if any(re.search(pattern, region, re.I) for region in eligible)]
    queries = settings.get("resume_queries", [])
    if queries:
        levels = r"\b(?:senior|junior|lead|analyst|associate|coordinator|manager|specialist)\b"
        # Search the responsibility phrase across adjacent levels, including comma-separated titles.
        phrase = norm(re.sub(levels, " ", title, flags=re.I))
        relevant = any(norm(re.sub(levels, " ", query, flags=re.I)) in phrase for query in queries)
    else:
        relevant = classify_roles(title, jd)
    if not verification and (not any(m in settings.get("enabled_countries", [x[0] for x in MARKETS]) for m in markets) or not relevant):
        return None
    item = dict(title=title, company=employer, location=location, country=markets[0] if len(markets) == 1 else "Unverified",
                source="Greenhouse", external_id=f"{token}:{row['id']}", requisition=str(row.get("requisition_id") or ""),
                url=url, apply_url=url, jd=jd, jd_quality="Full" if len(jd) >= 250 else "Partial",
                posted=when.astimezone(TZ).date().isoformat() if when else "", vacancy="Active",
                posting_date_evidence=f"Greenhouse first_published: {published}" if when else "",
                first_published=published or "", original_posted_at=published or "", updated_at=row.get("updated_at") or "")
    metadata = {str(x.get("name","")).casefold(): x.get("value") for x in (row.get("metadata") or []) if isinstance(x, dict)}
    for target, aliases in (("employment_type", ("employment type","commitment","job type")),
                            ("arrangement", ("work arrangement","workplace type","work type")),
                            ("salary", ("salary range","salary","compensation"))):
        item[target] = next((metadata[k][:500] for k in aliases if isinstance(metadata.get(k),str) and metadata[k]), "")
    sector = SECTORS.get(token)
    if sector and sector[0] in employer.casefold():
        item["industry_declared"] = "traditional"
    tier = 0 if within_discovery_window(when.isoformat() if when else "", clock) else 1 if when is None else 2
    return (tier, -location_priority(location), age if age is not None else 999), item


def normalize_lever(token, employer, row, settings, *, verification=False):
    categories = row.get("categories") or {}
    url = row.get("hostedUrl") or ""
    ident = row.get("id") or ""
    if not re.fullmatch(r"[a-f0-9-]{36}", ident) or urlsplit(url).hostname not in {"jobs.lever.co", "jobs.eu.lever.co"} or (
        urlsplit(url).path.rstrip("/") != f"/{token}/{ident}"):
        return None
    location = " / ".join(dict.fromkeys(x for x in [categories.get("location"), *(categories.get("allLocations") or [])] if x))
    if not any(re.search(pattern, location, re.I) for _, pattern in MARKETS):
        location = ", ".join(filter(None, (location, COUNTRY_CODES.get(row.get("country")))))
    jd = "\n".join(filter(None, [row.get("description"), *[
        "<p>"+(x.get("text") or "")+"</p>"+(x.get("content") or "") for x in (row.get("lists") or [])],
        row.get("additional")]))
    # Lever's createdAt is not an original publication timestamp.
    result = normalize(token, employer, {"title":row.get("text") or "", "location":{"name":location}, "id":ident,
        "internal_job_id":ident, "absolute_url":url, "content":jd}, settings, verification=verification)
    if not result:
        return None
    priority, item = result
    pay = row.get("salaryRange") or {}
    salary = row.get("salaryDescriptionPlain") or ""
    if not salary and isinstance(pay.get("min"), (int,float)) and isinstance(pay.get("max"), (int,float)) and pay.get("currency"):
        salary = f"{pay['currency']} {pay['min']:g}–{pay['max']:g} {pay.get('interval') or ''}".strip()
    apply = row.get("applyUrl")
    item.update(source="Lever", apply_url=apply if apply == url.rstrip("/")+"/apply" else url, salary=salary[:500],
                employment_type=categories.get("commitment") or "", arrangement=row.get("workplaceType") or "")
    return priority, item


def get_ashby(token):
    if token not in ASHBY_EMPLOYERS:
        raise ValueError("Unverified Ashby board.")
    rows = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")["jobs"]
    if not isinstance(rows, list):
        raise ValueError("Invalid Ashby response.")
    return ASHBY_EMPLOYERS[token], [row for row in rows if row.get("isListed") is True]


def normalize_ashby(token, employer, row, settings, *, verification=False):
    url = row.get("jobUrl") or ""
    match = re.fullmatch(rf"https://jobs\.ashbyhq\.com/{re.escape(token)}/([a-f0-9-]{{36}})/?", url)
    if not match or row.get("isListed") is not True:
        return None
    location = " / ".join(dict.fromkeys(filter(None, [row.get("location"),
        *(place.get("location") for place in row.get("secondaryLocations") or [])])))
    result = normalize(token, employer, {"title": row.get("title") or "", "id": match[1],
        "internal_job_id": match[1], "location": {"name": location}, "absolute_url": url,
        "content": row.get("descriptionHtml") or row.get("descriptionPlain") or ""}, settings, verification=verification)
    if not result:
        return None
    priority, job = result
    job.update(source="Ashby", industry_declared="traditional", employment_type=row.get("employmentType") or "",
               arrangement=row.get("workplaceType") or "")
    if row.get("applyUrl") == url.rstrip("/") + "/application":
        job["apply_url"] = row["applyUrl"]
    if row.get("descriptionPlain"):
        job.update(jd=row["descriptionPlain"], jd_quality="Full" if len(row["descriptionPlain"]) >= 250 else "Partial")
    published = row.get("publishedAt")
    if published:
        timestamp = dt.datetime.fromisoformat(published.replace("Z", "+00:00"))
        if timestamp.tzinfo is not None and timestamp <= now():
            # Ashby documents this as the last publication, which may be a repost.
            job.update(platform_date_kind="Last published", platform_date_evidence=published)
            age = (now() - timestamp).total_seconds() / 86400
            priority = (1, -location_priority(location), age)
    return priority, job


def collect(settings, health, *, verification=False):
    if __import__("runtime_config").fixture_mode():
        from fixture_demo import demo_jobs
        items=[j for j in demo_jobs() if j["country"] in settings.get("enabled_countries",COUNTRY_CODES.values())]
        health["Fixture sources"]={"state":"Simulated","retrieved":len(items),"targeted":len(items)}
        return items
    candidates = []
    sources = (("Greenhouse", settings["boards"], get_board, normalize),
               ("Lever", settings.get("lever_boards",""), get_lever, normalize_lever),
               ("Ashby", settings.get("ashby_boards",""), get_ashby, normalize_ashby))
    for name, tokens, fetch, normalize_row in sources:
      for token in dict.fromkeys(x.strip() for x in tokens.split(",") if x.strip()):
        label = name + ": " + token
        try:
            employer, jobs = fetch(token)
            selected, invalid = [], 0
            for row in jobs:
                try:
                    item = normalize_row(token, employer, row, settings, verification=verification)
                    if item:
                        selected.append(item)
                except (ValueError, TypeError, AttributeError):
                    invalid += 1
            health[label] = {"state": "Retrieved" if jobs else "Empty", "retrieved": len(jobs),
                             "targeted": len(selected), "invalid": invalid, "employer": employer}
            candidates.extend(selected)
        except (ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            health[label] = {"state": "Failed", "error": str(error)}
    return [item for _, item in sorted(candidates, key=lambda pair: pair[0])]
