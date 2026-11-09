"""Download the registry files this project is built on.

Run it from the repository root. The files land under data/raw and are not
committed, so every figure published anywhere in this repository names the
script that regenerates it and this is the first one in that chain.

    python3 scripts/fetch.py
    python3 scripts/fetch.py --only leie
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screening.registries import SOURCES, source  # noqa: E402

RAW = os.path.join("data", "raw")


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_one(src, force=False):
    target = os.path.join(RAW, src.local_name)
    if os.path.exists(target) and not force:
        return target, os.path.getsize(target), "already on disk"
    os.makedirs(RAW, exist_ok=True)
    with urllib.request.urlopen(src.url, timeout=150) as resp, open(target, "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    return target, os.path.getsize(target), "downloaded"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", action="append", default=None, help="a source key")
    ap.add_argument("--force", action="store_true", help="download even if the file is there")
    ap.add_argument("--manifest", default=os.path.join(RAW, "manifest.json"))
    args = ap.parse_args(argv)

    wanted = [source(k) for k in args.only] if args.only else list(SOURCES)
    manifest = {}
    for src in wanted:
        path, size, how = fetch_one(src, force=args.force)
        manifest[src.key] = {
            "url": src.url,
            "bytes": size,
            "sha256": digest(path),
            "encoding": src.encoding,
        }
        print("%-18s %12d bytes  %s" % (src.key, size, how))

    with open(args.manifest, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    print("manifest written to %s, %d sources" % (args.manifest, len(manifest)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
