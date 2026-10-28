# Who's Paying Your MP?

Who pays MPs, and who gives them gifts. Built from the House of Commons Register of Members' Financial Interests.

- **Find your MP** by name, constituency or postcode.
- **Parties**: who takes most, per MP and in total, where each party's money comes from, and payers who fund more than one party.
- **Running totals** since the July 2024 election, by type, sector, payer and MP.
- **What changed** between the two latest registers.
- **Search** every payment, donation, gift and paid trip.

## How it updates

A GitHub Action (`.github/workflows/update.yml`) runs on Tuesday and Thursday mornings:

1. `scripts/fetch.py` downloads any new register from the official API (interests-api.parliament.uk), plus the full history including expired entries.
2. `scripts/build.py` turns the CSVs into the JSON files in `site/data/`.
3. The site in `site/` is published to GitHub Pages.

Run it by hand from the Actions tab ("Run workflow"). Set "backfill" to, say, 30 to pull older registers too.

## Why some entries are years old

The register shows what is live. One-off items drop off 12 months after registration. Ongoing roles stay on while they last. That's why the job also saves every register and the full history: so running totals don't lose items that have dropped off.

## Editing

- Sector labels: `scripts/sectors.py`. The first matching rule wins. `OVR` fixes single payers.
- Payer name merges: `ALIAS` in `scripts/build.py`.
- Pin a payer to the right company: add a line to `data/company_links.csv` (payer name exactly as the site shows it, company number). Hand-checked links override the automatic name match.
- Context notes: add a line to `data/notes.csv` (payer, optional MP, note, source title, source link).

## Run locally

```
pip install pandas
python scripts/fetch.py
python scripts/build.py
cd site && python -m http.server
```

Estimates and sector labels are ours. Check every figure against the linked official entry before publishing.
