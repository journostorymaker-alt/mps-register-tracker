"""Download Commons registers of interests from the official Parliament API.

Usage:
  python scripts/fetch.py              # latest register + full history
  python scripts/fetch.py --backfill 10  # also the 10 most recent registers

Uses only the Python standard library.
API docs: https://interests-api.parliament.uk/index.html
"""
import argparse, io, json, os, sys, time, urllib.parse, urllib.request, zipfile
from datetime import datetime, timezone

API = "https://interests-api.parliament.uk/api/v2"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")


def get(path, params=None, tries=4):
    url = API + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mps-register-tracker (GitHub Actions)"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except Exception as e:  # network blips: wait and retry
            print(f"  attempt {i + 1} failed for {url}: {e}", file=sys.stderr)
            time.sleep(10 * (i + 1))
    raise SystemExit(f"Could not download {url}")


def registers():
    items, skip = [], 0
    while True:
        page = json.loads(get("/Registers", {"Type": "Commons", "Skip": skip, "Take": 20}))
        items += page.get("items") or []
        skip += 20
        if skip >= page.get("totalResults", 0) or not page.get("items"):
            break
    items.sort(key=lambda r: r["publishedDate"], reverse=True)
    return items


def unzip_to(blob, folder):
    os.makedirs(folder, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if name.lower().endswith(".csv"):
                with open(os.path.join(folder, os.path.basename(name)), "wb") as f:
                    f.write(z.read(name))


def folder_for(reg):
    day = datetime.fromisoformat(reg["publishedDate"][:10]).strftime("%Y-%m-%d")
    return os.path.join(RAW, f"register-{reg['id']}-{day}")


MEMBERS_API = "https://members-api.parliament.uk/api/Members/"
MEMBERS_FILE = os.path.join(ROOT, "data", "members.json")


def member_ids():
    import csv, glob
    ids = set()
    for f in glob.glob(os.path.join(RAW, "*", "*.csv")):
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("Mnis Id"):
                    ids.add(row["Mnis Id"])
    return sorted(ids, key=int)


def one_member(mid):
    for i in range(3):
        try:
            req = urllib.request.Request(MEMBERS_API + mid, headers={"User-Agent": "mps-register-tracker (GitHub Actions)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                v = json.loads(r.read())["value"]
            hm = v.get("latestHouseMembership") or {}
            p = v.get("latestParty") or {}
            return mid, {"name": v.get("nameDisplayAs"), "party": p.get("name") or "", "abbr": p.get("abbreviation") or "",
                         "colour": p.get("backgroundColour") or "", "seat": hm.get("membershipFrom") or "",
                         "house": hm.get("house"), "end": (hm.get("membershipEndDate") or "")[:10]}
        except Exception as e:
            err = e
            time.sleep(3 * (i + 1))
    print(f"  member {mid} failed: {err}", file=sys.stderr)
    return mid, None


def members():
    """Party, constituency and status for every MP in the data, from the Members API.
    Refreshed in full each run so defections and by-elections are picked up."""
    from concurrent.futures import ThreadPoolExecutor
    old = json.load(open(MEMBERS_FILE)) if os.path.exists(MEMBERS_FILE) else {}
    ids = member_ids()
    print(f"Fetching {len(ids)} members")
    with ThreadPoolExecutor(8) as ex:
        got = dict(ex.map(one_member, ids))
    out = {k: (got.get(k) or old.get(k)) for k in ids if got.get(k) or old.get(k)}
    with open(MEMBERS_FILE, "w") as f:
        json.dump(out, f, indent=0, sort_keys=True)
    print(f"  saved {len(out)} members ({sum(1 for v in got.values() if v is None)} failed, kept old copy where held)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=1, help="how many recent registers to make sure we hold")
    ap.add_argument("--no-history", action="store_true")
    a = ap.parse_args()

    regs = registers()
    print(f"API lists {len(regs)} Commons registers; latest is {regs[0]['id']} on {regs[0]['publishedDate'][:10]}")
    new = []
    for reg in regs[: max(1, a.backfill)]:
        folder = folder_for(reg)
        if os.path.isdir(folder) and os.listdir(folder):
            continue
        print(f"Downloading register {reg['id']} ({reg['publishedDate'][:10]})")
        unzip_to(get("/Interests/csv", {"RegisterId": reg["id"], "Type": "Commons"}), folder)
        new.append(reg["id"])
        time.sleep(2)

    if not a.no_history:
        # Every interest ever published, including ones that have expired off the live register.
        print("Downloading full history (expired entries included)")
        hist = os.path.join(RAW, "history")
        try:
            blob = get("/Interests/csv", {"Type": "Commons", "ExcludeExpired": "false"})
            tmp = hist + ".new"
            unzip_to(blob, tmp)
            if not any(f.endswith(".csv") for f in os.listdir(tmp)):
                raise SystemExit("history download held no CSV files")
            for f in os.listdir(hist) if os.path.isdir(hist) else []:
                os.remove(os.path.join(hist, f))
            os.makedirs(hist, exist_ok=True)
            for f in os.listdir(tmp):
                os.replace(os.path.join(tmp, f), os.path.join(hist, f))
            os.rmdir(tmp)
            with open(os.path.join(hist, "_fetched.txt"), "w") as f:
                f.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ") + "\n")
        except (SystemExit, Exception) as e:  # keep the last good history and carry on
            print(f"WARNING: full history not updated: {e}", file=sys.stderr)

    try:
        members()
    except Exception as e:
        print(f"WARNING: members not updated: {e}", file=sys.stderr)

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"new_registers={','.join(map(str, new))}\n")
    print("New registers:", new or "none")


if __name__ == "__main__":
    main()
