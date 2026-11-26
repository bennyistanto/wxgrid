# Profile Indonesian RR series in SACA&D blended and non-blended zips (exploratory).
import zipfile, io, re, pandas as pd, numpy as np
def series(z, member):
    t = z.read(member).decode("utf-8", "ignore").splitlines()
    i = [k for k, l in enumerate(t) if l.strip().startswith("STAID")][-1]
    df = pd.read_csv(io.StringIO("\n".join(t[i:])), skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df["DATE"] = pd.to_datetime(df["DATE"].astype(str), format="%Y%m%d")
    return df
def id_members(z, meta, key):
    t = z.read(meta).decode("utf-8", "ignore").splitlines()
    i = [k for k, l in enumerate(t) if l.strip().startswith(key)][0]
    rows = [[c.strip() for c in l.split(",")] for l in t[i+1:] if l.count(",") > 3]
    return rows
out = {}
for name, f, meta, key, pat in [("nonblend","sacad/SACA_nonblend_rr.zip","sources.txt","SOUID","RR_SOUID%06d.txt"),
                                ("blend","sacad/SACA_blend_rr.zip","stations.txt","STAID","RR_STAID%06d.txt")]:
    z = zipfile.ZipFile(f)
    rows = id_members(z, meta, key)
    ids = sorted({int(r[0]) for r in rows if len(r) > 2 and r[2] == "ID"})
    members = set(z.namelist())
    recs = []
    for s in ids:
        m = pat % s
        if m not in members: continue
        df = series(z, m)
        v = df[(df.Q_RR == 0) & (df.RR >= 0)]
        susp = int((df.Q_RR == 1).sum())
        recs.append(dict(id=s, n_valid=len(v), n_suspect=susp,
                         first=v.DATE.min(), last=v.DATE.max(),
                         n_after_2021=int((v.DATE >= "2022-01-01").sum())))
    r = pd.DataFrame(recs); out[name] = r
    print(f"== {name}: Indonesian series {len(r)} | valid days total {r.n_valid.sum():,} | suspect {r.n_suspect.sum():,}")
    print("   last valid date: max", r["last"].max().date(), "| series with valid data after 2021-12-31:", int((r.n_after_2021>0).sum()))
    print("   last-year distribution:", r["last"].dt.year.value_counts().sort_index().tail(8).to_dict())
    print("   first-year <=1980:", int((r["first"].dt.year<=1980).sum()))
    r.to_csv(f"saca_{name}_idn_profile.csv", index=False)
