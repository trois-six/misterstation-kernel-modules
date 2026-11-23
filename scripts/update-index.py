#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Merge a build record into the published index and keep the newest kernels.

usage: update-index.py OLD_INDEX NEW_INDEX KEEP [RECORD]

RECORD is the record.json the build job wrote, either a new build
({"build": {...}}: replaces any build of the same kernel id) or a Linux
release whose kernel was already built ({"seen": {"id", "linux_release"}}:
the version is added to that build). The index keeps the KEEP builds whose
kernels were built last (the kernel's own build time), newest first.
OLD_INDEX may be missing (first run).
"""

import datetime
import json
import os
import sys


def main():
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__)
    old, new, keep = sys.argv[1], sys.argv[2], int(sys.argv[3])
    builds = []
    if os.path.exists(old):
        with open(old) as f:
            builds = json.load(f)["builds"]
    if len(sys.argv) == 5:
        with open(sys.argv[4]) as f:
            record = json.load(f)
        if "build" in record:
            b = record["build"]
            prev = next((x for x in builds if x["id"] == b["id"]), None)
            if prev is not None:
                # a rebuild (recipe change) keeps the Linux releases seen
                b["linux_releases"] = sorted(set(prev["linux_releases"]) | set(b["linux_releases"]))
            builds = [x for x in builds if x["id"] != b["id"]] + [b]
        elif "seen" in record:
            s = record["seen"]
            for x in builds:
                if x["id"] == s["id"] and s["linux_release"] not in x["linux_releases"]:
                    x["linux_releases"] = sorted(x["linux_releases"] + [s["linux_release"]])
        else:
            sys.exit(f"update-index: unknown record {sorted(record)}")
    builds.sort(key=lambda b: (b["kernel_build_time"], b["id"]), reverse=True)
    dropped = builds[keep:]
    for b in dropped:
        print(f"update-index: {b['tag']} is no longer among the {keep} newest kernels", file=sys.stderr)
    index = {
        "format": 1,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builds": builds[:keep],
    }
    with open(new, "w") as f:
        json.dump(index, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
