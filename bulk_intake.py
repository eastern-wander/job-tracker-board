"""Convert user-supplied exports and listing links to preview rows."""
import csv
import io
import json
import re
from urllib.parse import parse_qs, urlsplit

from email_alerts import job_url


def parse_export(content, kind):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Choose a nonempty CSV or JSON export.")
    if kind == "json":
        rows = json.loads(content.lstrip("\ufeff"))
        if isinstance(rows, dict):
            rows = rows.get("jobs")
        if not isinstance(rows, list):
            raise ValueError("The JSON export must contain a listing array.")
        return rows
    if kind != "csv":
        raise ValueError("Choose a CSV or JSON export.")
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff"), newline=""), strict=True)
    aliases = {"job_title": "title", "employer": "company", "description": "jd", "job_description": "jd",
               "job_url": "url", "posting_date_label": "platform_date_evidence"}
    rows = []
    try:
        for row in reader:
            if None in row:
                raise ValueError("A CSV row has extra fields. Quote values containing commas.")
            rows.append({aliases.get(key.strip().lower().replace(" ", "_"), key.strip().lower().replace(" ", "_")): value or ""
                         for key, value in row.items()})
    except csv.Error as error:
        raise ValueError(f"Invalid CSV: {error}") from error
    return rows


def prepare_row(row):
    if not isinstance(row, dict):
        return row
    url = row.get("url")
    if not isinstance(url, str):
        return row
    url = url.strip()
    markdown = re.fullmatch(r"\[[^\]\n]+\]\((https://[^\s)]+)\)", url)
    if markdown:
        url = markdown[1]
    try:
        parts = urlsplit(url)
        job_id = parse_qs(parts.query).get("currentJobId", [""])[0]
        if (parts.scheme == "https" and not parts.username and not parts.password
                and parts.hostname in {"linkedin.com", "www.linkedin.com"}
                and parts.path.rstrip("/") in {"/jobs/search", "/jobs/search-results"}
                and job_id.isascii() and job_id.isdecimal()):
            url = f"https://www.linkedin.com/jobs/view/{job_id}"
    except ValueError:
        return row
    source = next((name for name in ("LinkedIn", "Indeed") if job_url(url.strip(), name)), "")
    if not source:
        return row
    return {**row, "url": url, "source": source if str(row.get("source") or "").casefold() in {"", source.casefold()} else row["source"],
            "title": row.get("title") or "Job title unverified",
            "company": row.get("company") or "Employer unverified",
            "platform_date_kind": row.get("platform_date_kind") or ("Displayed" if row.get("platform_date_evidence") else "")}
