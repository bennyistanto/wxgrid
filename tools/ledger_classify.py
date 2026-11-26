"""Classify every file in Data Stasiun from the measured ledger (tools/ledger_data_stasiun.py).
Station identity comes from the folder (station folders) or the file-name prefix (METKLIM),
not from the per-sheet name cell, which is often a copied template.

Run after ledger_data_stasiun.py:  python tools/ledger_classify.py
Writes F:/temp/station/additional-sources/_ledger_data_stasiun_final.csv and prints a summary.
"""
import re
from pathlib import Path

import pandas as pd

OUT = Path("F:/temp/station/additional-sources")
L = pd.read_csv(OUT / "_ledger_data_stasiun.csv")
IDENT = pd.read_csv(OUT / "_ledger_sheet_identity.csv")

# The collection's own inventory (ALIST/LIST.XLS) lists these 27 stations; folder codes map to them.
FOLDER = {"BDRBUAT": "Bandarbuat", "BONTBILI": "Bontobili", "CIKEMEUH": "Cikeumeuh", "CIMANGGU": "Cimanggu",
          "CIPANAS": "Cipanas", "GENTENG": "Genteng", "GNGMEDAN": "Gunungmedan", "HDLMNRAF": "Handilmanarap",
          "JAKENAN": "Jakenan", "JMBGEDE": "Jambegede", "KDLPAYAK": "Kendalpayak", "KUNINGAN": "Kuningan",
          "KYUAGUNG": "Kayuagung", "LANRANG": "Lanrang", "LMPINENG": "Lampineung", "MAROS": "Maros",
          "MOJOSARI": "Mojosari", "MRGAHAYU": "Margahayu", "MUARA": "Muara", "MUNENG": "Muneng", "NGALE": "Ngale",
          "PACET": "Pacet", "PUSAKA": "Pusakanegara", "RAMBATAN": "Rambatan", "SUKARAMI": "Sukarami",
          "SUMANI": "Sumani", "TMNBOGO": "Tamanbogo"}
# METKLIM file-name prefix -> station (prefix verified against the name/code cells; see F55)
PREFIX = [("MUARA", "Muara"), ("MUNENG", "Muneng"), ("MNG", "Muneng"), ("50D", "Rambatan"), ("179", "Jakenan"),
          ("68", "Kuningan"), ("052X", "Kendalpayak"), ("415", "Maros"), ("GM", "Gunungmedan"),
          ("BB", "Bandarbuat"), ("CPS68", "Cipanas"), ("MRG", "Margahayu"), ("175A", "Mojosari"),
          ("BON", "Bontobili"), ("CMG", "Cimanggu"), ("LNRNG", "Lanrang"), ("PCT", "Pacet"), ("GTG", "Genteng"),
          ("PUSAKA", "Pusakanegara"), ("BENKEL", "Bengkel (not in inventory)"), ("JAKENAN", "Jakenan"),
          ("KDL", "Kendalpayak"), ("C-", "Cikeumeuh"), ("S-", "Sukarami")]
ROOTMAP = {"GM.XLS": "Gunungmedan", "GMD80-94.XLS": "Gunungmedan", "JAKENAN.XLS": "Jakenan",
           "JAKENAN1.XLS": "Jakenan", "KAMBARA.XLS": "Kambara (not in inventory)", "KDL-P1.XLS": "Kendalpayak",
           "LRNG81.CSV": "Lanrang (inferred from name)", "GRAF-CHA.XLS": "", "METKLIM.ZIP": ""}
ALISTMAP = {"MJS81D83.XLS": "Mojosari", "MRA80&81.XLS": "Muara", "PSK79D80.XLS": "Pusakanegara", "LIST.XLS": ""}

FLORES_DAILY = {"MAU7879", "MAU7980", "MAU8081", "MAU8182", "MAU8283", "MAU8384", "MAU8485", "MAU8586",
                "MAU8687", "MAU8788", "MAU8889", "SIKKA", "MPA-9091", "WBL90-91", "WMILOK90", "WMILOK91"}
FLORES_DEKADE = {"MPANDA", "PAGA", "PTAHUDEK", "WAIGETE", "WAIOTI"}
FLORES_META = {"REKAP": "station recap with coordinates (metadata)", "RATACH": "long-term averages (derived)"}


def station_of(row):
    f, folder = row["file"], row["folder"]
    name = f.split("/")[-1].upper()
    if folder in FOLDER:
        return FOLDER[folder]
    if folder == "METKLIM":
        for p, s in PREFIX:
            if name.startswith(p):
                return s
        return ""
    if folder == "(root)":
        return ROOTMAP.get(name, "")
    if folder == "ALIST":
        return ALISTMAP.get(name, "")
    if folder == "BEKASI":
        return "Pondokbales rain post (not in inventory)"
    if folder == "BMG-JKT":
        return "BMG Jakarta (not in inventory)"
    if folder == "FLORES":
        return "Flores station"
    return ""


