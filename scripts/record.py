#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Write the build record (record.json) of a package for update-index.py.

usage: record.py PACKAGE_DIR TAG BUILD_TIME LINUX_RELEASE OUT

PACKAGE_DIR holds manifest.json (recipe/package.py) and its modules;
TAG is the release the files are published under, BUILD_TIME the
kernel's build time (kimage.py builddate). Every module is checked
against the manifest (size, SHA-256) and gets its MD5 (Downloader's hash)
and release URL; manifest.json is listed last.
"""

import datetime
import hashlib
import json
import os
import sys


def digest(path):
    md5, sha = hashlib.md5(), hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 16):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def main():
    if len(sys.argv) != 6:
        sys.exit(__doc__)
    pkg, tag, build_time, linux_release, out = sys.argv[1:]
    repo = os.environ["GITHUB_REPOSITORY"]
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    with open(os.path.join(pkg, "manifest.json")) as f:
        m = json.load(f)

    def entry(name):
        path = os.path.join(pkg, name)
        md5, sha = digest(path)
        return {"name": name, "size": os.path.getsize(path), "md5": md5, "sha256": sha,
                "url": f"{server}/{repo}/releases/download/{tag}/{name}"}

    files = []
    for mod in m["modules"]:
        e = entry(mod["file"])
        if e["size"] != mod["size"] or e["sha256"] != mod["sha256"]:
            sys.exit(f"record: {mod['file']} does not match the manifest")
        files.append(e)
    files.append(entry("manifest.json"))
    build = {
        "id": m["id"],
        "kernel_release": m["kernel_release"],
        "proc_version": m["proc_version"],
        "vermagic": m["vermagic"],
        "kernel_build_time": build_time,
        "linux_releases": [linux_release],
        "source_commit": m["source_commit"],
        "recipe": m["recipe"],
        "recipe_commit": os.environ.get("GITHUB_SHA", ""),
        "tag": tag,
        "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_url": os.environ.get("RUN_URL", ""),
        "files": files,
    }
    with open(out, "w") as f:
        json.dump({"build": build}, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
