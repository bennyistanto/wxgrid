"""QC focus 3: "X" cells in the CH_IND year files and possible accumulated readings after them.

Card rule (Perka BMG SK.32/TL.202/KB/BMG-2006, Lampiran IV, F62): X = no reading; the next reading
may hold more than one day. Inputs are the text dumps of the recheck (one line per sheet row,
"r<row> TAB <cells>"): F:/temp/station/additional_recheck/dump/DATA_IKLIM_CH_IND*.txt.
1. Per dump and sheet: count cells equal to x/X, split into (a) day columns R1..R31 of the first
   sheet (the only sheet the chind reader opens: station_month_grid uses sheet_by_index(0)) and
   (b) anything else; list where the first-sheet X cells of the chind year files sit.
2. JABOTABEK99 sheet of 1999.xls (10 Jakarta-area posts, not read by any source; no coordinates):
   for each X run followed by a numeric reading, compare that reading with
   - the post's wet values elsewhere (median, share above the post's p95 of other wet days),
   - the mean of the other lowland posts in the sheet (Gunungmas, a highland post, left out) on the
     day, and summed over the X run plus the day; a control uses ordinary days,
   - CPC-UNI at the Jakarta cell (-6.2, 106.8) on the day and summed over the run plus the day
     (CPC day D-1 for sheet day D, F38),
   - the dekad totals (columns I, II, III) against the sum of the numeric values.
3. Reach: chind 1999 values that sit right after an X cell of a read column.
Writes F:/temp/station/qc_phase2/chind_x_*.csv. Run: python tools/qc_chind_x.py
"""
import glob
import os
import re

import numpy as np
import pandas as pd

import qc_phase2_common as q

pd.set_option("display.width", 250)
DUMP = "F:/temp/station/additional_recheck/dump"


def isx(t):
    return t.strip().lower() == "x"


def sheets(path):
    out, name, rows = {}, None, []
    for line in open(path, encoding="utf-8", errors="replace"):
        if line.startswith("## SHEET"):
            if name is not None:
                out[name] = rows
            name = re.search(r"'(.*)'", line).group(1)
            rows = []
        elif line.startswith("r") and name is not None:
            p = line.rstrip("\n").split("\t")
            rows.append((int(p[0][1:]), p[1:]))
    if name is not None:
        out[name] = rows
    return out


cnt, first_x = [], []
for f in sorted(glob.glob(f"{DUMP}/DATA_IKLIM_CH_IND*.txt")):
    base = os.path.basename(f)
    yr = re.search(r"CH_IND(?:\.zip)?_((?:19|20)\d\d)\.xls\.txt$", base, re.I)
    sh = sheets(f)
    for k, (sn, rows) in enumerate(sh.items()):
        hdr = next((c for _, c in rows if any(str(x).strip().upper() == "R1" for x in c)), None)
        dcols = [i for i, x in enumerate(hdr) if re.fullmatch(r"R([1-9]|[12]\d|3[01])", str(x).strip().upper())] if hdr else []
        n_day = n_other = 0
        for r, c in rows:
            for i, t in enumerate(c):
                if isx(t):
                    if k == 0 and i in dcols:
                        n_day += 1
                    else:
                        n_other += 1
                    if k == 0 and yr:
                        allmiss = all(v.strip() in ("9999", "") for j, v in enumerate(c) if j in dcols)
                        first_x.append((base, sn, r, i, "R-day" if i in dcols else "outside R1..R31",
                                        " ".join(c[:4]), allmiss))
        if n_day + n_other:
            cnt.append((base, bool(yr), sn, k, n_day, n_other))
C = pd.DataFrame(cnt, columns=["dump", "chind_year_file", "sheet", "sheet_index", "x_in_read_day_cols", "x_elsewhere"])
C.to_csv(f"{q.OUT}/chind_x_counts.csv", index=False)
print("x/X cells in CH_IND dumps (chind reads sheet index 0, R1..R31, of the year files):")
print(C.to_string(index=False))
FX = pd.DataFrame(first_x, columns=["dump", "sheet", "row", "col", "where", "row_head", "row_all_9999"])
print("\nX cells in sheet 0 of chind year files:")
print(FX.to_string(index=False))

