#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Generate the Downloader database (db.json, db.json.zip) from index.json.

usage: make-db.py INDEX OUT_DIR [PREVIOUS_DB_JSON]

Every build of the index (the newest kernels) is listed as
`linux_modules/<kernel release>/<id>/<file>`: its modules and its
manifest.json (load order, sizes, SHA-256, the kernel it was built for),
each with the MD5 (Downloader's hash), size and release asset URL the
build recorded. The folder of a kernel is named after `uname -r` and the
id of its /proc/version (the first 16 hex digits of its SHA-256), so the
loader finds the modules of the running kernel by path alone, and two
builds of one release number never share a folder.

Every file carries the tags of config.json (`essential` among them, so a
user's positive download filter, `filter = arcade`, does not drop the
modules; `!sinden` does).

When PREVIOUS_DB_JSON lists the same files, folders and tags, its
timestamp is kept and the output is byte-identical (the zip has a fixed
date), so an unchanged database is not republished. Prints `changed` or
`unchanged`.
"""

import datetime
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP_DATE = (2000, 1, 1, 0, 0, 0)


def normalize(tag):
    # Downloader matches filter terms lowercased, without '-' and '_'.
    return tag.lower().replace("-", "").replace("_", "")


def build(cfg, builds):
    db = cfg["database"]
    folder = db["folder"]
    tag_names = [normalize(t) for t in db["tags"]]
    tags = {t: n for n, t in enumerate(tag_names)}
    ftags = [tags[t] for t in tag_names]
    files, folders = {}, {folder: {"tags": ftags}}
    for b in builds:
        rel = f"{folder}/{b['kernel_release']}"
        kdir = f"{rel}/{b['id']}"
        folders[rel] = {"tags": ftags}
        folders[kdir] = {"tags": ftags}
        for f in b["files"]:
            files[f"{kdir}/{f['name']}"] = {
                "hash": f["md5"],
                "size": f["size"],
                "url": f["url"],
                "tags": ftags,
            }
    if not files:
        sys.exit("make-db: no build in the index: nothing to publish")
    return {
        "v": 1,
        "db_id": db["db_id"],
        "timestamp": 0,
        "files": dict(sorted(files.items())),
        "folders": dict(sorted(folders.items())),
        "tag_dictionary": tags,
    }


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    index_path, out = sys.argv[1], sys.argv[2]
    with open(os.path.join(ROOT, "config.json")) as f:
        cfg = json.load(f)
    with open(index_path) as f:
        builds = json.load(f)["builds"]
    db = build(cfg, builds)
    prev = None
    if len(sys.argv) == 4 and os.path.exists(sys.argv[3]):
        with open(sys.argv[3]) as f:
            prev = json.load(f)
    same = prev is not None and {**prev, "timestamp": 0} == db
    db["timestamp"] = prev["timestamp"] if same else int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    text = json.dumps(db, indent=2) + "\n"
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "db.json"), "w") as f:
        f.write(text)
    info = zipfile.ZipInfo("db.json", ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with zipfile.ZipFile(os.path.join(out, "db.json.zip"), "w") as z:
        z.writestr(info, text, compresslevel=9)
    print("unchanged" if same else "changed")


if __name__ == "__main__":
    main()
