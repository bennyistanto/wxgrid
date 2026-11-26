import pandas as pd

from wxgrid.readers import knmi_sheets as ks


class Sheet:
    def __init__(self, name, rows):
        self.name, self.rows = name, rows
        self.nrows = len(rows)
        self.ncols = max(len(r) for r in rows)

    def cell_value(self, r, c):
        return self.rows[r][c] if c < len(self.rows[r]) else ""


class Book:
    def __init__(self, sheets):
        self._s = sheets

    def sheets(self):
        return self._s


def _smr(name, year, month, days):
    """One station-month row: No, Stasiun, Lon, Lat, Elev, Tahun, Bulan, day 1..31."""
    return ["", name, "", "", "", year, month] + days + [""] * (31 - len(days))


HDR = ["No", "Stasiun", "Longitude", "Latitude", "Elevasi", "Tahun", "Bulan"] + [float(d) for d in range(1, 32)]


def test_cell_coding():
    assert ks.cell(12.0) == (12.0, "num")
    assert ks.cell("-") == (0.0, "dash") and ks.cell("--") == (0.0, "dash")
    assert ks.cell("n.w.") == (None, "missing") and ks.cell("Geen waarnemingen ontvangen") == (None, "missing")
    assert ks.cell("") == (None, "blank") and ks.cell("`12") == (12.0, "num")


def test_read_blank_rules_skip_and_table(tmp_path, monkeypatch):
    sumatra = Book([Sheet("Harian", [HDR,
                                     _smr("Medan I", 1898.0, "Januari", [5.0, "", 3.0]),
                                     _smr("", "", "Februari", [""] * 28),            # whole month blank: missing
                                     _smr("Jakarta (BMG)", 1898.0, "Januari", [9.0])])])
    jawa = Book([Sheet("Tegal", [HDR, _smr("Tegal", 1879.0, "Januari", [4.0, "-", "", "n.w."])])])
    blocks = Book([Sheet("1880", [[1880.0], [""], ["No", "Stasiun"],
                                  ["1.0", "Palembang", "", "", "", "", "Januari", "Februari"],
                                  ["", "", "", "", "", 1.0, 7.0, "", "", "", "", "", "", 1.0, 2.0],
                                  ["", "", "", "", "", 2.0, "", "", "", "", "", "", "", 2.0, ""]])])
    books = {"sum.xls": sumatra, "jawa.xls": jawa, "blk.xls": blocks}
    monkeypatch.setattr(ks.xlrd, "open_workbook", lambda path, **k: books[path.replace("\\", "/").split("/")[-1]])
    tab = tmp_path / "st.csv"
    pd.DataFrame([dict(sheet_name="Medan I", key="MEDAN", place="Medan", lat=3.58, lon=98.68, elev_m=14, how="D"),
                  dict(sheet_name="Tegal", key="TEGAL", place="Tegal", lat=-6.85, lon=109.13, elev_m=None, how="D"),
                  dict(sheet_name="Palembang", key="PALEMBANG", place="Palembang", lat=-2.98, lon=104.77, elev_m=None, how="D")]
                 ).to_csv(tab, index=False)
    src = dict(name="knmi", path=str(tmp_path), stations_csv=str(tab), skip=["Jakarta (BMG)"], coord_approx=["TEGAL"],
               books=[dict(path="sum.xls", layout="station_month_rows", blank="dry_if_month_reported"),
                      dict(path="jawa.xls", layout="station_month_rows", blank="missing"),
                      dict(path="blk.xls", layout="year_blocks", blank="dry_if_month_reported")])
    st, se, ob = ks.read(src, [90, -15, 145, 12])
    assert sorted(st.station_key) == ["knmi:MEDAN", "knmi:PALEMBANG", "knmi:TEGAL"]   # Jakarta skipped
    v = {(s, d.strftime("%Y-%m-%d")): x for s, d, x in zip(ob.series_id, ob.date, ob.value)}
    # reported month: blank = dry; unreported month: nothing
    assert v[("knmi:MEDAN:RR", "1898-01-01")] == 5.0 and v[("knmi:MEDAN:RR", "1898-01-02")] == 0.0
    assert v[("knmi:MEDAN:RR", "1898-01-31")] == 0.0
    assert not any(k[0] == "knmi:MEDAN:RR" and k[1].startswith("1898-02") for k in v)
    # CH Jawa: '-' = dry, blank and n.w. = missing
    assert v[("knmi:TEGAL:RR", "1879-01-02")] == 0.0
    assert ("knmi:TEGAL:RR", "1879-01-03") not in v and ("knmi:TEGAL:RR", "1879-01-04") not in v
    # year blocks: Jan-Jul in columns 7-13, Aug-Dec in 15-19
    assert v[("knmi:PALEMBANG:RR", "1880-01-01")] == 7.0 and v[("knmi:PALEMBANG:RR", "1880-08-01")] == 2.0
    assert v[("knmi:PALEMBANG:RR", "1880-01-02")] == 0.0
    # coord_approx keys flag every value of that station only
    assert set(ob[ob.series_id == "knmi:TEGAL:RR"].flag) == {"coord_approx"}
    assert set(ob[ob.series_id != "knmi:TEGAL:RR"].flag) == {""}
