"""Read-only Gmail discovery. Raw messages and OAuth credentials never enter SQLite."""
import base64
import binascii
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import time
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

HOME = Path.home() / "Library/Application Support/Tracker Board"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
API = "https://gmail.googleapis.com/gmail/v1/users/me/"
TOKEN = "https://oauth2.googleapis.com/token"


class Reauthorize(ValueError):
    pass


def load():
    if __import__("runtime_config").fixture_mode():
        return {}
    path = HOME / "gmail.json"
    if not path.exists():
        return {}
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) & 0o077 or path.stat().st_uid != os.getuid():
        raise ValueError("Gmail credential file must be private and owned by your account.")
    return json.loads(path.read_text())


def save(value):
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    if HOME.is_symlink() or HOME.stat().st_uid != os.getuid() or stat.S_IMODE(HOME.stat().st_mode) & 0o077:
        raise ValueError("Gmail settings directory must be private (mode 0700).")
    fd, temp = tempfile.mkstemp(dir=HOME)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(value, file)
        os.replace(temp, HOME / "gmail.json")
    finally:
        Path(temp).unlink(missing_ok=True)


def request(url, data=None, bearer=None):
    # Pass bearer tokens and OAuth secrets over stdin, not in process arguments.
    cmd = ["/usr/bin/curl", "-sS", "--proto", "=https", "--max-time", "15",
           "--max-filesize", "5000000", "-w", "\n%{http_code}", "-K", "-", url]
    config = ""
    if bearer:
        config += "header = " + json.dumps("Authorization: Bearer " + bearer) + "\n"
    if data:
        config += 'header = "Content-Type: application/x-www-form-urlencoded"\n'
        config += "data = " + json.dumps(urlencode(data)) + "\n"
    result = subprocess.run(cmd, input=config.encode(), capture_output=True, timeout=20)
    if result.returncode:
        raise ValueError("Gmail request did not complete. Check network and try again.")
    body, status = result.stdout.rsplit(b"\n", 1)
    value = json.loads(body)
    if status == b"401" or value.get("error") == "invalid_grant":
        raise Reauthorize("Gmail authorization expired or was revoked. Reauthorize to resume.")
    if status != b"200":
        raise ValueError("Google API returned HTTP " + status.decode() + ". Check Gmail API access or retry later.")
    return value


def access(config):
    return request(TOKEN, {"client_id": config["client_id"], "client_secret": config["client_secret"],
                           "refresh_token": config["refresh_token"], "grant_type": "refresh_token"})["access_token"]


def labels(config):
    return [r for r in request(API+"labels", bearer=access(config))["labels"] if r.get("type") == "user"]


def select_label(label):
    cfg = load()
    if not cfg or label not in {r["id"] for r in labels(cfg)}:
        raise ValueError("Choose a dedicated custom Gmail label.")
    if cfg.get("label") != label:
        save({**cfg, "label": label, "since": int(time.time())})


def job_url(href, source, *, wrapped=False):
    try:
        u = urlsplit(href)
    except ValueError:
        return None
    host = u.hostname or ""
    if u.scheme != "https" or u.username or u.password:
        return None
    if source == "LinkedIn" and (host == "linkedin.com" or host.endswith(".linkedin.com")):
        if u.path == "/e/v2" and not wrapped:
            targets = parse_qs(u.query).get("url", [])
            if len(targets) == 1:
                target = targets[0]
                if not target.startswith("https://"):
                    target = unquote(target)
                return job_url(target, source, wrapped=True)
        found = re.fullmatch(r"/(?:comm/)?jobs/view/(?:[^/]*-)?(\d+)/?", unquote(u.path))
        if found:
            return found[1], "https://www.linkedin.com/jobs/view/" + found[1]
    if source == "Indeed" and re.fullmatch(r"(?:[\w-]+\.)*indeed\.(?:com|ca|ae|co\.uk)", host):
        params = parse_qs(u.query)
        ident = (params.get("jk") or params.get("vjk") or [""])[0]
        if u.path in {"/viewjob", "/rc/clk", "/rc/clk/dl", "/pagead/clk", "/pagead/clk/dl", "/clk/dl", "/m/basecamp/viewjob", "/jobs"} and re.fullmatch(r"[a-fA-F0-9]{16}", ident):
            ident = ident.lower()
            return ident, f"https://{host}/viewjob?jk={ident}"
    return None


class AlertHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.anchors = []
        self.cards = []

    def handle_starttag(self, tag, attrs):
        if tag in {"div", "p", "br", "li", "tr", "td", "table"}:
            self.parts.append("\n")
        if tag == "a":
            if self.anchors:
                self.anchors[-1][2] = True
            self.anchors.append([dict(attrs).get("href", ""), len(self.parts), False])

    def handle_endtag(self, tag):
        if tag == "a" and self.anchors:
            href, start, wraps_link = self.anchors.pop()
            target = self.cards if wraps_link else self.links
            target.append((href, start, len(self.parts)))
        if tag in {"div", "p", "li", "tr", "td", "table"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def indeed_plain_cards(content):
    """Read the alert's title and employer/location above its trailing job URL."""
    for block in re.split(r"\n\s*\n", content):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or not re.fullmatch(r"https://[^\s<>]+", lines[-1]):
            continue
        href = lines[-1]
        identity = job_url(href, "Indeed")
        if not identity or urlsplit(href).path != "/rc/clk/dl":
            continue
        fields = lines[1].split(" - ", 1)
        if len(fields) == 2 and all(fields) and len(lines[0]) <= 180:
            yield href, lines[0], fields, lines[2:-1]


def parse_alert(payload):
    headers = {x["name"].lower(): x["value"] for x in payload.get("headers", [])}
    host = parseaddr(headers.get("from", ""))[1].rpartition("@")[2].lower()
    source = next((name for domain, name in (("linkedin.com","LinkedIn"), ("indeed.com","Indeed"),
                  ("indeed.ca","Indeed"), ("indeed.ae","Indeed"), ("indeed.co.uk","Indeed"))
                   if host == domain or host.endswith("." + domain)), None)
    report = dict(platform=source or "Unknown", duplicates=0, rejected=0, parsing_errors=0)
    if not source:
        report["rejected"] = 1
        return [], report

    def bodies(part):
        if part.get("filename") or part.get("body", {}).get("attachmentId"):
            return
        for child in part.get("parts", []):
            yield from bodies(child)
        content = part.get("body", {}).get("data")
        if content and part.get("mimeType") in {"text/html", "text/plain"}:
            try:
                decoded = base64.b64decode(content + "="*(-len(content)%4), altchars=b"-_", validate=True)
                yield part["mimeType"], decoded.decode("utf-8")
            except (binascii.Error, UnicodeError, TypeError):
                report["parsing_errors"] += 1
    from discovery import CANADA, UAE
    jobs = {}
    untitled = {}
    for mime, content in sorted(bodies(payload), key=lambda part: part[0] != "text/html"):
        parser = AlertHTML()
        if mime == "text/html":
            parser.feed(content)
        elif source == "Indeed" and (cards := list(indeed_plain_cards(content))):
            for href, title, (company, location), details in cards:
                start = len(parser.parts)
                metadata = [f"Company: {company}", f"Location: {location}", *details]
                parser.parts.extend((title, "\n" + "\n".join(metadata) + "\n"))
                parser.links.append((href, start, start + 1))
        else:
            for line in content.splitlines():
                found = re.search(r"https://[^\s<>]+", line)
                if found:
                    title = line[:found.start()].strip(" -–|") or next((x.strip() for x in reversed(parser.parts[-3:]) if x.strip()), "")
                    start = len(parser.parts)
                    parser.parts.append(title + "\n")
                    parser.links.append((found[0].rstrip(").,"), start, start+1))
                else:
                    parser.parts.append(line + "\n")
        links = [(job_url(href, source), start, end) for href, start, end in parser.links]
        links = [(identity, start, end) for identity, start, end in links if identity]
        cards = [(job_url(href, source), start, end) for href, start, end in parser.cards]
        for i, ((external_id, url), start, end) in enumerate(links):
            title = " ".join("".join(parser.parts[start:end]).split()).strip()
            if not title or len(title) > 180 or re.fullmatch(
                    r"(?:view|see|apply|open|learn|show|click)(?: (?:job|now|details|more|here|on indeed|on linkedin))*[.!]?",
                    title, re.I):
                untitled[external_id] = url
                continue
            stop = links[i+1][1] if i+1<len(links) else len(parser.parts)
            card_end = next((last for identity, first, last in cards
                             if identity == (external_id, url) and first <= start <= end <= last), None)
            if card_end is not None:
                stop = min(stop, card_end)
            lines = [x.strip() for x in "".join(parser.parts[end:stop]).splitlines() if x.strip()][:8]
            location, company = "", ""
            if source == "Indeed" and card_end is not None:
                # The wrapped alert card puts the employer and optional star
                # rating before the location row.
                fields = [line for line in lines if not re.fullmatch(r"[0-5][.,]\d", line)]
                if fields and len(fields[0]) <= 100:
                    company = fields[0]
                if len(fields) >= 2 and len(fields[1]) <= 100 and not re.search(
                        r"[$£€]|\b(?:salary|posted|published|ago|today|yesterday)\b", fields[1], re.I):
                    location = fields[1]
            named = re.fullmatch(r"(.+?)\s+at\s+(.+)", title, re.I)
            if named and not company:
                title, company = named.groups()
            posted = ""
            for n,line in enumerate(lines):
                date = re.fullmatch(r"(?:posted|published)(?: on)?[: ]+(\d{4}-\d{2}-\d{2})", line, re.I)
                if date:
                    try:
                        posted = dt.date.fromisoformat(date[1]).isoformat()
                    except ValueError:
                        pass
                if not location and re.search(CANADA+"|"+UAE, line, re.I) and len(line)<150:
                    fields = re.split(r"\s*[·|•]\s*", line, maxsplit=1)
                    if len(fields) == 2 and re.search(CANADA+"|"+UAE, fields[1], re.I) and not re.search(CANADA+"|"+UAE, fields[0], re.I):
                        company = company or fields[0]
                        location = fields[1]
                    else:
                        location = line
                        if not company and n == 1 and len(lines[0]) <= 100:
                            company = lines[0]
            explicit = next((line.split(":", 1)[1].strip() for line in lines
                             if re.match(r"^(?:company|employer):", line, re.I)), "")
            company = explicit or company
            location = next((line.split(":", 1)[1].strip() for line in lines
                             if re.match(r"^location:", line, re.I)), location)
            if company and re.match(r"^(?:company|employer):", company, re.I):
                company = company.split(":", 1)[1].strip()
            markets = [name for name, pattern in (("Canada", CANADA), ("UAE", UAE)) if re.search(pattern,location,re.I)]
            official = next((href for href,pos,_ in parser.links if end <= pos < stop and
                             re.fullmatch(r"https://(?:job-boards|boards)\.greenhouse\.io/[a-zA-Z0-9_-]+/jobs/\d+(?:\?[^\s]*)?", href)), "")
            item = dict(title=title, company=company or "Employer unverified", location=location,
                country=markets[0] if len(markets)==1 else "Unverified", source=source, external_id=external_id,
                url=url, apply_url=official, posted=posted, allow_similar=not company,
                jd="Alert excerpt; verify employer and obtain the original job description.", jd_quality="Partial")
            previous = jobs.get(external_id)
            if previous:
                report["duplicates"] += 1
                for field in ("location", "posted", "apply_url"):
                    if not previous[field]:
                        previous[field] = item[field]
                if previous["company"] == "Employer unverified" and company:
                    previous["company"] = company
                    previous["allow_similar"] = False
                if previous["country"] == "Unverified":
                    previous["country"] = item["country"]
            else:
                jobs[external_id] = item
    for external_id, url in untitled.items():
        if external_id not in jobs:
            jobs[external_id] = dict(title="Job title unverified", company="Employer unverified",
                source=source, external_id=external_id, url=url,
                jd="Alert link only; verify title, employer and posting date.", jd_quality="Partial",
                allow_similar=True)
    if not jobs and not report["parsing_errors"]:
        report["rejected"] = 1
    return list(jobs.values()), report


def extract(payload):
    return parse_alert(payload)[0]


def scan(store, historical=False):
    cfg = load()
    if not cfg.get("label"):
        raise ValueError("Authorize Gmail and select a custom alert label first.")
    bearer = access(cfg)
    lower = int(time.time()) - 30*86400 if historical else cfg["since"]
    with store.connect() as c:
        processed = {r[0] for r in c.execute("SELECT message FROM email_processed WHERE mailbox=?", (cfg["mailbox"],))}
    rows, errors, page = [], [], None
    while True:
        params = {"labelIds": cfg["label"], "q": f"after:{lower}", "maxResults": 100}
        if page:
            params["pageToken"] = page
        batch = request(API+"messages?"+urlencode(params), bearer=bearer)
        for entry in batch.get("messages", []):
            key = entry["id"]
            if key in processed:
                continue
            try:
                message = request(API+"messages/"+quote(key,safe="")+"?format=full", bearer=bearer)
                if cfg["label"] in message.get("labelIds", []) and int(message.get("internalDate", "0")) >= lower*1000:
                    jobs, report = parse_alert(message["payload"])
                    rows.append((key, jobs, report))
            except Reauthorize:
                raise
            except (ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                errors.append(str(error))
        page = batch.get("nextPageToken")
        if not page:
            break
    return cfg["mailbox"], rows, errors


def authorize(path):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    client = json.loads(Path(path).expanduser().read_text())["installed"]
    nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    callback = {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != "/oauth/callback" or self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or query.get("state") != [nonce]:
                self.send_error(400)
                return
            callback.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Authorization response received. Return to Terminal.")
    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/oauth/callback"
        url = "https://accounts.google.com/o/oauth2/v2/auth?"+urlencode(dict(client_id=client["client_id"],
            redirect_uri=redirect, response_type="code", scope=SCOPE, state=nonce, access_type="offline",
            prompt="consent", code_challenge=challenge, code_challenge_method="S256"))
        print("Authorize read-only access in your browser:\n"+url, flush=True)
        until = time.monotonic()+300
        while not callback and time.monotonic()<until:
            server.handle_request()
    if not callback.get("code"):
        raise ValueError("Google consent was declined or timed out.")
    credentials = {key:client[key] for key in ("client_id","client_secret")}
    token = request(TOKEN, {**credentials, "code":callback["code"][0], "code_verifier":verifier,
                           "redirect_uri":redirect,"grant_type":"authorization_code"})
    if token.get("scope") != SCOPE or not token.get("refresh_token"):
        raise ValueError("Google did not grant the requested read-only offline scope.")
    profile = request(API+"profile", bearer=token["access_token"])
    mailbox = hashlib.sha256(profile["emailAddress"].casefold().encode()).hexdigest()
    old = load()
    retained = {k:old[k] for k in ("label","since") if k in old} if old.get("mailbox")==mailbox else {}
    save({**credentials, **retained, "refresh_token":token["refresh_token"], "mailbox":mailbox})
    print("Gmail authorized. Select a dedicated alert label in Tracker Settings.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python email_alerts.py /path/to/desktop-oauth-client.json")
    try:
        authorize(sys.argv[1])
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit(str(error))
