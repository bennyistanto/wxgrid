# Match SACA&D Indonesian stations (from zip metadata) to the 180 BMKG stations.
import zipfile, numpy as np, pandas as pd
def meta(f, m, key):
    t = zipfile.ZipFile(f).read(m).decode("utf-8","ignore").splitlines()
    i = [k for k,l in enumerate(t) if l.strip().startswith(key)][0]
    hdr = [c.strip() for c in t[i].split(",")]
    rows = []
    for l in t[i+1:]:
        c = [x.strip() for x in l.split(",")]
        if len(c) < len(hdr): continue
        # names may contain commas: take fixed fields from the right of the name
        rows.append(dict(zip(hdr, c[:1] + [",".join(c[1:len(c)-len(hdr)+2])] + c[len(c)-len(hdr)+2:])))
    return pd.DataFrame(rows)
dms = lambda s: (-1 if s.strip().startswith("-") else 1)*sum(float(x)/60**k for k,x in enumerate(s.strip().lstrip("+-").split(":")))
bmkg = pd.read_csv("bmkg_station_profile.csv")
def nn_to_bmkg(lat, lon):
    la1,lo1 = np.radians(lat)[:,None], np.radians(lon)[:,None]
    la2,lo2 = np.radians(bmkg.lat.values)[None], np.radians(bmkg.lon.values)[None]
    return (2*6371*np.arcsin(np.sqrt(np.sin((la2-la1)/2)**2+np.cos(la1)*np.cos(la2)*np.sin((lo2-lo1)/2)**2))).min(1)
for name,f,m,key,prof in [("blend","sacad/SACA_blend_rr.zip","stations.txt","STAID","saca_blend_idn_profile.csv"),
                          ("nonblend","sacad/SACA_nonblend_rr.zip","sources.txt","SOUID","saca_nonblend_idn_profile.csv")]:
    d = meta(f, m, key); d = d[d.CN == "ID"].copy()
    d["lat"] = d.LAT.map(dms); d["lon"] = d.LON.map(dms); d["id"] = d[key].astype(int)
    p = pd.read_csv(prof, parse_dates=["first","last"]).merge(d[["id","lat","lon"]], on="id")
    p["nn_km"] = nn_to_bmkg(p.lat.values, p.lon.values)
    far = p[p.nn_km >= 5]
    print(f"== {name}: {len(p)} ID series with data | within 5 km of a BMKG-180 station: {(p.nn_km<5).sum()} | farther: {len(far)}")
    print(f"   farther series: valid days {far.n_valid.sum():,}; last-year range {far['last'].dt.year.min()}-{far['last'].dt.year.max()}; ",
          "median NN to BMKG-180 km:", round(far.nn_km.median(),1))
    # unique far locations (sources can share a site)
    print("   distinct far sites (rounded 0.01 deg):", far[["lat","lon"]].round(2).drop_duplicates().shape[0])
    p.to_csv(f"saca_{name}_idn_matched.csv", index=False)
