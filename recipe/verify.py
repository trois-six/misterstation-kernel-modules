#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Checks that a set of kernel modules loads into a stock kernel.

  verify.py --exports EXPORTS --vermagic VERMAGIC [--order OUT]
            [--root NAME]... MODULE.ko...

EXPORTS is the stock kernel's export table (kimage.py exports: "name\t
EXPORT_SYMBOL[_GPL]\tnamespace" per line), VERMAGIC its vermagic string
(kimage.py vermagic). Reads each module's ELF itself (32-bit ARM, no
binutils needed) and checks what the kernel's loader checks:

* its vermagic equals the kernel's (no MODVERSIONS, so this and the
  symbols are the whole ABI check the loader makes);
* every undefined symbol is exported by the stock kernel or by another
  module of the set; GPL-only exports are used by GPL modules only; a
  symbol exported in a namespace is used by a module importing that
  namespace (or named by a "module:" namespace);
* every module it depends on (modinfo "depends") is in the set.

With --root, only the modules the roots need are checked and listed.
Prints the load order (dependencies first, then by name) and writes it to
OUT when given. Exits 1 on the first set of failures, listing them all.
"""

import argparse
import os
import struct
import sys

GPL_LICENSES = {"GPL", "GPL v2", "GPL and additional rights",
                "Dual BSD/GPL", "Dual MIT/GPL", "Dual MPL/GPL"}


def norm(name):
    return name.replace("-", "_")


class Module:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            data = f.read()
        if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
            raise SystemExit(f"{path}: not a 32-bit little-endian ELF")
        (e_shoff,) = struct.unpack_from("<I", data, 0x20)
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x2E)
        sections = []
        for i in range(e_shnum):
            sections.append(struct.unpack_from("<10I", data, e_shoff + i * e_shentsize))
        shstr = sections[e_shstrndx]

        def name_at(table, off):
            start = table[4] + off
            return data[start:data.index(b"\0", start)].decode()

        self.sections = {}
        for i, s in enumerate(sections):
            self.sections[i] = (name_at(shstr, s[0]), s)
        by_name = {n: s for n, s in self.sections.values()}
        mi = by_name.get(".modinfo")
        if mi is None:
            raise SystemExit(f"{path}: no .modinfo")
        self.modinfo = {}
        for field in data[mi[4]:mi[4] + mi[5]].split(b"\0"):
            if b"=" in field:
                k, v = field.decode().split("=", 1)
                self.modinfo.setdefault(k, []).append(v)
        # The kernel treats "-" and "_" alike in module names.
        self.name = norm(self.info("name") or os.path.basename(path)[:-3])
        self.depends = [norm(d) for d in (self.info("depends") or "").split(",") if d]
        symtab = by_name[".symtab"]
        strtab = sections[symtab[6]]
        self.undefined = set()
        self.exports = {}  # name -> GPL?
        for off in range(symtab[4], symtab[4] + symtab[5], 16):
            st_name, _value, _size, st_info, _other, st_shndx = struct.unpack_from(
                "<IIIBBH", data, off)
            sym = name_at(strtab, st_name)
            bind = st_info >> 4
            if st_shndx == 0 and sym and bind in (1, 2):  # GLOBAL, WEAK
                self.undefined.add(sym)
            elif sym.startswith("__ksymtab_") and st_shndx < len(sections):
                sec = self.sections[st_shndx][0]
                self.exports[sym[len("__ksymtab_"):]] = sec.startswith("___ksymtab_gpl+")
        # Symbols the loader resolves itself or the ELF ABI leaves undefined.
        self.undefined.discard("__this_module")

    def info(self, key):
        v = self.modinfo.get(key)
        return v[0] if v else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exports", required=True)
    ap.add_argument("--vermagic", required=True)
    ap.add_argument("--order")
    ap.add_argument("--root", action="append",
                    help="keep only this module and what it depends on (repeatable)")
    ap.add_argument("modules", nargs="+")
    args = ap.parse_args()

    kernel = {}
    with open(args.exports) as f:
        for line in f:
            name, kind, ns = (line.rstrip("\n").split("\t") + [""])[:3]
            kernel[name] = (kind == "EXPORT_SYMBOL_GPL", ns)

    mods = [Module(p) for p in args.modules]
    by_name = {m.name: m for m in mods}
    if args.root:
        # Only the modules the roots need, the others are left out.
        keep, todo = set(), [norm(r) for r in args.root]
        while todo:
            n = todo.pop()
            if n in keep:
                continue
            if n not in by_name:
                sys.exit(f"verify: {n} is needed and was not built")
            keep.add(n)
            todo.extend(by_name[n].depends)
        for m in mods:
            if m.name not in keep:
                print(f"verify: {m.name} is not needed, left out", file=sys.stderr)
        mods = [m for m in mods if m.name in keep]
        by_name = {m.name: m for m in mods}
    provided = {}
    for m in mods:
        for sym, gpl in m.exports.items():
            provided[sym] = (m.name, gpl)

    errors = []
    for m in mods:
        vm = m.info("vermagic")
        if vm is None or vm.strip() != args.vermagic.strip():
            errors.append(f"{m.name}: vermagic {vm!r}, kernel {args.vermagic!r}")
        gpl_ok = m.info("license") in GPL_LICENSES
        imports = set(m.modinfo.get("import_ns", []))
        for sym in sorted(m.undefined):
            if sym in provided:
                owner, gpl = provided[sym]
                if gpl and not gpl_ok:
                    errors.append(f"{m.name}: GPL-only {sym} of {owner}, license {m.info('license')}")
                continue
            if sym not in kernel:
                errors.append(f"{m.name}: {sym} is not exported by the stock kernel")
                continue
            gpl, ns = kernel[sym]
            if gpl and not gpl_ok:
                errors.append(f"{m.name}: GPL-only {sym}, license {m.info('license')}")
            if ns.startswith("module:"):
                if m.name not in ns[len("module:"):].split(","):
                    errors.append(f"{m.name}: {sym} is exported to {ns} only")
            elif ns and ns not in imports:
                errors.append(f"{m.name}: {sym} is in namespace {ns}, not imported")
        for dep in m.depends:
            if dep not in by_name:
                errors.append(f"{m.name}: depends on {dep}, not in the set")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)

    # Dependencies first; among the ready ones, by name (stable).
    order, done = [], set()
    while len(order) < len(mods):
        ready = sorted(
            m.name for m in mods if m.name not in done and all(d in done for d in m.depends))
        if not ready:
            sys.exit("verify: dependency cycle")
        for name in ready[:1]:
            order.append(name)
            done.add(name)
    lines = [f"{os.path.basename(by_name[n].path)}" for n in order]
    print("\n".join(lines))
    if args.order:
        with open(args.order, "w") as f:
            f.write("\n".join(lines) + "\n")
    print(f"verify: {len(mods)} modules, vermagic {args.vermagic.strip()!r}, "
          f"{sum(len(m.undefined) for m in mods)} symbol references resolved",
          file=sys.stderr)


if __name__ == "__main__":
    main()
