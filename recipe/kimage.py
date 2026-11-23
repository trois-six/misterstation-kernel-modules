#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Inspect a stock MiSTer kernel image (zImage_dtb) without its sources.

Subcommands (each reads the zImage_dtb given as first argument):

  version  ZIMAGE           the "Linux version ..." banner (= /proc/version)
  release  ZIMAGE           the kernel release (uname -r)
  vermagic ZIMAGE           the vermagic string modules must carry
  config   ZIMAGE           the embedded .config (CONFIG_IKCONFIG)
  builddate ZIMAGE          the build timestamp of the banner, ISO 8601 UTC
  exports  ZIMAGE           the exported symbols, one per line:
                            "<name>\t<EXPORT_SYMBOL|EXPORT_SYMBOL_GPL>\t<ns>"
  symvers  ZIMAGE           the same as a Module.symvers for modpost

The image is an ARM zImage (any of the kernel's compressions: gzip, lz4,
lzma, xz, lzo) with a device tree appended. The decompressed Image is
linked at PAGE_OFFSET + TEXT_OFFSET (0xC0008000 on MiSTer). The export
tables (__ksymtab and __ksymtab_gpl, arrays of struct kernel_symbol
{value, name, namespace} without PREL32 relocations on ARM) are found as
the long runs of entries whose name and namespace pointers point to
NUL-terminated identifiers inside the image; each run is sorted by name
(the kernel bsearches it), which is checked.
"""

import datetime
import gzip
import lzma
import os
import re
import shutil
import struct
import subprocess
import sys

PAGE_OFFSET = 0xC0000000
IMAGE_BASE = PAGE_OFFSET + 0x8000
IDENT = re.compile(rb"[A-Za-z_][A-Za-z0-9_.$]*\Z")
NAMESPACE = re.compile(rb"[A-Za-z_:][A-Za-z0-9_.:,-]*\Z")


def decompress(zimage: bytes) -> bytes:
    """The decompressed kernel Image inside a zImage."""
    # gzip: 1f 8b 08 00; xz: fd 37 7a 58 5a 00; lz4 legacy: 02 21 4c 18;
    # lzma: 5d 00 00; lzo: 89 4c 5a 4f.
    candidates = []
    for magic, kind in (
        (b"\x1f\x8b\x08\x00", "gzip"),
        (b"\xfd7zXZ\x00", "xz"),
        (b"\x02\x21\x4c\x18", "lz4"),
        (b"\x89LZO\x00", "lzo"),
        (b"\x5d\x00\x00", "lzma"),
    ):
        start = 0
        while True:
            off = zimage.find(magic, start)
            if off < 0:
                break
            candidates.append((off, kind))
            start = off + 1
    candidates.sort()
    for off, kind in candidates:
        data = zimage[off:]
        try:
            if kind == "gzip":
                out = gzip.GzipFile(fileobj=__import__("io").BytesIO(data)).read()
            elif kind == "xz":
                out = lzma.LZMADecompressor(lzma.FORMAT_XZ).decompress(data)
            elif kind == "lzma":
                out = lzma.LZMADecompressor(lzma.FORMAT_ALONE).decompress(data)
            else:
                tool = {"lz4": ["lz4", "-dc"], "lzo": ["lzop", "-dc"]}[kind]
                if shutil.which(tool[0]) is None:
                    sys.exit(f"kimage: {tool[0]} is needed to read this image")
                p = subprocess.run(tool, input=data, capture_output=True)
                out = p.stdout
        except (OSError, EOFError, lzma.LZMAError):
            continue
        if b"Linux version " in out:
            return out
    sys.exit("kimage: no compressed kernel found in the image")


def banner(image: bytes) -> str:
    m = re.search(rb"Linux version [^\n\x00]*#\d+ [^\n\x00]*", image)
    if not m:
        sys.exit("kimage: no Linux version banner")
    return m.group(0).decode("ascii", "replace")


# The release names the tag of the build, the folder of the Downloader
# database and so the folder on the user's SD card: it comes from a kernel
# image downloaded from the network, and only the characters the database
# accepts are allowed (scripts/check-db.py's folder pattern).
RELEASE_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}")


def release(image: bytes) -> str:
    rel = banner(image).split()[2]
    if not RELEASE_RE.fullmatch(rel):
        sys.exit(f"kimage: unexpected kernel release {rel!r}")
    return rel


def vermagic(image: bytes) -> str:
    rel = re.escape(release(image).encode())
    m = re.search(rel + rb" [ -~]*?(?:mod_unload|SMP|preempt|ARMv)[ -~]*?\x00", image)
    if not m:
        sys.exit("kimage: no vermagic string")
    return m.group(0)[:-1].decode()


def build_date(image: bytes) -> str:
    # "... #2 SMP Sat Sep 12 20:19:51 CST 2026": the zone is an
    # abbreviation, mapped for the ones MiSTer's builders use.
    text = banner(image)
    m = re.search(r"(\w{3} \w{3} +\d+ \d\d:\d\d:\d\d) (\S+) (\d{4})$", text)
    if not m:
        sys.exit("kimage: no build date in the banner")
    zones = {"UTC": 0, "GMT": 0, "CST": 8, "CET": 1, "CEST": 2, "EST": -5,
             "EDT": -4, "CDT": -5, "PST": -8, "PDT": -7, "MSK": 3, "AEST": 10,
             "AEDT": 11, "JST": 9}
    zone = m.group(2)
    if zone not in zones:
        sys.exit(f"kimage: unknown time zone {zone} in the banner")
    t = datetime.datetime.strptime(f"{m.group(1)} {m.group(3)}", "%a %b %d %H:%M:%S %Y")
    t -= datetime.timedelta(hours=zones[zone])
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def config(zimage: bytes, image: bytes) -> str:
    for blob in (image, zimage):
        off = blob.find(b"IKCFG_ST")
        if off >= 0:
            end = blob.find(b"IKCFG_ED", off)
            return gzip.decompress(blob[off + 8:end]).decode()
    sys.exit("kimage: no embedded config (CONFIG_IKCONFIG is not set)")


def cstring(image: bytes, addr: int):
    off = addr - IMAGE_BASE
    if not 0 <= off < len(image):
        return None
    end = image.find(b"\x00", off, off + 256)
    if end < 0:
        return None
    return image[off:end]


def exports(image: bytes):
    """([(name, namespace)] of __ksymtab, the same of __ksymtab_gpl)."""
    n = len(image) // 4
    words = struct.unpack_from(f"<{n}I", image)

    def entry(i):
        if i + 2 >= n:
            return None
        name = cstring(image, words[i + 1])
        ns = cstring(image, words[i + 2])
        if name is None or ns is None or not IDENT.match(name):
            return None
        # Namespaces are identifiers, or "module:a,b" since 6.18
        # (EXPORT_SYMBOL_FOR_MODULES).
        if ns and not NAMESPACE.match(ns):
            return None
        # Every exported address is a kernel one; the trace event enum
        # maps (also {value, name, name} triples) hold small integers.
        if words[i] < PAGE_OFFSET:
            return None
        return name.decode(), ns.decode()

    runs = []
    i = 0
    while i < n:
        e = entry(i)
        if e is None:
            i += 1
            continue
        run = [e]
        j = i + 3
        while (e := entry(j)) is not None:
            run.append(e)
            j += 3
        if len(run) >= 64:
            runs.append(run)
            i = j
        else:
            i += 1
    if os.environ.get("KIMAGE_DEBUG"):
        for run in runs:
            print(len(run), run[0], run[-1], file=sys.stderr)
    if not runs:
        sys.exit("kimage: no export table found")
    # The linker script places __ksymtab_gpl right after __ksymtab: the
    # longest run is both, each sorted by name.
    run = max(runs, key=len)
    tables = [[run[0]]]
    for prev, e in zip(run, run[1:]):
        if e[0] <= prev[0]:
            tables.append([])
        tables[-1].append(e)
    if len(tables) != 2:
        sys.exit(f"kimage: expected 2 sorted export tables, found {len(tables)}")
    return tables


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    cmd, path = sys.argv[1], sys.argv[2]
    with open(path, "rb") as f:
        zimage = f.read()
    image = decompress(zimage)
    if cmd == "version":
        print(banner(image))
    elif cmd == "release":
        print(release(image))
    elif cmd == "vermagic":
        print(vermagic(image))
    elif cmd == "builddate":
        print(build_date(image))
    elif cmd == "config":
        sys.stdout.write(config(zimage, image))
    elif cmd in ("exports", "symvers"):
        plain, gpl = exports(image)
        rows = [(s, "EXPORT_SYMBOL", ns) for s, ns in plain]
        rows += [(s, "EXPORT_SYMBOL_GPL", ns) for s, ns in gpl]
        for s, kind, ns in sorted(rows):
            if cmd == "exports":
                print(f"{s}\t{kind}\t{ns}")
            else:
                print(f"0x00000000\t{s}\tvmlinux\t{kind}\t{ns}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