# ---- 2. JABOTABEK99
MON = {"JAN": 1, "PEB": 2, "FEB": 2, "MAR": 3, "APR": 4, "MEI": 5, "JUN": 6, "JUL": 7, "AGU": 8, "AGS": 8,
       "SEP": 9, "OKT": 10, "NOP": 11, "NOV": 11, "DES": 12}


def num(s):
    s = s.strip()
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else np.nan


J = sheets(f"{DUMP}/DATA_IKLIM_CH_IND_1999.xls.txt")["JABOTABEK99"]
recs, dek = [], []
for r, c in J:
    if len(c) < 35 or c[1].strip() in ("", "NM STASIUN"):
        continue
    mo = MON.get(c[2].strip().upper()[:3])
    stn = c[1].strip()
    if mo is None:
        continue
    for d, t in enumerate(c[4:35], start=1):
        try:
            date = pd.Timestamp(1999, mo, d)
        except ValueError:
            continue
        t = t.strip()
        if isx(t):
            recs.append((stn, date, np.nan, "x"))
        elif t in ("", "-"):
            recs.append((stn, date, np.nan, "blank"))
        elif np.isfinite(num(t)):
            recs.append((stn, date, num(t), "v"))
        else:
            recs.append((stn, date, np.nan, "text"))
    dek.append((stn, mo) + tuple(num(c[i]) if len(c) > i else np.nan for i in (35, 36, 37)))
D = pd.DataFrame(recs, columns=["stn", "date", "value", "kind"])
print(f"\nJABOTABEK99: {D.stn.nunique()} posts, {len(D)} dated cells, kinds {D.kind.value_counts().to_dict()}")
V = D.pivot(index="date", columns="stn", values="value")
K = D.pivot(index="date", columns="stn", values="kind")
cpc = q.CPCField()
cs = cpc.series(-6.2, 106.8)
cs.index = cs.index + pd.Timedelta(days=1)  # CPC D-1 -> sheet day D
lowl = [s for s in V.columns if s != "GUNUNGMAS"]
lagr = {}
for k in [-1, 0, 1]:
    lagr[k] = q.pearson(V[lowl].mean(axis=1).values, cs.reindex(V.index + pd.Timedelta(days=k)).values)[0]
    print(f"  sheet mean of 9 lowland posts vs CPC (sheet D <-> CPC D-1{k:+d}): r {lagr[k]:.2f}")
kbest = max(lagr, key=lagr.get)
cs.index = cs.index - pd.Timedelta(days=kbest)  # align CPC to the sheet's own day label for the tests below
print(f"  CPC tests below use the best lag ({kbest:+d})")
ev = []
for s in V.columns:
    kk = K[s]
    others = V[[c for c in lowl if c != s]].mean(axis=1)
    i, dates = 0, V.index
    while i < len(dates):
        if kk.iloc[i] == "x":
            j = i
            while j < len(dates) and kk.iloc[j] == "x":
                j += 1
            if j < len(dates) and kk.iloc[j] == "v":
                d = dates[j]; win = dates[i:j + 1]
                ev.append(dict(stn=s, date=d.date(), run_len=j - i, value=V[s].iloc[j], nbr_day=others.loc[d],
                               nbr_run_sum=others.loc[win].sum(), nbr_run_n=int(others.loc[win].notna().sum()),
                               cpc_day=cs.get(d, np.nan), cpc_run_sum=cs.reindex(win).sum()))
            i = j
        else:
            i += 1
E = pd.DataFrame(ev)
E.to_csv(f"{q.OUT}/chind_x_jabotabek_events.csv", index=False)
post = set(zip(E.stn, pd.to_datetime(E.date)))
ref = D[(D.kind == "v") & (D.value >= 1)]
ref = ref[[(a, b) not in post for a, b in zip(ref.stn, ref.date)]]
p95 = ref.groupby("stn").value.quantile(0.95)
print(f"\nX cells {int((D.kind == 'x').sum())}; X runs followed by a reading: {len(E)} "
      f"(run length median {E.run_len.median():.0f}, max {E.run_len.max()}); zero readings after X: {(E.value == 0).sum()}")
