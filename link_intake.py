"""Read explicitly pasted public job links without a logged-in browser session."""
import datetime as dt
import http.client
import ipaddress
import json
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from bulk_intake import prepare_row
from core import canonical, now
from discovery import COUNTRY_CODES, MARKETS, Description, fetch_json, normalize
from email_alerts import job_url


class ReadFailure(ValueError):
    pass


def target(url):
    if not isinstance(url, str) or len(url) > 3000 or re.search(r'[\s\\]', url):
        raise ReadFailure("请粘贴一个有效的公开 HTTPS 岗位链接。")
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ReadFailure("只读取标准端口的公开 HTTPS 链接。")
    host = parsed.hostname.rstrip('.').lower()
    if re.search(r'(?:^|\.)(?:linkedin\.com|indeed\.[a-z.]+)$', host):
        raise ReadFailure("LinkedIn／Indeed 需要在平台页面查看；请粘贴完整 JD 或使用雇主官网链接。")
    return parsed, host


def download(url, redirects=3, *, inspect_redirect=False):
    for _ in range(redirects + 1):
        parsed, host = target(url)
        try:
            ips = {r[4][0] for r in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        except OSError as error:
            raise ReadFailure("域名无法解析，请检查链接后重试。") from error
        if not ips or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in ips):
            raise ReadFailure("此链接不指向公开网站。")
        connection = http.client.HTTPSConnection(host, timeout=7)
        # Pin the connection to the validated address while keeping TLS hostname verification.
        address = sorted(ips, key=lambda ip: (':' in ip, ip))[0]
        connection._create_connection = lambda _, timeout, source_address: socket.create_connection((address, 443), timeout, source_address)
        try:
            path = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')
            connection.request('GET', path, headers={'User-Agent': 'TrackerBoard/2.0', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            status = response.status
            if status in (301, 302, 303, 307, 308) and response.getheader('Location'):
                url = urljoin(url, response.getheader('Location'))
                if inspect_redirect:
                    return status, '', url
                continue
            data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ReadFailure("页面太大，请手动补充 JD。")
            return status, data.decode('utf-8', errors='replace'), url
        except (OSError, http.client.HTTPException) as error:
            raise ReadFailure("网站连接失败或超时，请稍后重试。") from error
        finally:
            connection.close()
    raise ReadFailure("页面重定向次数过多。")


class StructuredPosting(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and (dict(attrs).get('type') or '').lower() == 'application/ld+json':
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            self.scripts.append(''.join(self.current))
            self.current = None


def postings(value):
    if isinstance(value, list):
        for child in value:
            yield from postings(child)
    elif isinstance(value, dict):
        kind = value.get('@type', [])
        if 'JobPosting' in ([kind] if isinstance(kind, str) else kind if isinstance(kind, list) else []):
            yield value
        yield from postings(value.get('@graph'))


def description(html):
    parser = Description()
    parser.feed(unescape(html))
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())


def date_only(value):
    try:
        day = dt.date.fromisoformat(value[:10])
        return day.isoformat() if day <= now().date() else ''
    except (ValueError, TypeError):
        return ''


def public_posting(url):
    final = url
    for _ in range(4):
        _, host = target(final)
        status, body, _ = download(f'https://{host}/robots.txt')
        if status == 200:
            rules = RobotFileParser()
            rules.parse(body.splitlines())
            if not rules.can_fetch('TrackerBoard', final):
                raise ReadFailure("该网站的 robots.txt 不允许读取此页面。")
        elif status not in (404, 410):
            raise ReadFailure("无法核实该网站的公开抓取规则，请手动补充。")
        status, html, next_url = download(final, inspect_redirect=True)
        if status not in (301, 302, 303, 307, 308) or next_url == final:
            break
        final = next_url
    else:
        raise ReadFailure("页面重定向次数过多。")
    if status in (401, 403, 429):
        raise ReadFailure(f"网站拒绝公开读取（HTTP {status}），可能需要登录、人机验证或稍后重试。")
    if status in (404, 410):
        raise ReadFailure(f"岗位链接失效或已下架（HTTP {status}）。")
    if status != 200:
        raise ReadFailure(f"网站返回 HTTP {status}，请重试或手动补充。")
    if re.search(r'<title>[^<]*(?:security check|just a moment|access denied|sign in|log in|captcha)', html, re.I):
        raise ReadFailure("页面显示登录或人机验证提示。")
    parser = StructuredPosting()
    parser.feed(html)
    records = []
    for script in parser.scripts:
        try:
            records.extend(postings(json.loads(script)))
        except (ValueError, RecursionError):
            continue
    if len(records) != 1:
        raise ReadFailure("未找到唯一的公开岗位数据。该链接可能是列表、动态页面或仅公开摘要。")
    row = records[0]
    employer = row.get('hiringOrganization')
    company = employer.get('name') if isinstance(employer, dict) else ''
    title = row.get('title')
    raw = row.get('description')
    jd = description(raw) if isinstance(raw, str) else ''
    if not all(isinstance(x, str) and x.strip() for x in (title, company)):
        raise ReadFailure("网页缺少可核验的职位名或雇主，请手动补充。")
    locations = row.get('jobLocation') or []
    locations = locations if isinstance(locations, list) else [locations]
    parts = []
    country_codes = set()
    for place in locations:
        address = place.get('address') if isinstance(place, dict) else None
        if isinstance(address, dict):
            country = address.get('addressCountry')
            country = country.get('name') if isinstance(country, dict) else country
            if isinstance(country, str):
                country_codes.add(country.upper())
            parts.append(', '.join(x for x in (address.get('addressLocality'), address.get('addressRegion'), country) if isinstance(x, str) and x))
    location = ' / '.join(dict.fromkeys(filter(None, parts)))
    markets = {name for name, pattern in MARKETS if re.search(pattern, location, re.I)}
    markets.update(COUNTRY_CODES[code] for code in country_codes if code in COUNTRY_CODES)
    market = next(iter(markets)) if len(markets) == 1 else 'Unverified'
    ident = row.get('identifier')
    ident = ident.get('value') if isinstance(ident, dict) else ident
    posted = date_only(row.get('datePosted'))
    return dict(title=title.strip(), company=company.strip(), location=location, country=market,
                source='Company career page', url=url, apply_url=final, requisition=str(ident) if isinstance(ident, (str, int)) else '',
                posted=posted, posting_date_evidence=f'Public page JobPosting.datePosted: {posted}' if posted else '',
                jd=jd, jd_quality='Full' if len(jd) >= 250 and not jd.endswith(('…', '...')) else 'Partial')


def read_listing(url):
    parsed, host = target(url)
    greenhouse = re.fullmatch(r'/([a-zA-Z0-9_-]{1,60})/jobs/(\d{1,20})/?', parsed.path)
    if greenhouse and host in {'boards.greenhouse.io', 'job-boards.greenhouse.io',
                               'boards.eu.greenhouse.io', 'job-boards.eu.greenhouse.io'}:
        token, job_id = greenhouse.groups()
        api = 'boards-api.eu.greenhouse.io' if '.eu.' in host else 'boards-api.greenhouse.io'
        base = f'https://{api}/v1/boards/{token}'
        try:
            detail = fetch_json(f'{base}/jobs/{job_id}')
            board = fetch_json(base)
        except ValueError as error:
            if re.search(r'\b(?:404|410)\b', str(error)):
                raise ReadFailure("雇主招聘接口显示岗位不存在或已下架。") from error
            raise ReadFailure("雇主招聘接口暂不可读，请重试或手动补充。") from error
        if str(detail.get('id')) != job_id or not board.get('name'):
            raise ReadFailure("雇主接口未返回匹配的岗位编号。")
        row = normalize(token, board['name'], detail, {}, verification=True)
        if not row:
            raise ReadFailure("雇主接口未返回可识别的职位信息。")
        return {**row[1], 'url': url}
    return public_posting(url)


def existing_by_url(store, url):
    normalized = prepare_row({'url': url})['url']
    key = canonical(normalized)
    source, external = "", ""
    for platform in ("LinkedIn", "Indeed"):
        identity = job_url(normalized, platform)
        if identity:
            source, external = platform, identity[0]
            break
    parts = urlsplit(normalized)
    greenhouse = re.fullmatch(r'/([a-zA-Z0-9_-]{1,60})/jobs/(\d{1,20})/?', parts.path)
    if greenhouse and parts.hostname in {'boards.greenhouse.io', 'job-boards.greenhouse.io',
                                          'boards.eu.greenhouse.io', 'job-boards.eu.greenhouse.io'}:
        source, external = 'Greenhouse', ':'.join(greenhouse.groups())
    with store.connect() as c:
        rows = c.execute("""SELECT DISTINCT job FROM sources
            WHERE url=? OR original_url=? OR (platform=? AND external_id=?)""", (key, url, source, external)).fetchall()
    return [r[0] for r in rows]


def import_link(store, url):
    ids = existing_by_url(store, url)
    if len(ids) > 1:
        return {'result': 'conflict', 'ids': ids}
    existing = next((job for job in store.jobs() if ids and job['id'] == ids[0]), None)
    if existing and existing['jd'] and not existing['jd'].startswith('[Partial JD]'):
        store.mark_imported(existing['id'], url)
        return {'result': 'duplicate', 'id': existing['id'], 'read': False}
    try:
        item = read_listing(url)
    except (ReadFailure, ValueError) as error:
        return {'result': 'unreadable', 'reason': str(error), 'id': existing['id'] if existing else None}
    result = store.ingest(item, manual_import=True)
    return {**result, 'read': True, 'complete_jd': item['jd_quality'] == 'Full'}
