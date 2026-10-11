# Contributing

This list only stays useful if people keep it current. Every new posting, closed role, or broken link you report helps the next person.

## The easy way: open an issue

- **Found a new role?** Use the [➕ New internship](../../issues/new?template=new_role.yml) form.
- **Role closed, link broken, or info wrong?** Use the [✏️ Update or close a role](../../issues/new?template=update_role.yml) form.

A maintainer will add it to `listings.json` and regenerate the README.

## The direct way: open a pull request

1. Edit [`listings.json`](listings.json). Each role is one object:

   ```json
   {
     "company": "Google",
     "role": "MBA Product Manager Intern, Summer 2027",
     "category": "PM",
     "locations": ["Mountain View, CA", "New York, NY"],
     "url": "https://careers.google.com/jobs/results/...",
     "date_posted": "2026-10-01",
     "status": "open",
     "pay": "$55–$65/hr",
     "sponsorship": "unknown",
     "notes": "Must be enrolled in a full-time MBA graduating in 2028"
   }
   ```

   | Field | Allowed values |
   | --- | --- |
   | `category` | `PM`, `Strategy & BizOps`, `PMM & GTM`, `Finance & Corp Dev` |
   | `status` | `open`, `closed`, `expected` (company usually hires MBA interns, but the 2027 posting isn't up yet) |
   | `sponsorship` | `yes`, `no`, `unknown` (go by what the posting says) |
   | `date_posted` | `YYYY-MM-DD`, or `null` if unknown |
   | `pay` | Only what the posting publishes (pay-transparency ranges count). **Never estimate.** Use `null` if not listed. |

2. Regenerate the README:

   ```bash
   python3 scripts/update_readme.py
   ```

3. Commit both `listings.json` and `README.md`. CI runs `python3 scripts/update_readme.py --check` and fails if they're out of sync or a field is invalid.

## What counts

- ✅ Summer 2027 internships aimed at **full-time MBA students** (or roles that explicitly accept MBAs) at tech companies, or in the tech/product org of a non-tech company
- ✅ PM, strategy/BizOps, product marketing/GTM, and finance/corp dev roles
- ❌ Undergrad, PhD-only, or SWE/research internships (there are [great lists](https://github.com/SimplifyJobs/Summer2026-Internships) for those)
- ❌ Links to reposts or aggregators. Please link the company's own posting.

## Closing roles

When a posting comes down, set `"status": "closed"` instead of deleting it. Closed roles show up struck through with a 🔒, which helps next year's class see who hired and when.
