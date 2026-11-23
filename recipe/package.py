#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Writes the manifest of a kernel module package.

  package.py --zimage ZIMAGE_DTB --order ORDER --dir DIR [--commit SHA]
             [--linux-release NAME] [--source URL] [--recipe TREE]

DIR holds the modules ORDER lists (verify.py --order), in load order.
Writes DIR/manifest.json, installed by Downloader next to the modules
(linux_modules/<kernel release>/<id>/manifest.json) and read by the
loader (MiSTerStation):

  {
    "format": 1,
    "id": "3a53fb98bca8210a",                    sha256(proc_version)[:16]
    "kernel_release": "6.18.38-MiSTer",          uname -r
    "proc_version": "Linux version ...",         /proc/version, no newline
    "vermagic": "6.18.38-MiSTer SMP ...",
    "zimage_sha256": "...",                      the stock zImage_dtb
    "linux_release": "20260912",                 informational
    "source_commit": "...", "source": "...",     informational
    "recipe": "...",                             git tree of recipe/
    "modules": [ {"file": "mc.ko", "size": N, "sha256": "..."}, ... ]
  }

"modules" is in load order. Keys are written in this order, one per line,
ASCII only, so that the file is stable byte for byte. Prints the id.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def kimage(cmd, zimage):
    here = os.path.dirname(os.path.abspath(__file__))
    out = subprocess.run([sys.executable, "-I", os.path.join(here, "kimage.py"), cmd, zimage],
                         check=True, capture_output=True, text=True).stdout
    return out.rstrip("\n")


def kernel_id(proc_version):
    return hashlib.sha256(proc_version.encode()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zimage", required=True)
    ap.add_argument("--order", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--commit", default="")
    ap.add_argument("--linux-release", default="")
    ap.add_argument("--source", default="")
    ap.add_argument("--recipe", default="")
    args = ap.parse_args()

    with open(args.order) as f:
        files = [line.strip() for line in f if line.strip()]
    modules = []
    for name in files:
        if "/" in name or not name.endswith(".ko"):
            sys.exit(f"package: bad module file name {name!r}")
        path = os.path.join(args.dir, name)
        modules.append({"file": name, "size": os.path.getsize(path), "sha256": sha256(path)})

    proc_version = kimage("version", args.zimage)
    manifest = {
        "format": 1,
        "id": kernel_id(proc_version),
        "kernel_release": kimage("release", args.zimage),
        "proc_version": proc_version,
        "vermagic": kimage("vermagic", args.zimage),
        "zimage_sha256": sha256(args.zimage),
        "linux_release": args.linux_release,
        "source_commit": args.commit,
        "source": args.source,
        "recipe": args.recipe,
        "modules": modules,
    }
    text = json.dumps(manifest, indent=1, ensure_ascii=True) + "\n"
    with open(os.path.join(args.dir, "manifest.json"), "w") as f:
        f.write(text)
    print(kernel_id(proc_version))


if __name__ == "__main__":
    main()
