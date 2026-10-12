#!/usr/bin/env python3
"""Check every listing's link and flag rows that need a maintainer.

Usage:
    python3 scripts/check_links.py            # markdown report on stdout
    python3 scripts/check_links.py --json     # JSON report instead
    python3 scripts/check_links.py --strict   # exit 1 if anything needs action
    python3 scripts/check_links.py --no-fetch # deadlines only, no network

Results per row:
    OK       link resolves (and the ATS says the posting is live, where we can ask)
    DEAD     the link itself 404s/410s
    CLOSED   the ATS or the page says the posting is no longer available
    UNKNOWN  blocked, rate-limited, timed out or erroring. Usually bot
             protection, so never treated as dead.
Open rows whose `deadline` has passed are reported separately. Closed rows
are skipped, and expected rows only need their careers page to resolve.
"""

import json
import re
from http.client import HTTPException, IncompleteRead
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from update_readme import LISTINGS

TIMEOUT = 20
WORKERS = 8
MAX_BODY = 1_000_000
SOON_DAYS = 7
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# Phrases careers sites show on a dead posting that still returns 200.
CLOSED_TEXT = re.compile(
    r"job (?:posting )?(?:is|has been) (?:no longer available|closed|filled|removed)"
    r"|(?:position|posting|job|role) (?:is )?no longer (?:available|accepting applications|open)"
    r"|no longer accepting applications"
    r"|this (?:job|position|posting|requisition) has (?:expired|been filled|closed)"
    r"|the job you are looking for (?:is no longer|no longer exists|could not be found)",
    re.I,
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


follow = build_opener()
no_follow = build_opener(NoRedirect)


def fetch(url, accept="text/html,application/xhtml+xml,*/*;q=0.8", redirects=True):
    """Return (status, headers, body). status is None on network errors."""
    req = Request(url, headers={
        "User-Agent": UA,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with (follow if redirects else no_follow).open(req, timeout=TIMEOUT) as resp:
            try:
                body = resp.read(MAX_BODY)
            except IncompleteRead as e:
                body = e.partial  # truncated response: still usable
            return resp.status, resp.headers, body.decode("utf-8", "replace")
    except HTTPError as e:
        return e.code, e.headers, ""
    except (URLError, HTTPException, OSError) as e:
        return None, None, str(getattr(e, "reason", e))


def from_http(status, body="", detail=""):
    if status in (404, 410):
        return "DEAD", f"HTTP {status}"
    if status is None:
        return "UNKNOWN", detail or "network error"
    if status >= 400:
        return "UNKNOWN", f"HTTP {status}"
    if CLOSED_TEXT.search(body):
        return "CLOSED", "page says the job is no longer available"
    return "OK", f"HTTP {status}"


# --- ATS-specific checks. Each returns (result, detail), or None to fall back
# --- to a plain page fetch.

def greenhouse(url):
    u = urlparse(url)
    qs = parse_qs(u.query)
    board = job = None
    m = re.match(r"/([^/]+)/jobs/(\d+)", u.path)
    if u.netloc.endswith("greenhouse.io") and m:
        board, job = m.groups()
    elif "gh_jid" in qs:
        # Custom careers domain: Greenhouse's embed URL redirects to ?for=<board>.
        job = qs["gh_jid"][0]
        status, headers, _ = fetch(
            f"https://boards.greenhouse.io/embed/job_app?token={quote(job)}",
            redirects=False,
        )
        if status == 404:
            return "CLOSED", "Greenhouse: job not found"
        board = parse_qs(urlparse((headers or {}).get("Location", "")).query).get("for", [None])[0]
    if not (board and job and job.isdigit()):
        return None
    status, _, _ = fetch(
        f"https://boards-api.greenhouse.io/v1/boards/{quote(board)}/jobs/{job}",
        accept="application/json",
    )
    if status == 404:
        return "CLOSED", f"Greenhouse API: {board}/{job} not found"
    if status == 200:
        return "OK", "Greenhouse API: live"
    return None


def amazon(url):
    m = re.search(r"amazon\.jobs/(?:[a-z-]+/)?jobs/(\d+)", url)
    if not m:
        return None
    status, _, body = fetch(f"https://www.amazon.jobs/en/jobs/{m.group(1)}")
    if status == 404:
        return "CLOSED", "amazon.jobs: job not found"
    if status == 200:
        if CLOSED_TEXT.search(body):
            return "CLOSED", "amazon.jobs: no longer available"
        return "OK", "amazon.jobs: live"
    return None


def workday(url):
    u = urlparse(url)
    m = re.match(r"([^.]+)\.wd\d+\.myworkdayjobs\.com$", u.netloc)
    parts = [p for p in u.path.split("/") if p]
    if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
        parts = parts[1:]  # drop locale, e.g. /en-US/
    if not (m and len(parts) >= 3 and parts[1] == "job"):
        return None
    tenant, site = m.group(1), parts[0]
    api = f"https://{u.netloc}/wday/cxs/{tenant}/{site}/job/" + "/".join(parts[2:])
    status, _, body = fetch(api, accept="application/json")
    if status == 404:
        return "CLOSED", "Workday: posting not found"
    if status != 200:
        return None
    try:
        info = json.loads(body).get("jobPostingInfo", {})
    except ValueError:
        return None
    if info.get("postingAvailable") is False or info.get("canApply") is False:
        return "CLOSED", "Workday: posting not available"
    return "OK", "Workday API: live"


ATS = [
    (re.compile(r"greenhouse\.io|[?&]gh_jid="), greenhouse),
    (re.compile(r"amazon\.jobs/"), amazon),
    (re.compile(r"\.myworkdayjobs\.com/"), workday),
]


def check(item):
    try:
        return check_url(item)
    except Exception as e:  # one odd site shouldn't sink the whole run
        return "UNKNOWN", f"error: {e}"


def check_url(item):
    url = item["url"]
    if item["status"] == "open":
        for pattern, fn in ATS:
            if pattern.search(url):
                result = fn(url)
                if result:
                    return result
    status, _, body = fetch(url)
    if status is None:
        return from_http(None, detail=body)
    # Expected rows point at careers landing pages: only care that they resolve.
    return from_http(status, body if item["status"] == "open" else "")


def label(item):
    return f"{item['company']} - {item['role']}"


def run(listings, fetch_links=True, today=None):
    today = today or date.today()
    rows = []
    to_check = [r for r in listings if r["status"] != "closed"] if fetch_links else []
    with ThreadPoolExecutor(WORKERS) as pool:
        for item, (result, detail) in zip(to_check, pool.map(check, to_check)):
            rows.append({"company": item["company"], "role": item["role"],
                         "status": item["status"], "url": item["url"],
                         "result": result, "detail": detail})

    past, soon = [], []
    for item in listings:
        if item["status"] != "open" or not item.get("deadline"):
            continue
        d = date.fromisoformat(item["deadline"])
        entry = {"company": item["company"], "role": item["role"],
                 "url": item["url"], "deadline": item["deadline"]}
        if d < today:
            past.append(entry)
        elif d <= today + timedelta(days=SOON_DAYS):
            soon.append(entry)
    return {"date": today.isoformat(), "links": rows,
            "past_deadline": past, "deadline_soon": soon}


def counts(report):
    c = {k: 0 for k in ("OK", "UNKNOWN", "DEAD", "CLOSED")}
    for r in report["links"]:
        c[r["result"]] += 1
    c["PAST_DEADLINE"] = len(report["past_deadline"])
    return c


def needs_action(report):
    c = counts(report)
    return c["DEAD"] + c["CLOSED"] + c["PAST_DEADLINE"] > 0


def md_table(rows, extra):
    lines = [f"| Company | Role | {extra} |", "| --- | --- | --- |"]
    for r in rows:
        value = r.get("deadline") or r.get("detail", "")
        role = r["role"].replace("|", "\\|")
        lines.append(f"| {r['company']} | [{role}]({r['url']}) | {value} |")
    return "\n".join(lines)


def markdown(report):
    c = counts(report)
    summary = f"**{c['PAST_DEADLINE']}** past deadline"
    if report["links"]:
        summary = (f"**{c['OK']}** OK · **{c['UNKNOWN']}** unknown · **{c['DEAD']}** dead · "
                   f"**{c['CLOSED']}** closed · " + summary)
    out = [f"## Link check ({report['date']})", "", summary, ""]
    dead = [r for r in report["links"] if r["result"] in ("DEAD", "CLOSED")]
    if dead:
        out += ["### ❌ Dead or closed",
                "Set `\"status\": \"closed\"` (or fix the URL) in `listings.json`.", "",
                md_table(dead, "Why"), ""]
    if report["past_deadline"]:
        out += ["### ⌛ Open but past deadline",
                "Confirm the posting is down, then set `\"status\": \"closed\"`.", "",
                md_table(report["past_deadline"], "Deadline"), ""]
    if report["deadline_soon"]:
        out += [f"### 📅 Deadline in the next {SOON_DAYS} days", "",
                md_table(report["deadline_soon"], "Deadline"), ""]
    unknown = [r for r in report["links"] if r["result"] == "UNKNOWN"]
    if unknown:
        out += ["<details><summary>Unknown (likely bot protection; check by hand if it persists)</summary>",
                "", md_table(unknown, "Why"), "", "</details>", ""]
    if not (dead or report["past_deadline"]):
        out += ["Nothing needs action. ✅", ""]
    return "\n".join(out)


def main():
    listings = json.loads(LISTINGS.read_text())
    report = run(listings, fetch_links="--no-fetch" not in sys.argv)
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(markdown(report))
    if "--strict" in sys.argv and needs_action(report):
        sys.exit(1)


if __name__ == "__main__":
    main()
