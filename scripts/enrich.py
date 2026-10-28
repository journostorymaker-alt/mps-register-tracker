"""Find out more about the organisations that pay MPs.

Companies House (needs a free API key in the CH_API_KEY environment variable / GitHub secret):
  status, type, incorporation date, what the company does (SIC codes), registered office,
  current directors and people with significant control (owners).
Wikidata (no key): short description, website and Wikipedia page, where an exact name match exists.

Results are cached in data/enrich/ so each company is only looked up again every 60 days.
Usage: python scripts/enrich.py
"""
import base64, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENR = os.path.join(ROOT, "data", "enrich")
ENTRIES = os.path.join(ROOT, "site", "data", "entries.json")
UA = {"User-Agent": "mps-register-tracker/1.0 (https://github.com/journostorymaker-alt/mps-register-tracker; public-interest research)"}
START = time.time()


class Budget(Exception):
    pass


def check_budget(limit_min, label):
    if time.time() - START > limit_min * 60:
        raise Budget(f"{label}: time budget used, the rest will be done on the next run")
TODAY = datetime.now(timezone.utc).date()
STALE = timedelta(days=60)


def load(name):
    p = os.path.join(ENR, name)
    return json.load(open(p)) if os.path.exists(p) else {}


def save(name, obj):
    os.makedirs(ENR, exist_ok=True)
    with open(os.path.join(ENR, name), "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=False)


def fresh(rec):
    try:
        return TODAY - datetime.strptime(rec.get("_fetched", "")[:10], "%Y-%m-%d").date() < STALE
    except ValueError:
        return False


def norm(s):
    s = re.sub(r"\(.*?\)", " ", str(s).lower())
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(the|ltd|limited|plc|llp|lp|llc|inc|uk|co|company|group|holdings)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def get_json(url, headers=None, tries=2):
    """Fetch JSON. Returns None for 404. Raises on refusal (401/403) or repeated failure so callers stop early."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (401, 403):
                raise
            if e.code == 429 and i < tries - 1:
                time.sleep(20)
                continue
            if i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(2)
    return None


# ---------------- Companies House ----------------
CH = "https://api.company-information.service.gov.uk"


def ch_get(path, key):
    auth = base64.b64encode((key + ":").encode()).decode()
    time.sleep(0.55)  # stay well under 600 requests per 5 minutes
    return get_json(CH + path, {"Authorization": "Basic " + auth})


def clean_number(n):
    n = re.sub(r"[^A-Za-z0-9]", "", str(n or "")).upper()
    if not n or len(n) > 8:
        return ""
    if n.isdigit():
        n = n.zfill(8)
    elif re.match(r"^[A-Z]{2}\d+$", n):
        n = n[:2] + n[2:].zfill(6)
    return n if re.match(r"^[A-Z0-9]{8}$", n) else ""


def companies(entries, key):
    cache = load("companies.json")
    by_payer = load("ch_names.json")  # payer name -> company number found by exact-name search
    try:
        _companies(entries, key, cache, by_payer)
    finally:
        save("companies.json", cache)
        save("ch_names.json", by_payer)
        print(f"Companies House: {sum(1 for c in cache.values() if c.get('found'))} companies held, {len(by_payer)} names searched", flush=True)


def _companies(entries, key, cache, by_payer):
    numbers = {}
    for r in entries:
        n = clean_number(r.get("co"))
        if n:
            numbers.setdefault(n, set()).add(r["payer"])
    # payers that look like UK companies but gave no number: try an exact-name search
    looks_corp = re.compile(r"\b(ltd|limited|plc|llp)\b", re.I)
    not_org = re.compile(r"individual|government|embassy|ministry|parliament|university|council\b|state of", re.I)
    have_number = {r["payer"] for r in entries if clean_number(r.get("co"))}
    want = {}
    for r in entries:
        if r["payer"] in have_number:
            continue
        corp = looks_corp.search(r.get("raw_payer", "")) or looks_corp.search(r["payer"])
        org = r.get("sector") != "Private individuals" and not not_org.search((r.get("ptype") or "") + " " + r["payer"])
        if corp or org:
            want[r["payer"]] = re.sub(r"\s*\(.*$", "", r.get("raw_payer") or r["payer"]).strip() or r["payer"]
    print(f"Companies House: {len(numbers)} declared numbers, {len(want)} names to search")
    done = 0
    for payer, raw in want.items():
        if payer in by_payer and fresh(by_payer[payer]):
            continue
        check_budget(CH_MINUTES, "Companies House")
        res = ch_get("/search/companies?items_per_page=5&q=" + urllib.parse.quote(raw), key) or {}
        hit = next((i for i in res.get("items", []) if norm(i.get("title")) == norm(raw)), None)
        by_payer[payer] = {"number": hit["company_number"] if hit else "", "_fetched": str(TODAY)}
        done += 1
    for payer, rec in by_payer.items():
        if rec.get("number"):
            numbers.setdefault(rec["number"], set()).add(payer)
    for n, payers in numbers.items():
        if n in cache and fresh(cache[n]):
            cache[n]["payers"] = sorted(payers)
            continue
        check_budget(CH_MINUTES, "Companies House")
        prof = ch_get(f"/company/{n}", key)
        if not prof:
            cache[n] = {"number": n, "found": False, "payers": sorted(payers), "_fetched": str(TODAY)}
            continue
        try:
            offs = ch_get(f"/company/{n}/officers?items_per_page=35", key) or {}
        except urllib.error.HTTPError:
            offs = {}
        try:
            psc = ch_get(f"/company/{n}/persons-with-significant-control?items_per_page=25", key) or {}
        except urllib.error.HTTPError:
            psc = {}
        addr = prof.get("registered_office_address") or {}
        cache[n] = {
            "number": n, "found": True, "payers": sorted(payers),
            "name": prof.get("company_name"), "status": prof.get("company_status"), "type": prof.get("type"),
            "created": prof.get("date_of_creation"), "ceased": prof.get("date_of_cessation"),
            "sic": prof.get("sic_codes") or [],
            "address": ", ".join(x for x in [addr.get("address_line_1"), addr.get("address_line_2"), addr.get("locality"), addr.get("postal_code"), addr.get("country")] if x),
            "officers": [{"name": o.get("name"), "role": o.get("officer_role"), "since": o.get("appointed_on")}
                         for o in offs.get("items", []) if not o.get("resigned_on")][:20],
            "owners": [{"name": p.get("name"), "kind": p.get("kind", "").replace("-person-with-significant-control", "").replace("-", " "),
                        "control": [c.replace("-", " ") for c in p.get("natures_of_control", [])], "since": p.get("notified_on")}
                       for p in psc.get("items", []) if not p.get("ceased_on")][:12],
            "_fetched": str(TODAY),
        }
        done += 1
        if done % 50 == 0:
            save("companies.json", cache); save("ch_names.json", by_payer)
            print(f"  {done} looked up", flush=True)
    return


# ---------------- Wikidata ----------------
WD = "https://www.wikidata.org/w/api.php?"


def wikidata(entries):
    cache = load("wikidata.json")
    totals = {}
    kinds = {}
    for r in entries:
        totals[r["payer"]] = totals.get(r["payer"], 0) + (r.get("since") or r.get("value") or 0)
        kinds.setdefault(r["payer"], set()).add((r.get("ptype") or "").lower())
    names = [p for p, t in totals.items() if t >= 5000 and not any("individual" in k for k in kinds[p]) and r_sector_ok(p, entries)]
    print(f"Wikidata: {len(names)} organisations to check")
    todo = [n for n in names if not (n in cache and fresh(cache[n]))]
    try:
        _wd_lookup(todo, cache)
    finally:
        save("wikidata.json", cache)
        print(f"Wikidata: {sum(1 for v in cache.values() if v.get('id'))} matches held of {len(cache)} checked", flush=True)


def _wd_lookup(todo, cache):
    for n in todo:
        check_budget(WD_MINUTES, "Wikidata")
        res = get_json(WD + urllib.parse.urlencode({"action": "wbsearchentities", "format": "json", "language": "en", "type": "item", "limit": 5, "search": n})) or {}
        hit = next((s for s in res.get("search", []) if norm(s.get("label")) == norm(n) or norm(s.get("match", {}).get("text", "")) == norm(n)), None)
        cache[n] = {"id": hit["id"] if hit else "", "_fetched": str(TODAY)}
        time.sleep(0.2)
    ids = [v["id"] for v in cache.values() if v.get("id") and "label" not in v]
    for i in range(0, len(ids), 40):
        batch = ids[i:i + 40]
        res = get_json(WD + urllib.parse.urlencode({"action": "wbgetentities", "format": "json", "ids": "|".join(batch), "props": "labels|descriptions|claims|sitelinks", "languages": "en", "sitefilter": "enwiki"})) or {}
        for qid, ent in (res.get("entities") or {}).items():
            site = None
            for c in (ent.get("claims") or {}).get("P856", []):
                site = (((c.get("mainsnak") or {}).get("datavalue") or {}).get("value"))
                if site:
                    break
            wiki = ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("title")
            for v in cache.values():
                if v.get("id") == qid:
                    v.update(label=((ent.get("labels") or {}).get("en") or {}).get("value", ""),
                             description=((ent.get("descriptions") or {}).get("en") or {}).get("value", ""),
                             website=site or "", wikipedia=("https://en.wikipedia.org/wiki/" + urllib.parse.quote(wiki.replace(" ", "_"))) if wiki else "")
        time.sleep(0.5)


def sic_codes():
    """Companies House's list of business activity (SIC) codes, read once from its public page."""
    if load("sic.json"):
        return
    import html
    req = urllib.request.Request("https://resources.companieshouse.gov.uk/sic/", headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        page = r.read().decode("utf-8", "replace")
    rows = re.findall(r"<tr[^>]*>\s*<td[^>]*>\s*(\d{5})\s*</td>\s*<td[^>]*>(.*?)</td>", page, re.S | re.I)
    codes = {c: html.unescape(re.sub(r"<[^>]+>", "", d)).strip() for c, d in rows}
    if len(codes) > 500:
        save("sic.json", codes)
    print(f"SIC codes: {len(codes)} read", flush=True)


def r_sector_ok(payer, entries, _memo={}):
    if not _memo:
        for r in entries:
            _memo.setdefault(r["payer"], r.get("sector"))
    return _memo.get(payer) != "Private individuals"


CH_MINUTES = 25   # stop Companies House lookups after this long; carry on next run
WD_MINUTES = 35   # overall clock (Companies House runs first)


def main():
    if not os.path.exists(ENTRIES):
        raise SystemExit("Run scripts/build.py first: enrich reads site/data/entries.json")
    entries = json.load(open(ENTRIES))
    try:
        sic_codes()
    except Exception as e:
        print(f"SIC list not read: {e}", flush=True)
    key = os.environ.get("CH_API_KEY", "").strip()
    if key:
        try:
            companies(entries, key)
        except Exception as e:
            print(f"Companies House stopped: {e}", flush=True)
    else:
        print("Companies House: no CH_API_KEY set, skipping", flush=True)
    try:
        wikidata(entries)
    except Exception as e:
        print(f"Wikidata stopped: {e}", flush=True)


if __name__ == "__main__":
    main()
