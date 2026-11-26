"""Which coordinate is right for a West Sumatra post? Decide from the rainfall, not the tables.

For every post in `d_rainfall_west_sumatera.xls`, the candidate positions are:
  - `_SUMBAR/Data Sumbar.XLS` (MONTHLY sheet),
  - `CH_IND/catalog West Sumatera.xls`,
  - the sign-flipped latitude of either, when the latitude is positive (POS-HUJAN region 19 and
    Data Sumbar both carry some unsigned latitudes; review of 2026-11-25).
Rule: decide only when the best candidate is >= 20 km closer than the next, and a sign flip
also needs a partner with r >= 0.5 (anchors are all south of the equator, so the score is biased
toward the southern mirror for weakly correlated posts near the equator). Otherwise "undecided":
the catalogue builder then keeps a single in-province table position, or skips the post.
Evidence: daily rainfall correlation with the other posts (>= 300 shared days). The post's top-3
partners by r are taken only from "anchor" posts (one candidate, or both tables within 5 km,
negative latitude), and each candidate is scored by the median distance to those partners.
Correlation falls with distance, so the right position is the one near its best correlates.

Output: F:/temp/station/additional-sources/_post_position_decisions.csv
(post_key, lat, lon, how, evidence), read by tools/build_post_catalogue.py.
Usage: python tools/check_post_positions.py
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xlrd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wxgrid.readers import post_forms  # noqa: E402

ROOT = Path("F:/temp/station/additional-sources")
SUMBAR_BOX = (-3.6, 1.0, 98.5, 102.0)   # lat min, lat max, lon min, lon max: West Sumatra and its islands


def norm(s):
    s = re.sub(r"\(.*?(\)|$)", " ", str(s).upper()).split(",")[0]
    s = re.sub(r"\b(SMPK|SPP|BPP|SP|PTP|PU|UPP|KPTP|STA|POS)\b\.?", " ", s)
    return re.sub(r"[^A-Z]", "", s)


def km(a, b):
    p = math.pi / 180
    return 6371 * 2 * math.asin(math.sqrt(math.sin((b[0] - a[0]) * p / 2) ** 2 + math.cos(a[0] * p) * math.cos(b[0] * p)
                                          * math.sin((b[1] - a[1]) * p / 2) ** 2))


def table(path, sheet=None):
    wb = xlrd.open_workbook(str(path))
    sh = wb.sheet_by_name(sheet) if sheet else wb.sheet_by_index(0)
    out = {}
    for r in range(1, sh.nrows):
        nm, no, la, lo = (sh.cell_value(r, c) for c in range(4))
        if isinstance(la, float) and isinstance(lo, float) and la != 0:
            out.setdefault(norm(nm), (float(la), float(lo)))
    return out


def inbox(la, lo):
    return SUMBAR_BOX[0] <= la <= SUMBAR_BOX[1] and SUMBAR_BOX[2] <= lo <= SUMBAR_BOX[3]


def main():
    ds = table(ROOT / "DATA IKLIM/_SUMBAR/Data Sumbar.XLS", "MONTHLY")
    cw = table(ROOT / "DATA IKLIM/CH_IND/catalog West Sumatera.xls")
    # daily series straight from the workbook (no catalogue needed)
    coder = post_forms.Coder({"missing_codes": [999], "unmeasurable_codes": [888]}, 2000)
    sheets = post_forms.load_book(ROOT / "DATA IKLIM/CH_IND/d_rainfall_west_sumatera.xls")
    recs = []
    for post, y, m, d, raw in post_forms.lay_station_month_rows(sheets, {}):
        v, f, k = coder(raw)
        if v is not None and not np.isnan(v):
            try:
                recs.append((post, pd.Timestamp(y, m, d), v))
            except ValueError:
                pass
    s = pd.DataFrame(recs, columns=["post", "date", "v"]).drop_duplicates(["post", "date"])
    wide = s.pivot(index="date", columns="post", values="v")
    # candidates per post
    cand = {}
    for post in wide.columns:
        k = norm(post.split("|", 1)[1])
        c = []
        for src, tab in (("Data Sumbar", ds), ("catalog West Sumatera", cw)):
            m = post_forms_match(k, tab)
            if m:
                la, lo = tab[m]
                c.append((src, la, lo))
                if la > 0:
                    c.append((src + " sign-flipped", -la, lo))
        cand[post] = [x for x in c if inbox(x[1], x[2])]
    anchors = {}
    for p, c in cand.items():
        plain = [x for x in c if "flipped" not in x[0]]
        if plain and all(x[1] < 0 for x in plain) and (len(plain) == 1 or km(plain[0][1:], plain[1][1:]) <= 5):
            anchors[p] = plain[0][1:]
    r = wide.corr(min_periods=300)
    rows = []
    for p, c in cand.items():
        plain = [x for x in c if "flipped" not in x[0]]
        need = (not c) or len(c) > 1 and (any("flipped" in x[0] for x in c) or
                                         (len(plain) == 2 and km(plain[0][1:], plain[1][1:]) > 5))
        if not need and p in anchors:
            continue
        partners = r[p].drop(p).dropna()
        partners = partners[[q in anchors and q != p for q in partners.index]].sort_values(ascending=False).head(3)
        scored, seen = [], set()
        for src, la, lo in c:
            if (round(la, 4), round(lo, 4)) in seen:   # both tables give the same position
                continue
            seen.add((round(la, 4), round(lo, 4)))
            dist = [km((la, lo), anchors[q]) for q in partners.index]
            scored.append((float(np.median(dist)) if dist else np.nan, src, la, lo))
        scored.sort(key=lambda x: (np.isnan(x[0]), x[0]))
        ev = "; ".join(f"{q} r={partners[q]:.2f}" for q in partners.index)
        opts = "; ".join(f"{src} ({la:.4f},{lo:.4f}) median {d:.0f} km" for d, src, la, lo in scored)
        top_r = float(partners.iloc[0]) if len(partners) else 0.0
        decided = None
        if len(scored) >= 2 and not np.isnan(scored[0][0]) and scored[1][0] - scored[0][0] >= 20:
            best = scored[0]
            # a sign flip needs a strong partner: anchors are all south of the equator, so a weakly
            # correlated post near the equator always looks closer when flipped south (bias)
            if "flipped" not in best[1] or top_r >= 0.5:
                decided = best
        if decided:
            d, src, la, lo = decided
            rows.append(dict(post_key=p, lat=la, lon=lo, how=f"neighbour rainfall: {src}", evidence=f"{opts} | partners {ev}"))
        else:
            rows.append(dict(post_key=p, lat=np.nan, lon=np.nan, how="undecided",
                             evidence=f"{opts or 'no candidate inside West Sumatra'} | partners {ev}"))
    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "_post_position_decisions.csv", index=False)
    pd.set_option("display.width", 250)
    print(f"anchors {len(anchors)}, posts needing a decision {len(out)}")
    print(out.to_string(index=False, max_colwidth=160))


def post_forms_match(k, tab):
    """Same rule as build_post_catalogue.best_match: exact, else one candidate with similarity >= 0.85."""
    import difflib
    if len(k) < 4:
        return None
    if k in tab:
        return k
    c = [t for t in tab if len(t) >= 4 and difflib.SequenceMatcher(None, k, t).ratio() >= 0.85]
    return c[0] if len(c) == 1 else None


if __name__ == "__main__":
    main()