w = E[E.value >= 1]
print(f"  wet readings (>= 1 mm) after X: {len(w)}; median {w.value.median():.1f} mm vs the same posts' other wet days "
      f"{ref[ref.stn.isin(w.stn)].value.median():.1f} mm; share above the post's p95: "
      f"{(w.value.values > w.stn.map(p95).values).mean():.2f} (0.05 expected without accumulation)")


def closer_day(val, day, run):
    return (val - day).abs() < (val - run).abs()


e2 = E[(E.nbr_run_n >= 2) & ((E.nbr_run_sum - E.nbr_day) >= 5)]
print(f"  events where neighbours' run sum exceeds their day value by >= 5 mm: {len(e2)}; reading closer to the day "
      f"value in {int(closer_day(e2.value, e2.nbr_day, e2.nbr_run_sum).sum())}; medians: reading {e2.value.median():.1f}, "
      f"nbr day {e2.nbr_day.median():.1f}, nbr run sum {e2.nbr_run_sum.median():.1f}")
e3 = E[(E.cpc_run_sum - E.cpc_day) >= 5]
print(f"  same with CPC (run sum - day >= 5 mm): {len(e3)}; reading closer to the CPC day value in "
      f"{int(closer_day(e3.value, e3.cpc_day, e3.cpc_run_sum).sum())}")
rng = np.random.default_rng(0)
ctl = []
for r in E.itertuples():
    o_ = V[[c for c in lowl if c != r.stn]].mean(axis=1)
    for _ in range(20):
        jx = int(rng.integers(r.run_len, len(V.index)))
        win = V.index[jx - r.run_len:jx + 1]
        if K[r.stn].loc[win].eq("v").all():
            ctl.append((V[r.stn].iloc[jx], o_.iloc[jx], o_.loc[win].sum()))
Ct = pd.DataFrame(ctl, columns=["value", "nbr_day", "nbr_run_sum"])
Ct2 = Ct[(Ct.nbr_run_sum - Ct.nbr_day) >= 5]
print(f"  control (ordinary days, same pseudo-run lengths): closer to the day value in "
      f"{closer_day(Ct2.value, Ct2.nbr_day, Ct2.nbr_run_sum).mean():.2f} of {len(Ct2)}")
print("\n  events:")
print(E.round(1).to_string(index=False))
Dk = pd.DataFrame(dek, columns=["stn", "month", "I", "II", "III"])
chk = []
for r in Dk.itertuples():
    for nm, (a, b) in zip(["I", "II", "III"], [(1, 10), (11, 20), (21, 31)]):
        sub = D[(D.stn == r.stn) & (D.date.dt.month == r.month) & D.date.dt.day.between(a, b)]
        tot = getattr(r, nm)
        if np.isfinite(tot):
            chk.append((r.stn, r.month, nm, tot, sub.value.sum(), int((sub.kind == "x").sum())))
Kc = pd.DataFrame(chk, columns=["stn", "month", "dekad", "total", "sum_values", "n_x"])
Kc["equal"] = np.isclose(Kc.total, Kc.sum_values, atol=1.01)
print("\n  dekad totals equal to the sum of numeric values (+-1 mm), by whether the dekad holds X:")
print(Kc.groupby(Kc.n_x > 0).equal.agg(["sum", "size"]).to_string())

# ---- 3. reach
o = q.obs_rr()
ch = o[o.series_id.astype(str).str.startswith("chind:") & (o.date_raw.dt.year == 1999)]
nread = int(C[C.chind_year_file & (C.sheet_index == 0)].x_in_read_day_cols.sum())
print(f"\nchind 1999 values in observations_RR: {len(ch)}; X cells inside read R-day columns of chind year files: {nread}")
