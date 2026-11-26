"""Collect the phase-2 /qc findings into a PROPOSED exclusion table (same columns as
compiled/qc/exclusions_rr.csv: series_id, start, end, rule, note). Proposal only: it is written
to F:/temp/station/qc_phase2/proposed_exclusions_rr.csv and is not referenced by any config.
Dates are form dates (date_raw) for month-based rules, which equal the merged dates only where
the day-label offset is 0 [to verify per entry before adoption].
Inputs: dash_months.csv (tools/qc_dash_months.py), jatim_zero_years.csv
(tools/qc_jatim_zero_years.py), audit_zero_runs.csv (tools/qc_phase2_audit.py).
Run: python tools/qc_phase2_proposals.py
"""
import pandas as pd

OUT = "F:/temp/station/qc_phase2"
rows = []
d = pd.read_csv(f"{OUT}/dash_months.csv")
for r in d[d.verdict == "unreported"].itertuples():
    p = pd.Period(r.month, "M")
    rows.append((r.series_id, str(p.start_time.date()), str(p.end_time.date()), "dash_month_unreported",
                 f"all '-' month; CPC {r.cpc_mm:.0f} mm, {r.n_nbr} nbrs median {r.nbr_median_mm:.0f} mm"))
z = pd.read_csv(f"{OUT}/jatim_zero_years.csv")
for r in z.itertuples():
    rows.append((r.series_id, f"{r.year}-01-01", f"{r.year}-12-31", "zero_year",
                 f"whole year 0.0 mm; post median year {r.post_median_year_mm:.0f} mm; CPC {r.cpc_year_mm:.0f} mm"))
zr = pd.read_csv(f"{OUT}/audit_zero_runs.csv")
zr = zr[zr.suspect & (zr.length >= 30) & (zr.dash_month_days == 0)]
for r in zr.itertuples():
    rows.append((r.series_id, r.start, r.end, "zero_run_30d",
                 f"{r.length} d of 0 mm, CPC mean {r.cpc_mean:.1f} mm/d, nbr median {r.nbr_median_mean:.1f} mm/d"))
COPIES = [  # tools/qc_copy_checks.py, tools/qc_phase2_audit.py section 4
    ("sumbar_daily:|Sumpur_Kudus:RR", "1992-01-01", "1998-12-31", "copy_of_other_post", "equal to sumbar Kumanis on 66-96% of wet days per year (22 km)"),
    ("sumbar_daily:50D|Rambatan:RR", "1991-01-01", "1994-12-31", "copy_of_other_post", "equal to agro:RAMBATAN at lag -1 on 74-90% of wet days (13.6 km)"),
    ("sumbar_daily:36B|KPTP_Sitiung_P_Punjung_Sijunjung:RR", "1992-01-01", "1993-12-31", "copy_of_other_post", "equal to agro:GUNUNGMEDAN at lag -1 on 67-89% of wet days (15 km)"),
    ("bmg_posts:Patas:RR", "1974-01-01", "1974-05-31", "month_copy", "Jan, Mar, Apr, May 1974 equal 1972 (and Dec 1974)"),
    ("bmg_posts:Patas:RR", "1974-12-01", "1974-12-31", "month_copy", "Dec 1974 equal Dec 1972"),
    ("sumbar_daily:56A|Koto_Tinggi:RR", "1998-02-01", "1998-09-30", "month_copy", "Feb-May, Jul, Sep 1998 equal 1997 (6 months)"),
    ("sumbar_daily:|Sukarami:RR", "1998-01-01", "1998-05-31", "month_copy", "Jan, Mar, May 1998 equal 1995-07, 1995-05, 1996-10"),
    ("sumbar_daily:|Tiku:RR", "1998-07-01", "1998-07-31", "month_copy", "equal 1997-07"),
    ("sumbar_daily:|SMPK_Laing:RR", "1999-01-01", "1999-01-31", "month_copy", "equal 1998-01"),
    ("sumbar_daily:56B|Suliki:RR", "1996-10-01", "1996-10-31", "month_copy", "equal 1996-08"),
    ("sumsel_posts:Banyuasin|Alicia_191_d:RR", "2004-04-01", "2004-04-30", "month_copy", "equal 2003-04"),
    ("sumsel_posts:Banyuasin|Melania_191_h:RR", "2004-04-01", "2004-04-30", "month_copy", "equal 2003-04"),
    ("sumsel_posts:Banyuasin|Sanna_191_e:RR", "2004-04-01", "2004-04-30", "month_copy", "equal 2003-04"),
    ("sumbar_daily:|Lubuk_Gadang:RR", "1995-05-30", "1995-05-30", "code_like_value", "777 mm, CPC 0 mm, no neighbour within 25 km"),
    ("sumbar_daily:|PU_Padang_Panjang:RR", "1994-10-27", "1994-10-27", "isolated_extreme", "501 mm (form date), CPC 0 mm, 5 nbrs max 10 mm"),
]
rows += COPIES
P = pd.DataFrame(rows, columns=["series_id", "start", "end", "rule", "note"])
P.to_csv(f"{OUT}/proposed_exclusions_rr.csv", index=False)
print(P.groupby("rule").agg(entries=("series_id", "size"), series=("series_id", "nunique")).to_string())
print("total entries", len(P))
