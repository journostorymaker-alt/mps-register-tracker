"""Turn the downloaded registers into the JSON files the web page reads.

Reads  data/raw/register-<id>-<date>/   one folder per register edition
       data/raw/history/                every interest ever published (optional)
Writes site/data/*.json
"""
import glob, json, os, re, sys
from datetime import date, datetime, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sectors import sector  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "site", "data")
ELECTION = date(2024, 7, 4)
V = "Version 1 "
MONEY = ["1.1", "1.2", "2", "3", "4", "5"]
KIND = {"1.1": "Paid work (one-off)", "1.2": "Paid work (regular)", "2": "Donation or support",
        "3": "Gift or hospitality (UK)", "4": "Paid overseas trip", "5": "Gift from abroad"}
OTHER = {"1": "Job or paid role", "6": "Land and property", "7": "Shareholding", "8": "Other interest",
         "9": "Family member employed", "10": "Family member who lobbies"}


# ---------- loading ----------
def cat_of(path):
    m = re.search(r"Commons_(\d+(?:[._]\d+)?)_", os.path.basename(path))
    return m.group(1).replace("_", ".") if m else None


def load_folder(folder):
    cats = {}
    for f in glob.glob(os.path.join(folder, "*.csv")):
        c = cat_of(f)
        if c:
            cats[c] = pd.read_csv(f, encoding="utf-8-sig", dtype=str).fillna("")
    return cats


def editions():
    eds = []
    for folder in glob.glob(os.path.join(RAW, "register-*")):
        m = re.search(r"register-(\d+)-(\d{4}-\d{2}-\d{2})$", folder)
        if m:
            eds.append({"id": int(m.group(1)), "date": m.group(2), "folder": folder})
    return sorted(eds, key=lambda e: e["date"])


