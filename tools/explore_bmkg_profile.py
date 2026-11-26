"""Exploratory read-only profile of the BMKG station workbooks (rainfall, RR column).

Superseded later by the generic profiler module. Produces the numbers in
docs/findings.md F1-F6. Run: python tools/explore_bmkg_profile.py
Writes bmkg_station_profile.csv to the current directory.
"""
import glob, numpy as np, pandas as pd
rows, series = [], {}
for f in sorted(glob.glob("I:/My Drive/ForShared/BMKG/*.xlsx")):
    raw = pd.read_excel(f, header=None)
    meta = {str(raw.iloc[i,1]).strip(): str(raw.iloc[i,2]).replace(":","").strip() for i in range(5)}
    hdr = raw.index[raw.iloc[:,0].astype(str).str.strip()=="Tanggal"][0]
    df = raw.iloc[hdr+1:, :].copy(); df.columns = [str(c).strip() for c in raw.iloc[hdr]]
    d = pd.to_datetime(df["Tanggal"], format="%d-%m-%Y", errors="coerce")
    rr = pd.to_numeric(df["RR"], errors="coerce")
    s = pd.Series(rr.values, index=d).dropna()
    sid = meta.get("ID WMO")
    n8888 = int((s==8888).sum()); n9999 = int((s==9999).sum())
    s = s[(s!=8888)&(s!=9999)&(s>=0)]
    series[sid] = s
    rows.append(dict(id=sid, name=meta.get("Nama Stasiun"), lat=float(meta["Lintang"]), lon=float(meta["Bujur"]),
                     elev=meta.get("Elevasi"), n_valid=len(s), first=s.index.min(), last=s.index.max(),
                     n8888=n8888, n9999=n9999, max=s.max()))
st = pd.DataFrame(rows); st.to_csv("bmkg_station_profile.csv", index=False)
print("stations:", len(st), "| unique ids:", st.id.nunique())
print("sentinel 8888 total:", st.n8888.sum(), "in", (st.n8888>0).sum(), "stations | 9999 total:", st.n9999.sum())
print("first year range:", st["first"].min().year, "-", st["first"].max().year, "| last year range:", st["last"].min().year, "-", st["last"].max().year)
print("valid days per station: quantiles", st.n_valid.quantile([0,.1,.25,.5,.75,.9,1]).astype(int).tolist())
# daily station count
allv = pd.concat(series, axis=1)
cnt = allv.notna().sum(axis=1)
yr = cnt.groupby(cnt.index.year).median()
print("median stations reporting per day, by year:"); print(yr.to_string())
# nearest neighbour distance (haversine)
la, lo = np.radians(st.lat.values), np.radians(st.lon.values)
dla = la[:,None]-la[None,:]; dlo = lo[:,None]-lo[None,:]
a = np.sin(dla/2)**2 + np.cos(la[:,None])*np.cos(la[None,:])*np.sin(dlo/2)**2
D = 2*6371*np.arcsin(np.sqrt(a)); np.fill_diagonal(D, np.inf)
nn = D.min(axis=1); st["nn_km"] = nn
print("nearest-neighbour km quantiles:", np.round(np.quantile(nn,[0,.1,.25,.5,.75,.9,1]),1).tolist())
java = (st.lon.between(105,115.5)) & (st.lat.between(-9,-5.5))
print("Java bbox stations:", int(java.sum()), "| NN median Java:", round(float(np.median(nn[java])),1), "| outside:", round(float(np.median(nn[~java])),1))
print("max daily RR (top 5):", st.nlargest(5,"max")[["name","max"]].to_string(index=False))
st.to_csv("bmkg_station_profile.csv", index=False)
