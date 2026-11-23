#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Maps a stock MiSTer kernel to the Linux-Kernel_MiSTer commit it was
# built from.
#
#   find-commit.sh SRC RELEASE BUILD_DATE CONFIG [BRANCH]
#
# SRC: a clone of https://github.com/MiSTer-devel/Linux-Kernel_MiSTer
# (blobless is enough); RELEASE: the image's `uname -r` (6.18.38-MiSTer);
# BUILD_DATE: its banner's build time in ISO 8601 UTC; CONFIG: its
# embedded .config (kimage.py config). BRANCH defaults to
# MiSTer-v<major>.<minor> of RELEASE.
#
# The kernel carries no commit id (CONFIG_LOCALVERSION_AUTO is off), so
# the commit is found from what the image does carry:
#
#   1. the candidates are the branch's commits whose Makefile gives
#      RELEASE (VERSION.PATCHLEVEL.SUBLEVEL + "-MiSTer"), committed at
#      or before BUILD_DATE (the build is made from a commit already
#      made, the release published after it);
#   2. among them, those whose arch/arm/configs/MiSTer_defconfig, a full
#      .config in this repository, equals CONFIG once the toolchain
#      lines (compiler version and capability probes) are left out;
#   3. the newest of these is the answer.
#
# Limits: a build from uncommitted changes, or from a commit pushed
# later with an older commit date, cannot be told apart from its parent
# by date and config alone. The export check of verify.py (every symbol
# the modules use exported by the stock image) and the optional ABI
# check of build.sh (--abi-check: the stock image's export table equals
# the one built from the commit) catch a wrong pick that matters to the
# modules. Prints the commit on stdout, the reasoning on stderr.

set -euo pipefail

if [[ $# -lt 4 ]]; then
	sed -n '4,13p' "$0" >&2
	exit 2
fi
src=$1 release=$2 build_date=$3 config=$4
base=${release%%-*}
major_minor=$(cut -d. -f1-2 <<<"$base")
branch=${5:-MiSTer-v$major_minor}

normalize() {
	grep -E '^(CONFIG_|# CONFIG_)' |
		grep -vE 'CONFIG_(CC_VERSION_TEXT|GCC_VERSION|CLANG_VERSION|AS_VERSION|LD_VERSION|LLD_VERSION|AS_IS_[A-Z_]+|LD_IS_[A-Z_]+|CC_IS_[A-Z_]+|CC_HAS_[A-Z0-9_]+|CC_CAN_[A-Z0-9_]+|AS_HAS_[A-Z0-9_]+|LD_CAN_[A-Z0-9_]+|LD_HAS_[A-Z0-9_]+|TOOLS_SUPPORT_[A-Z_]+|PAHOLE_VERSION|RUSTC_[A-Z_]+|RUST_IS_AVAILABLE|GCC_ASM_[A-Z_]+|GCC10_NO_[A-Z_]+|HAVE_LD_DEAD_CODE_DATA_ELIMINATION|LD_DEAD_CODE_DATA_ELIMINATION)[= ]' |
		sort
}

ref="refs/remotes/origin/$branch"
git -C "$src" rev-parse --verify -q "$ref" >/dev/null || ref="refs/heads/$branch"
git -C "$src" rev-parse --verify -q "$ref" >/dev/null || {
	echo "find-commit: no branch $branch in $src" >&2
	exit 1
}

want=$(normalize <"$config")
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
printf '%s\n' "$want" >"$tmp/want"

# git log --before compares the committer date.
while read -r commit date; do
	mk=$(git -C "$src" show "$commit:Makefile" 2>/dev/null | sed -n "1,8p")
	v=$(sed -nE 's/^VERSION = //p' <<<"$mk").$(sed -nE 's/^PATCHLEVEL = //p' <<<"$mk").$(sed -nE 's/^SUBLEVEL = //p' <<<"$mk")
	if [[ "$v-MiSTer" != "$release" ]]; then
		echo "find-commit: $commit ($date): version $v, stop" >&2
		break
	fi
	git -C "$src" show "$commit:arch/arm/configs/MiSTer_defconfig" | normalize >"$tmp/have"
	n=$(diff "$tmp/have" "$tmp/want" | grep -c '^[<>]' || true)
	if [[ $n -eq 0 ]]; then
		echo "find-commit: $commit ($date): version and config match" >&2
		echo "$commit"
		exit 0
	fi
	echo "find-commit: $commit ($date): config differs ($n lines)" >&2
done < <(git -C "$src" log --format='%H %cI' --before="$build_date" "$ref")

echo "find-commit: no commit of $branch matches $release built $build_date" >&2
exit 1