# ---------- tidying ----------
def num(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def day(x):
    try:
        return datetime.strptime(str(x)[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def mp_name(s):
    return re.sub(r"^(.*?), (.*)$", r"\2 \1", s)


def pkey(s):
    s = re.sub(r"\(via .*?\)", "", str(s)).lower()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[^a-z0-9 &]", " ", s)
    s = re.sub(r"\b(ltd|limited|plc|llp|llc|inc|the|uk)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Same payer under different spellings. Check these: they are judgement calls.
ALIAS = {"lord sainsbury of turville": "lord david sainsbury", "lord david sainsbury of turville": "lord david sainsbury",
         "lord sainsbury": "lord david sainsbury", "fran perrin": "francesca perrin"}


def short(s, n=240):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------- money rows ----------
def money_rows(cats):
    out = []
    parents = cats.get("1", pd.DataFrame(columns=["Id"])).set_index("Id")
    for c in ("1.1", "1.2"):
        for _, r in cats.get(c, pd.DataFrame()).iterrows():
            par = parents.loc[r["Parent Interest ID"]] if r["Parent Interest ID"] in parents.index else None
            if isinstance(par, pd.DataFrame):
                par = par.iloc[0]
            payer = par[V + "PayerName"] if par is not None else ""
            nature = par[V + "PayerNatureOfBusiness"] if par is not None else ""
            role = par[V + "JobTitle"] if par is not None else ""
            if r.get(V + "IsUltimatePayerDifferent") == "True" and r.get(V + "UltimatePayerName"):
                nature = r.get(V + "UltimatePayerNatureOfBusiness") or nature
                payer = f"{r[V + 'UltimatePayerName']} (via {payer})" if payer else r[V + "UltimatePayerName"]
            out.append(dict(id=r["Id"], cat=c, mp=r["Member"], payer=payer, ptype=nature,
                            value=num(r[V + "Value"]), freq=(r.get(V + "RegularityOfPayment") or "").lower(),
                            start=day(r.get(V + "StartDate")), end=day(r.get(V + "EndDate")),
                            received=day(r.get(V + "ReceivedDate")), registered=day(r[V + "Registered"]),
                            detail=" | ".join(x for x in (role, r[V + "PaymentDescription"]) if x),
                            charity=r.get(V + "IsPaymentDonated") == "True", link=r["Link"]))
    for c in ("2", "3", "5"):
        for _, r in cats.get(c, pd.DataFrame()).iterrows():
            pt = r[V + "DonorStatus"] + (" / " + r[V + "DonorOtherDetails"] if r.get(V + "DonorOtherDetails") else "")
            out.append(dict(id=r["Id"], cat=c, mp=r["Member"], payer=r[V + "DonorName"], ptype=pt,
                            value=num(r[V + "Value"]), freq="", start=None, end=None,
                            received=day(r[V + "ReceivedDate"]), registered=day(r[V + "Registered"]),
                            detail=r[V + "PaymentDescription"], charity=False, link=r["Link"]))
    for _, r in cats.get("4", pd.DataFrame()).iterrows():
        dest = ", ".join(r[k] for k in r.index if k.startswith(V + "Country") and r[k])
        for i in range(10):
            n = r.get(V + f"Name (.{i}.0)", "")
            if not n:
                continue
            out.append(dict(id=r["Id"] + (f"-{i}" if i else ""), cat="4", mp=r["Member"], payer=n,
                            ptype="Individual" if r.get(V + f"IsPrivateIndividual (.{i}.1)") == "True" else "",
                            value=num(r.get(V + f"Value (.{i}.5)", "")), freq="", start=None, end=None,
                            received=day(r[V + "StartDate"]), registered=day(r[V + "Registered"]),
                            detail=" | ".join(x for x in (dest, r[V + "Purpose"], r.get(V + f"PaymentDescription (.{i}.4)", "")) if x),
                            charity=False, link=r["Link"]))
    return out


PER_MONTH = {"monthly": 1, "quarterly": 1 / 3, "yearly": 1 / 12, "weekly": 52 / 12}


def months_between(a, b):
    """Calendar months a..b inclusive, as (year, month)."""
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def spread(r, upto):
    """Money in each calendar month since the election. One-offs land on one date.
    Regular payments are spread across the months the agreement ran (an estimate)."""
    v = r["value"] or 0
    if not v:
        return {}
    if r["cat"] != "1.2":
        d = r["received"] or r["registered"]
        return {f"{d.year}-{d.month:02d}": v} if d and d >= ELECTION else {}
    start = max(r["start"] or r["registered"] or ELECTION, ELECTION)
    end = min(r["end"] or upto, upto)
    if end < start:
        return {}
    per = v * PER_MONTH.get(r["freq"], 1 / 12)
    return {f"{y}-{m:02d}": per for y, m in months_between(start, end)}


# ---------- changes between two editions ----------
def changes(old, new):
    rows = []
    o_m = {r["id"]: r for r in money_rows(old)}
    for r in money_rows(new):
        if r["id"] not in o_m:
            rows.append(("new_money", r))
        else:
            a = o_m[r["id"]]
            diff = [k for k in ("payer", "value", "detail") if str(a[k]) != str(r[k])]
            if diff:
                rows.append(("changed", dict(id=r["id"], mp=mp_name(r["mp"]), area=KIND[r["cat"]],
                                             before=" | ".join(f"{k}: {a[k]}" for k in diff)[:300],
                                             after=" | ".join(f"{k}: {r[k]}" for k in diff)[:300], link=r["link"])))
    for c, label in OTHER.items():
        o, n = old.get(c), new.get(c)
        if n is None or o is None:
            continue
        oi = o.set_index("Id")
        for _, r in n.iterrows():
            if r["Id"] not in oi.index:
                extra = r.get(V + "PayerNatureOfBusiness", "") or r.get(V + "Employer", "")
                rows.append(("changed", dict(id=r["Id"], mp=mp_name(r["Member"]), area=label, before="",
                                             after=short(r[V + "Summary"] + (f" ({extra})" if extra and extra not in r[V + "Summary"] else "")),
                                             link=r["Link"])))
                continue
            a = oi.loc[r["Id"]]
            keys = [k for k in (V + "PayerName", V + "Employer", V + "JobTitle", V + "Summary", V + "EndDate",
                                V + "NumberOfProperties", V + "RentalIncomeDetails") if k in n.columns and k in o.columns and a[k] != r[k]]
            if keys:
                rows.append(("changed", dict(id=r["Id"], mp=mp_name(r["Member"]), area=label,
                                             before=short(" | ".join(f"{k[len(V):]}: {a[k] or '(blank)'}" for k in keys), 300),
                                             after=short(" | ".join(f"{k[len(V):]}: {r[k] or '(blank)'}" for k in keys), 300),
                                             link=r["Link"])))
    gone = [mp_name(r["Member"]) + ": " + r[V + "Summary"] for c in MONEY + list(OTHER)
            if old.get(c) is not None and new.get(c) is not None
            for _, r in old[c].iterrows() if r["Id"] not in set(new[c]["Id"])]
    return rows, gone


# ---------- main ----------
def main():
    eds = editions()
    if not eds:
        raise SystemExit("No registers in data/raw. Run scripts/fetch.py first.")
    latest = eds[-1]
    cats = {e["id"]: load_folder(e["folder"]) for e in eds}
    upto = datetime.strptime(latest["date"], "%Y-%m-%d").date()

    # Pool every money entry we have ever seen. Newer copies win.
    pool = {}
    hist = os.path.join(RAW, "history")
    has_history = os.path.isdir(hist) and bool(glob.glob(os.path.join(hist, "*.csv")))
    sources = ([load_folder(hist)] if has_history else []) + [cats[e["id"]] for e in eds]
    for cs in sources:
        for r in money_rows(cs):
            pool[r["id"]] = r
    live = {r["id"] for r in money_rows(cats[latest["id"]])}

    rows = []
    for r in pool.values():
        k = pkey(r["payer"])
        k = ALIAS.get(k, k)
        r["pkey"] = k
        r["months"] = spread(r, upto)
        r["since"] = round(sum(r["months"].values()), 2)
        r["sector"] = sector(k, r["payer"], r["ptype"], r["cat"])
        rows.append(r)
    df = pd.DataFrame(rows)
    names = df.groupby("pkey")["payer"].agg(lambda x: re.sub(r"\s*\(via .*?\)", "", x.value_counts().index[0]))
    names.update(pd.Series({"lord david sainsbury": "Lord (David) Sainsbury of Turville", "francesca perrin": "Francesca (Fran) Perrin"}))
    df["payer_group"] = df.pkey.map(names)
    df["mp_name"] = df.mp.map(mp_name)
    df["kind"] = df.cat.map(KIND)
    since = df[df.since > 0]

    os.makedirs(OUT, exist_ok=True)

    def dump(name, obj):
        with open(os.path.join(OUT, name), "w") as f:
            json.dump(obj, f, separators=(",", ":"), default=str)

    # monthly flows for the running-total chart
    mon = {}
    for _, r in since.iterrows():
        for m, v in r.months.items():
            key = (m, r.kind, r.sector)
            mon[key] = mon.get(key, 0) + v
    dump("monthly.json", [{"month": m, "type": k, "sector": s, "amount": round(v, 2)} for (m, k, s), v in sorted(mon.items())])

    def top(x, n=6):
        vc = x.value_counts()
        return ", ".join(vc.index[:n]) + (" and others" if len(vc) > n else "")

    pay = since.groupby("payer_group").agg(sector=("sector", lambda x: x.value_counts().index[0]), total=("since", "sum"),
                                           entries=("id", "size"), mps=("mp", "nunique"), mp_list=("mp_name", top),
                                           types=("kind", lambda x: ", ".join(sorted(set(x))))).reset_index()
    pay = pay.rename(columns={"payer_group": "payer"}).sort_values("total", ascending=False)
    pay["total"] = pay.total.round(2)
    dump("payers.json", pay.to_dict("records"))

    mps = since.groupby("mp_name").agg(total=("since", "sum"), entries=("id", "size"), payers=("payer_group", "nunique"),
                                       top_payers=("payer_group", top)).reset_index().rename(columns={"mp_name": "mp"})
    mps = mps.sort_values("total", ascending=False)
    mps["total"] = mps.total.round(2)
    dump("mps.json", mps.to_dict("records"))

    ent = since.assign(live=since.id.isin(live), detail=since.detail.map(short))
    ent = ent.sort_values("since", ascending=False)
    dump("entries.json", [dict(id=r.id, mp=r.mp_name, type=r.kind, payer=r.payer_group, sector=r.sector,
                               value=r.value, since=r.since, freq=r.freq, date=str(r.received or r.start or ""),
                               registered=str(r.registered or ""), live=bool(r.live), charity=bool(r.charity),
                               detail=r.detail, link=r.link) for r in ent.itertuples()])

    # what changed in the latest fortnight
    ch = {"from": None, "to": latest["date"], "new": [], "other": [], "gone": []}
    if len(eds) > 1:
        prev = eds[-2]
        ch["from"] = prev["date"]
        rows_c, gone = changes(cats[prev["id"]], cats[latest["id"]])
        by_id = df.set_index("id")
        for kind_, r in rows_c:
            if kind_ == "new_money":
                x = by_id.loc[r["id"]]
                ch["new"].append(dict(id=r["id"], mp=x.mp_name, type=x.kind, payer=x.payer_group, sector=x.sector,
                                      value=r["value"], date=str(r["received"] or r["start"] or ""), detail=short(r["detail"]), link=r["link"]))
            else:
                ch["other"].append(r)
        ch["gone"] = gone
        ch["new"].sort(key=lambda r: -(r["value"] or 0))
    dump("changes.json", ch)

    dump("summary.json", {
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "latest_register": {"id": latest["id"], "date": latest["date"]}, "registers_held": [{"id": e["id"], "date": e["date"]} for e in eds],
        "has_history": has_history, "since": str(ELECTION),
        "total_since": round(float(since.since.sum()), 2), "entries_since": int(len(since)),
        "mps_since": int(since.mp.nunique()), "payers_since": int(since.payer_group.nunique()),
        "live_entries": len(live),
    })
    print(f"Built from {len(eds)} registers (history: {has_history}). {len(since)} entries since {ELECTION}, "
          f"£{since.since.sum():,.0f}. Latest changes: {len(ch['new'])} new money entries, {len(ch['other'])} other.")


if __name__ == "__main__":
    main()
