#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Decide whether the workflow has to build.

usage: detect.py DISTRIBUTION_DB_ZIP INDEX RECIPE [--linux-url URL] [--force]

DISTRIBUTION_DB_ZIP is Distribution_MiSTer's db.json.zip: its `linux`
entry ({url, version, hash, size}) is the Linux release MiSTer's
Downloader installs. INDEX is the published index.json (the `db` branch;
may be missing on the first run), RECIPE the git tree id of recipe/.

Prints one JSON object: {"build": bool, "reason": str, "url", "version",
"md5", "size"}; the four values taken from the database are checked
against the format each must have (the workflow turns them into step
outputs and shell variables). No build when a published build of the current recipe
already lists that Linux release; the build job itself then finds out,
from the kernel image, whether the kernel is new or was already built for
another Linux release (only its version is then recorded).
"""

import argparse
import json
import os
import re
import sys
import zipfile

URL_RE = re.compile(r"^https://github\.com/MiSTer-devel/[A-Za-z0-9_.-]+/releases/download/[^\s?#]+/linux_release_(\d{8})\.7z$")
# Everything printed here comes from a database downloaded from the
# network and ends up in the workflow's step outputs (one `key=value` line
# each) and in shell variables of the build: a value with a newline in it
# would write further outputs of its own, so the three that are not the
# URL (checked above) are checked too, as strictly as their format allows.
VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}")
MD5_RE = re.compile(r"[0-9a-f]{32}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("distribution_db")
    ap.add_argument("index")
    ap.add_argument("recipe")
    ap.add_argument("--linux-url", default="")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.linux_url:
        m = URL_RE.match(args.linux_url)
        if not m:
            sys.exit(f"detect: {args.linux_url} is not a MiSTer-devel linux_release_<YYYYMMDD>.7z")
        linux = {"url": args.linux_url, "version": m[1][2:], "hash": "", "size": 0}
    else:
        with zipfile.ZipFile(args.distribution_db) as z:
            linux = json.loads(z.read("db.json"))["linux"]
        if not URL_RE.match(linux["url"]):
            sys.exit(f"detect: unexpected Linux release URL {linux['url']!r}")
    version = str(linux["version"])
    if not VERSION_RE.fullmatch(version):
        sys.exit(f"detect: unexpected Linux release version {version!r}")
    md5 = str(linux.get("hash", ""))
    if md5 and not MD5_RE.fullmatch(md5):
        sys.exit(f"detect: unexpected Linux release hash {md5!r}")
    size = linux.get("size", 0)
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        sys.exit(f"detect: unexpected Linux release size {size!r}")

    builds = []
    if os.path.exists(args.index):
        with open(args.index) as f:
            builds = json.load(f)["builds"]
    done = [b for b in builds if version in b["linux_releases"] and b["recipe"] == args.recipe]
    if args.force:
        build, reason = True, "forced"
    elif done:
        build, reason = False, f"linux_release {version} already built ({done[0]['tag']})"
    elif any(version in b["linux_releases"] for b in builds):
        build, reason = True, f"recipe changed since linux_release {version} was built"
    else:
        build, reason = True, f"new linux_release {version}"
    print(json.dumps({"build": build, "reason": reason, "url": linux["url"], "version": version,
                      "md5": md5, "size": size}))


if __name__ == "__main__":
    main()
