"""Download PU (Ditjen SDA) rain-post publications from SIHKA, the backend of pdsda.sda.pu.go.id.

Endpoints (found 2026-11-25 from the public dashboard page, e.g.
https://pdsda.sda.pu.go.id/dashboard/detail/6aa7bd5f9f4193be4e722e8b):
  catalogue   https://sihka.dev-tunnels.id/service/v1/publication?src=pos_data
              list of posts: id, integration_id, name, hidrologi_type, unit, data[{pubId, type, variable, year, status}]
  one year    https://sihka.dev-tunnels.id/service/v1/publication?id=<pubId>
              JSON {head: post metadata incl. DMS coordinates and elevation, body: {unix_ts: {note, value}}}
robots.txt on sihka.dev-tunnels.id allows all agents (checked 2026-11-25).

Only `variable == "Rainfall"` publications are fetched. Raw responses are saved unchanged, one file per
publication, so the reader never touches the network. Re-running skips files already on disk (resume).
Politeness: one request at a time, DELAY seconds apart, generic client name, retries with back-off.

Output: F:/temp/station/pu_sihka/raw/catalogue_<date>.json, raw/pub/<pubId>.json, fetch_log.csv
        (pubId, post id, name, year, type, status, http, bytes, fetched_utc).
Usage: python tools/fetch_pu_sihka.py [--limit N]
"""
import argparse
import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

BASE = "https://sihka.dev-tunnels.id/service/v1/publication"
OUT = Path("F:/temp/station/pu_sihka")
DELAY = 1.5
HEADERS = {"User-Agent": "wxgrid-research-script/0.1", "Accept": "application/json"}


def get(sess, params, tries=4):
    for k in range(tries):
        try:
            r = sess.get(BASE, params=params, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                return r
            if r.status_code in (400, 404):
                return r
        except requests.RequestException as e:
            r = e
        time.sleep(DELAY * 4 * (k + 1))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    raw = OUT / "raw"
    (raw / "pub").mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    today = dt.date.today().isoformat()
    cat_path = raw / f"catalogue_{today}.json"
    if not cat_path.exists():
        r = get(sess, {"src": "pos_data"})
        r.raise_for_status()
        cat_path.write_bytes(r.content)
        time.sleep(DELAY)
    cat = json.loads(cat_path.read_text(encoding="utf-8"))
    jobs = [(d["pubId"], p["id"], p["name"], d["year"], d["type"], d.get("status", ""))
            for p in cat for d in p.get("data", []) if d.get("variable") == "Rainfall"]
    print(f"catalogue {len(cat)} posts, {len(jobs)} rainfall publications", flush=True)
    if a.limit:
        jobs = jobs[:a.limit]
    log_path = OUT / "fetch_log.csv"
    new_log = not log_path.exists()
    n_ok = n_skip = n_bad = 0
    with log_path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new_log:
            w.writerow(["pubId", "post_id", "name", "year", "type", "status", "http", "bytes", "fetched_utc"])
        for i, (pub, post, name, year, typ, status) in enumerate(jobs, 1):
            f = raw / "pub" / f"{pub}.json"
            if f.exists():
                n_skip += 1
                continue
            r = get(sess, {"id": pub})
            code = getattr(r, "status_code", "error")
            body = getattr(r, "content", b"")
            if code == 200 and body[:1] == b"{":
                f.write_bytes(body)
                n_ok += 1
            else:
                n_bad += 1
            w.writerow([pub, post, name, year, typ, status, code, len(body),
                        dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")])
            fh.flush()
            if i % 100 == 0:
                print(f"{i}/{len(jobs)} ok {n_ok} skip {n_skip} bad {n_bad}", flush=True)
            time.sleep(DELAY)
    print(f"done: ok {n_ok}, already on disk {n_skip}, failed {n_bad}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
