#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
#   abi-check.sh TREE WORK CROSS CC JOBS LOCALVERSION [STOCK_BUILD MODULE_BUILD]
#
# The optional check of build.sh --abi-check (two full vmlinux builds).
# TREE: the patched source; WORK: build.sh's work directory (stock/config,
# stock/exports, build/ configured with the module options);
# LOCALVERSION: the release's suffix (-MiSTer); STOCK_BUILD and
# MODULE_BUILD default to WORK/abi-stock and WORK/build.
#
# 1. vmlinux built from the stock config and vmlinux built from the
#    module config are made of identical objects but the embedded config
#    (kernel/configs.o): enabling the media options as modules changed no
#    built-in code or data, so the modules were built for the kernel the
#    stock image runs. (The Images themselves differ by that config and
#    the addresses it shifts.)
# 2. The exports of the vmlinux built from the stock config (name, GPL or
#    not, namespace) equal the export table read from the stock image:
#    the source commit and config are the stock kernel's as far as any
#    module can see, and kimage.py read the table right.
#
# Both builds use the same deterministic KBUILD_BUILD_* values. Exits 1 on a difference.

set -euo pipefail

[[ $# -ge 6 ]] || { sed -n '4,21p' "$0" >&2; exit 2; }
tree=$1 work=$2 cross=$3 cc=$4 jobs=$5 localversion=$6
stock_build=${7:-$work/abi-stock}
module_build=${8:-$work/build}

export KBUILD_BUILD_TIMESTAMP='Thu Jan  1 00:00:00 UTC 1970'
export KBUILD_BUILD_USER=abi KBUILD_BUILD_HOST=check KBUILD_BUILD_VERSION=1

make_k() {
	local dir=$1
	shift
	make -s -C "$tree" O="$dir" ARCH=arm CROSS_COMPILE="$cross" CC="$cc" \
		RUSTC=/nonexistent LOCALVERSION="$localversion" -j"$jobs" "$@"
}

if [[ ! -f $stock_build/.config ]]; then
	mkdir -p "$stock_build"
	cp "$work/stock/config" "$stock_build/.config"
	make_k "$stock_build" olddefconfig
fi
make_k "$stock_build" vmlinux
make_k "$module_build" vmlinux

# Every object linked into vmlinux, without its debug info (which holds
# the build directory) and .comment, compared between the two builds.
# kernel/configs.o is the embedded .config (CONFIG_IKCONFIG), the one
# object that must differ.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
objects=0
differ=()
for lib in vmlinux.a lib/lib.a arch/arm/lib/lib.a; do
	[[ -f $stock_build/$lib ]] || continue
	while read -r obj; do
		obj=${obj#"$stock_build/"}
		objects=$((objects + 1))
		"${cross}objcopy" --strip-debug -R .comment "$stock_build/$obj" "$tmp/a.o"
		if [[ ! -f $module_build/$obj ]]; then
			differ+=("$obj (missing)")
			continue
		fi
		"${cross}objcopy" --strip-debug -R .comment "$module_build/$obj" "$tmp/b.o"
		cmp -s "$tmp/a.o" "$tmp/b.o" || differ+=("$obj")
	done < <("${cross}ar" t "$stock_build/$lib")
done
if [[ ${#differ[@]} -ne 1 || ${differ[0]} != kernel/configs.o ]]; then
	echo "abi-check: the module config changes built-in objects: ${differ[*]}" >&2
	exit 1
fi
echo "abi-check: $objects built-in objects identical with and without the media options (but kernel/configs.o, the embedded config)" >&2

# vmlinux.symvers: "crc\tname\tvmlinux\tEXPORT_SYMBOL[_GPL]\tnamespace".
awk -F'\t' '{ print $2 "\t" $4 "\t" $5 }' "$stock_build/vmlinux.symvers" | sort >"$work/abi-exports.built"
sort "$work/stock/exports" >"$work/abi-exports.stock"
if ! diff -u "$work/abi-exports.stock" "$work/abi-exports.built" >"$work/abi-exports.diff"; then
	echo "abi-check: the stock image's exports differ from the source's:" >&2
	head -40 "$work/abi-exports.diff" >&2
	exit 1
fi
echo "abi-check: the stock image's $(wc -l <"$work/abi-exports.stock") exports equal the source's" >&2
