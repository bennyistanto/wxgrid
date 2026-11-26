"""Resolve DOIs against Crossref and pull abstracts from OpenAlex.

Used by the reference-verifier agent and the /verify-refs and /add-ref commands.
Existence is checked against Crossref (authoritative DOI registry). The abstract
comes from OpenAlex, so a claim can be checked against what the paper says, not
just against the fact that it exists.

Usage:
    python tools/refcheck.py 10.1029/2008JD010100 10.1002/joc.950
    python tools/refcheck.py --abstract 10.1029/2008JD010100
    python tools/refcheck.py --registry docs/references.md
    python tools/refcheck.py --search "Aldrian Susanto 2003 rainfall regions Indonesia"
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "wxgrid-refcheck/0.1"}
SAFE = "/()<>;:."


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=30))


def crossref(doi):
    m = _get("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe=SAFE))["message"]
    authors = m.get("author") or [{}]
    date = m.get("published-print") or m.get("published-online") or m.get("issued")
    return {
        "first_author": authors[0].get("family", "?"),
        "year": date["date-parts"][0][0],
        "journal": (m.get("container-title") or ["?"])[0],
        "title": (m.get("title") or ["?"])[0],
    }


def openalex_abstract(doi):
    m = _get("https://api.openalex.org/works/doi:" + urllib.parse.quote(doi, safe=SAFE))
    inv = m.get("abstract_inverted_index") or {}
    words = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in words) or None


def search(query, rows=5):
    url = "https://api.crossref.org/works?rows=%d&query.bibliographic=%s" % (rows, urllib.parse.quote(query))
    for m in _get(url)["message"]["items"]:
        a = m.get("author") or [{}]
        yr = m.get("issued", {}).get("date-parts", [[None]])[0][0]
        print(f"  {m.get('DOI')} | {a[0].get('family', '?')} {yr} | "
              f"{(m.get('container-title') or ['?'])[0]} | {(m.get('title') or ['?'])[0][:100]}")


def dois_in(path):
    text = open(path, encoding="utf-8").read()
    return sorted(set(d.rstrip(".,;)") for d in re.findall(r"10\.\d{4,9}/[^\s|`]+", text)))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("dois", nargs="*")
    ap.add_argument("--abstract", action="store_true", help="also print the OpenAlex abstract")
    ap.add_argument("--registry", help="check every DOI found in this markdown file")
    ap.add_argument("--search", help="Crossref bibliographic search, to find a DOI")
    args = ap.parse_args()

    if args.search:
        search(args.search)
        return
    dois = list(args.dois) + (dois_in(args.registry) if args.registry else [])
    for d in dois:
        try:
            r = crossref(d)
            print(f"OK  | {d} | {r['first_author']} {r['year']} | {r['journal']} | {r['title'][:110]}")
        except Exception as e:  # report and continue, one bad DOI must not stop the run
            print(f"ERR | {d} | {e}")
            continue
        if args.abstract:
            try:
                print("    " + (openalex_abstract(d) or "[no abstract in OpenAlex]") + "\n")
            except Exception as e:
                print(f"    [abstract fetch failed: {e}]\n")


if __name__ == "__main__":
    main()
