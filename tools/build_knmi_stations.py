"""Name table for the KNMI Dutch-era daily sheets (F28, F71, F74): station name in the sheets -> place, position, elevation.

Only the station records that hold rain values are listed (16 records at 15 places; the modern-named blocks in
`Sumatera 1880-1897.xls`, e.g. Pajar Bulan or Astra Ksetra, are empty). Two position sources, both read here:
  D = `List Stasiun Se- Indonesia (Data Belanda 1879 - 1939).xls` (Dutch spellings, degrees and minutes, typos)
  P = `Panjang data yang diguanakan.xls` (user's sheet: KNMI station name, decimal degrees, 2 decimals)
Choice per place is written in `how`; D is preferred where its entry is plausible, P where D lacks the place or has a typo.
Rejected: P Sabang (5.57, 95.44 is Banda Aceh), P "Tg. Karang / Bra" (the modern Branti airport).
Jakarta is listed but skipped by the reader (same record as SACA&D 180 Kemayoran at 0.1 mm, F71).

Output: F:/temp/station/knmi/_knmi_stations.csv (sheet_name, key, place, lat, lon, elev_m, how, d_lat, d_lon, p_lat, p_lon, km_d_p)
Usage: python tools/build_knmi_stations.py
"""
import math
import re
import sys
from pathlib import Path

import pandas as pd
import xlrd

sys.stdout.reconfigure(encoding="utf-8")
K = Path("F:/temp/station/knmi")

# sheet name -> (key, Dutch-list name or None, Panjang name or None, choice, note)
TABLE = [
    ("Jambi", "JAMBI", "Djambi", "Jambi", "D", ""),
    ("jambi", "JAMBI", "Djambi", "Jambi", "D", ""),
    ("Palembang", "PALEMBANG", "Palembang", "Palembang", "D", ""),
    ("Medan", "MEDAN", "Medan", "Medan", "D", ""),
    ("Medan I", "MEDAN", "Medan", "Medan", "D", "Medan I (1880-1897) continued as Medan (1898-1916) [to verify]"),
    ("Medan II (Deli)", "MEDAN_II", "Medan", "Medan", "D", "second Medan gauge; position of Medan assumed [to verify]"),
    ("Medan II (Deli Putri)", "MEDAN_II", "Medan", "Medan", "D", "1885 only; taken as Medan II [to verify]"),
    ("Sabang", "SABANG", "Sabang", None, "D", "P gives 5.57, 95.44 (Banda Aceh): rejected"),
    ("sabang", "SABANG", "Sabang", None, "D", ""),
    ("Lhokseumawe", "LHOKSEUMAWE", "Telok Semawe", "Lhouksemawe", "D", ""),
    ("Pangkal pinang", "PANGKAL_PINANG", None, "Pangkal Pinang", "P", "not in the Dutch list"),
    ("Tanjung karang", "TANJUNG_KARANG", "Telok Betong", None, "D", "Tanjung Karang and Telok Betong are adjacent (Bandar Lampung) [to verify]; "
                                                                      "P 'Tg. Karang / Bra' is Branti airport: rejected"),
    ("Banyuwangi", "BANYUWANGI", "Banjoewangi", "Banyuwangi", "D", ""),
    ("Cilacap", "CILACAP", "Tjilatjap", "Cilacap", "D", ""),
    ("Jatiwangi", "JATIWANGI", None, "Jatiwangi", "P", "not in the Dutch list (Tjiwangi there is another place)"),
    ("Semarang", "SEMARANG", "Semarang", "Semarang", "D", ""),
    ("Tasikmalaya", "TASIKMALAYA", "Tasikmalaja", "Tasikmalaya", "P", "D latitude written 6 19 (typo)"),
    ("Tegal", "TEGAL", "Tegal", "Tegal", "D", ""),
    ("Jakarta", "JAKARTA", "Batavia", "Jakarta (BMG)", "D", "skipped by the reader: same record as SACA&D 180 (F71)"),
    ("Jakarta (BMG)", "JAKARTA", "Batavia", "Jakarta (BMG)", "D", "skipped by the reader: same record as SACA&D 180 (F71)"),
]


def dm(s):
    """'106° 22'' or '6° 31' S' -> signed decimal degrees (S negative)."""
    t = str(s).replace("⁰", "°")
    n = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if not n:
        return float("nan")
    v = n[0] + (n[1] / 60 if len(n) > 1 else 0)
    return -v if re.search(r"\bS\b|S'?\s*$|S$", t.strip()) else v


def km(a, b, c, d):
    p = math.pi / 180
    return 6371 * 2 * math.asin(math.sqrt(math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2))


sh = xlrd.open_workbook(str(K / "List Stasiun Se- Indonesia (Data Belanda 1879 - 1939).xls")).sheet_by_index(0)
D = {}
for r in range(2, sh.nrows):
    nm = str(sh.cell_value(r, 1)).strip()
    if nm:
        el = sh.cell_value(r, 5)
        D[nm] = (dm(sh.cell_value(r, 4)), dm(sh.cell_value(r, 3)), float(el) if isinstance(el, float) else float("nan"))
sh = xlrd.open_workbook(str(K / "Panjang data yang diguanakan.xls")).sheet_by_index(0)
P = {}
for r in range(2, sh.nrows):
    nm = str(sh.cell_value(r, 2)).strip()
    la, lo = sh.cell_value(r, 4), sh.cell_value(r, 5)
    if nm and isinstance(la, float) and isinstance(lo, float):
        P.setdefault(nm, (la, lo))

rows = []
for sheet_name, key, dname, pname, choice, note in TABLE:
    d = D.get(dname) if dname else None
    p = P.get(pname) if pname else None
    if dname and d is None:
        raise SystemExit(f"Dutch list has no '{dname}'")
    if pname and p is None:
        raise SystemExit(f"Panjang sheet has no '{pname}'")
    lat, lon = (d[0], d[1]) if choice == "D" else p
    rows.append(dict(sheet_name=sheet_name, key=key, place=dname or pname, lat=round(lat, 4), lon=round(lon, 4),
                     elev_m=d[2] if d else float("nan"),
                     how=("Dutch station list" if choice == "D" else "user's Panjang data sheet") + (f"; {note}" if note else ""),
                     d_lat=round(d[0], 4) if d else None, d_lon=round(d[1], 4) if d else None,
                     p_lat=p[0] if p else None, p_lon=p[1] if p else None,
                     km_d_p=round(km(d[0], d[1], p[0], p[1]), 1) if d and p else None))
out = pd.DataFrame(rows)
out.to_csv(K / "_knmi_stations.csv", index=False)
pd.set_option("display.width", 250)
print(out[["sheet_name", "key", "place", "lat", "lon", "elev_m", "km_d_p"]].to_string(index=False))