def classify(row):
    f, folder, name = row["file"], row["folder"], row["file"].split("/")[-1].upper()
    stem = name.rsplit(".", 1)[0]
    if row["status"] == "protected":
        return "UNREADABLE", "protected", "password-protected; not opened"
    if row["status"] == "error":
        return "UNREADABLE", "corrupt", "xlrd: not a valid BIFF file"
    if name == "METKLIM.ZIP":
        return "CONTAINER", "archive", "byte-identical to METKLIM/ folder (236/236 CRC match)"
    if name == "LIST.XLS":
        return "METADATA", "inventory", "station x year status grid (cell colours), 27 stations 1973-94"
    if folder == "FLORES":
        if stem in FLORES_DAILY:
            return "DAILY-NOT-EXTRACTED", "daily", "needs a reader (Flores layouts)"
        if stem in FLORES_DEKADE:
            return "NOT-DAILY", "dekadal", "10-day totals"
        if stem in FLORES_META:
            return "METADATA", "summary", FLORES_META[stem]
        return "NOT-DAILY", "monthly", "year x month table"
    if name in ("KDL-P1.XLS",):
        return "NOT-DAILY", "monthly", "monthly climate summary"
    if name == "GRAF-CHA.XLS":
        return "NOT-DAILY", "derived", "chart data: averages / SD"
    if name in ("JAKENAN.XLS", "JAKENAN1.XLS", "052X-ACC.XLS"):
        hdr = "has year header" if name == "JAKENAN1.XLS" else "NO year header"
        return "DAILY-NOT-EXTRACTED", "radiation-matrix", f"day x year radiation values, {hdr}"
    if name == "LRNG81.CSV":
        return "DAILY-NOT-EXTRACTED", "unlabelled", "5 unlabelled columns, no dates; usable only by matching a dated sheet"
    if row["layout"] == "agro-daily":
        return "EXTRACTED", "agro-daily", ""
    if name in ("KAMBARA.XLS", "BENKEL.XLS") or (folder == "METKLIM" and (stem.startswith("MNG") or stem.startswith("MUNENG"))):
        return "DAILY-NOT-EXTRACTED", "daily-long", "station-day rows with year blocks; needs a reader"
    if folder == "BEKASI":
        return "DAILY-NOT-EXTRACTED", "daily-grid", "day x year rainfall grid; needs a reader + coordinates"
    if folder == "BMG-JKT":
        return "DAILY-NOT-EXTRACTED", "daily-form", "monthly form sheets of daily values; needs a reader"
    if folder in ("METKLIM",) or folder in FOLDER or folder == "ALIST" or folder == "(root)":
        return "DAILY-NOT-EXTRACTED", "agro-variant", "agro layout the reader rejects (no degree marker / header on another row / blank coords)"
    return "UNCLASSIFIED", "", ""


L["station"] = L.apply(station_of, axis=1)
L[["status_final", "category", "reason"]] = L.apply(lambda r: pd.Series(classify(r)), axis=1)

# identity problems found in extracted files (sheet name cell disagrees with the file's station)
IDENT["key"] = IDENT["key"].fillna("")
L["sheets_name_mismatch"] = 0
L["sheets_name_blank"] = 0
for f, g in IDENT.groupby("file"):
    st = L.loc[L["file"] == f, "station"]
    if st.empty:
        continue
    want = re.sub(r"[^A-Z0-9]", "", st.iat[0].upper().split(" (")[0])
    keys = g["key"]
    L.loc[L["file"] == f, "sheets_name_blank"] = int((keys == "").sum())
    L.loc[L["file"] == f, "sheets_name_mismatch"] = int(((keys != "") & ~keys.str.startswith(want[:6])).sum())

cols = ["file", "folder", "size_kb", "station", "status_final", "category", "reason", "n_sheets",
        "first", "last", "values_total", "RR", "TX", "TN", "TG", "HU", "HU07", "HU13", "RA", "EV", "SS", "FG",
        "sheets_name_mismatch", "sheets_name_blank", "overlaps_most_with", "overlap_share"]
L[cols].to_csv(OUT / "_ledger_data_stasiun_final.csv", index=False)

print("files:", len(L))
print(L.groupby(["status_final", "category"]).size().to_string())
print("\nunclassified:", int((L["status_final"] == "UNCLASSIFIED").sum()))
print("extracted files with sheets whose name cell disagrees:",
      int((L["sheets_name_mismatch"] > 0).sum()), "| with blank-name sheets:", int((L["sheets_name_blank"] > 0).sum()))
print("\nby station (files / status):")
print(L[L["station"] != ""].groupby(["station", "status_final"]).size().unstack(fill_value=0).to_string())
