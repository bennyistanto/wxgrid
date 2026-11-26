"""Final per-file ledger for Data Stasiun: one row per file (356) with its outcome after the
whole extraction (F55-F56). Combines the classification (ledger_classify.py), per-sheet
parsing (agro_stage_a.py), station/year resolution (agro_resolve.py), undated matches
(agro_undated_match.py) and the files read by the agro_collection reader.

Run: python tools/ledger_final.py -> F:/temp/station/additional-sources/_ledger_data_stasiun_OUTCOME.csv
"""
from pathlib import Path

import pandas as pd

B = Path("F:/temp/station/additional-sources")
L = pd.read_csv(B / "_ledger_data_stasiun_final.csv")
S = pd.read_csv(B / "_agro_raw_sheets.csv")
Z = pd.read_csv(B / "_agro_sheet_resolution.csv")
U = pd.read_csv(B / "_agro_undated_matches.csv")

OTHER_READ = {  # files read by agro_collection outside the agro-sheet path -> station
    "KAMBARA.XLS": "Kambara", "METKLIM/BENKEL.XLS": "Bengkel", "BEKASI/H-319996.XLS": "Pondokbalas + Rawamerta",
    "BMG-JKT/BMG8194.XLS": "Bandung (WMO 96783; file named BMG-Jakarta)", "JAKENAN1.XLS": "Jakenan (radiation)",
    "FLORES/WMILOK90.XLS": "Watumilok", "FLORES/WMILOK91.XLS": "Watumilok", "FLORES/WBL90-91.XLS": "Wairbleler",
    "FLORES/MPA-9091.XLS": "Magepanda"}

rows = []
for _, r in L.iterrows():
    f, cat = r["file"], r["category"]
    out = dict(file=f, folder=r["folder"], size_kb=r["size_kb"], category=cat)
    name = f.split("/")[-1].upper()
    if cat in ("agro-daily", "agro-variant"):
        sh = S[S["file"] == f]
        z = Z[Z["file"] == f]
        used = z[z["status"] != "unresolved"]
        moved = used[(used["station"] != used["file_station"]) | (used["year"] != used["parsed_year"])]
        if z.empty:
            out.update(outcome="empty form", detail=f"{len(sh)} sheets, none with values")
        else:
            stns = sorted(set(used["station"].dropna()))
            yrs = sorted(set(used["year"].dropna().astype(int)))
            det = f"{len(used)}/{len(z)} sheets used; stations {stns}; years {yrs[0]}-{yrs[-1]}" if len(used) else ""
            if len(moved):
                det += "; moved: " + ", ".join(f"{a}->{b} {int(y)}" for a, b, y in
                                                zip(moved["sheet"], moved["station"], moved["year"]))
            excl = z[z["status"] == "unresolved"]
            if len(excl):
                det += "; excluded (unresolved): " + ", ".join(excl["sheet"])
            out.update(outcome="extracted" if len(used) else "excluded", detail=det.strip("; "),
                       values_raw=int(sh["n_values"].fillna(0).sum()))
    elif f in OTHER_READ or name.startswith("MAU") and f.startswith("FLORES/") and name[3:7].isdigit():
        st = OTHER_READ.get(f, "Maumere (WMO 97300)")
        out.update(outcome="extracted", detail=f"station {st}")
    elif f.startswith("METKLIM/") and (name.startswith("MNG") or name.startswith("MUNENG")):
        out.update(outcome="extracted", detail="station Muneng (long format)")
    elif f in set(U["file"]):
        u = U[U["file"] == f]
        dated = u[u["year"].notna()]
        out.update(outcome="duplicate of dated data",
                   detail=f"{len(dated)}/{len(u)} columns identical to dated series ({', '.join(map(str, dated['year'].astype(str).unique()))}); "
                          f"unmatched columns not used (user rule 2026-10-08)")
    elif f == "FLORES/SIKKA.XLS":
        out.update(outcome="excluded", detail="daily Oct 1990-Feb 1991, but no locatable station (not Maumere 97300: Tmax equal 6%)")
    elif r["status_final"] == "UNREADABLE":
        out.update(outcome="unreadable", detail=r["reason"])
    elif r["status_final"] == "NOT-DAILY":
        out.update(outcome="not daily", detail=f"{r['category']}: {r['reason']}")
    elif r["status_final"] == "METADATA":
        out.update(outcome="metadata", detail=r["reason"])
    elif r["status_final"] == "CONTAINER":
        out.update(outcome="container", detail=r["reason"])
    else:
        out.update(outcome="UNACCOUNTED", detail=str(r.get("reason", "")))
    rows.append(out)

O = pd.DataFrame(rows)
O.to_csv(B / "_ledger_data_stasiun_OUTCOME.csv", index=False)
print("files:", len(O))
print(O["outcome"].value_counts().to_string())
print("\nunaccounted:", O[O["outcome"] == "UNACCOUNTED"]["file"].tolist())
