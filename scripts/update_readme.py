#!/usr/bin/env python3
"""Regenerate the README tables from listings.json.

Usage:
    python3 scripts/update_readme.py          # rewrite README.md in place
    python3 scripts/update_readme.py --check  # exit 1 if README.md is out of date

Each table in README.md lives between a pair of markers:
    <!-- TABLE_START:PM -->
    <!-- TABLE_END:PM -->
Everything outside the markers is hand-written and left alone.
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISTINGS = ROOT / "listings.json"
README = ROOT / "README.md"

CATEGORIES = {
    "PM": "PM",
    "Strategy & BizOps": "STRATEGY",
    "PMM & GTM": "PMM",
    "Finance & Corp Dev": "FINANCE",
}
STATUSES = {"open", "closed", "expected"}
SPONSORSHIP = {"yes": "✅", "no": "🚫", "unknown": "—"}
REQUIRED = ["company", "role", "category", "locations", "url", "status"]

# Open first, then not-yet-open, then closed; newest posting first within each.
STATUS_ORDER = {"open": 0, "expected": 1, "closed": 2}


def validate(listings):
    errors = []
    for i, item in enumerate(listings):
        label = f"#{i} ({item.get('company', '?')} - {item.get('role', '?')})"
        for field in REQUIRED:
            if not item.get(field):
                errors.append(f"{label}: missing '{field}'")
        if item.get("category") not in CATEGORIES:
            errors.append(f"{label}: category must be one of {list(CATEGORIES)}")
        if item.get("status") not in STATUSES:
            errors.append(f"{label}: status must be one of {sorted(STATUSES)}")
        if item.get("sponsorship", "unknown") not in SPONSORSHIP:
            errors.append(f"{label}: sponsorship must be one of {list(SPONSORSHIP)}")
        posted = item.get("date_posted")
        if posted:
            try:
                date.fromisoformat(posted)
            except ValueError:
                errors.append(f"{label}: date_posted must be YYYY-MM-DD")
    return errors


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def apply_cell(item):
    url = item["url"]
    if item["status"] == "open":
        return f"[Apply]({url})"
    if item["status"] == "expected":
        return f"⏳ [Careers page]({url})"
    return f"🔒 [Closed]({url})"


def posted_cell(item):
    posted = item.get("date_posted")
    if not posted:
        return "—"
    return date.fromisoformat(posted).strftime("%b %d")


def render_table(rows):
    if not rows:
        return "_Nothing tracked yet. [Submit a role](../../issues/new/choose)!_"
    rows = sorted(
        rows,
        key=lambda r: (
            STATUS_ORDER[r["status"]],
            # Newest first; undated rows sink to the bottom of their status group.
            -(date.fromisoformat(r["date_posted"]).toordinal() if r.get("date_posted") else 0),
            r["company"].lower(),
        ),
    )
    lines = [
        "| Company | Role | Location | Application | Pay | Visa | Posted | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        company = f"**{cell(r['company'])}**"
        role = cell(r["role"])
        if r["status"] == "closed":
            company, role = f"~~{company}~~", f"~~{role}~~"
        lines.append(
            "| "
            + " | ".join(
                [
                    company,
                    role,
                    cell("</br>".join(r["locations"])),
                    apply_cell(r),
                    cell(r.get("pay") or "—"),
                    SPONSORSHIP[r.get("sponsorship", "unknown")],
                    posted_cell(r),
                    cell(r.get("notes") or ""),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def render_counts(listings):
    open_count = sum(1 for r in listings if r["status"] == "open")
    expected = sum(1 for r in listings if r["status"] == "expected")
    companies = len({r["company"] for r in listings})
    return (
        f"**{open_count}** open roles · **{expected}** not yet open · "
        f"**{companies}** companies tracked"
    )


def build(readme, listings):
    sections = {key: [] for key in CATEGORIES.values()}
    for item in listings:
        sections[CATEGORIES[item["category"]]].append(item)
    blocks = {key: render_table(rows) for key, rows in sections.items()}
    blocks["COUNTS"] = render_counts(listings)

    for key, body in blocks.items():
        pattern = re.compile(
            rf"(<!-- TABLE_START:{key} -->\n).*?(\n<!-- TABLE_END:{key} -->)", re.S
        )
        if not pattern.search(readme):
            sys.exit(f"README.md is missing the TABLE_START:{key} / TABLE_END:{key} markers")
        readme = pattern.sub(lambda m: m.group(1) + body + m.group(2), readme)
    return readme


def main():
    listings = json.loads(LISTINGS.read_text())
    errors = validate(listings)
    if errors:
        print("listings.json has problems:\n  " + "\n  ".join(errors))
        sys.exit(1)

    current = README.read_text()
    updated = build(current, listings)

    if "--check" in sys.argv:
        if current != updated:
            print("README.md is out of date. Run: python3 scripts/update_readme.py")
            sys.exit(1)
        print("README.md is up to date.")
        return

    README.write_text(updated)
    print(f"Wrote README.md from {len(listings)} listings.")


if __name__ == "__main__":
    main()
