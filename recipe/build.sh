#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Builds the V4L2/UVC kernel modules (a Sinden lightgun's camera) for a
# stock MiSTer kernel, without changing that kernel.
#
#   build.sh [options] ZIMAGE_DTB
#
# Options:
#   --src DIR            clone of Linux-Kernel_MiSTer (blobless is enough;
#                        cloned there when missing; default target/linux)
#   --work DIR           build directory (default target/work)
#   --out DIR            the package (default target/out/<id>)
#   --commit SHA         the source commit (default: the kernel's entry in
#                        commits.json, else find-commit.sh)
#   --linux-release NAME informational, e.g. 20260912
#   --recipe TREE        informational, the git tree of recipe/
#   --cross PREFIX       toolchain prefix (default arm-linux-gnueabihf-)
#   --cc CC              compiler (default <prefix>gcc-10 if present, the
#                        stock kernels being built with GCC 10.2)
#   --abi-check          also build vmlinux from the stock config and from
#                        the module config, and check that (1) their
#                        Images are identical (the media options change no
#                        built-in code), (2) the stock image's export table
#                        equals the one built from the commit
#   -j N                 parallel jobs (default: nproc)
#
# Steps: read the image (kimage.py), map it to a commit (find-commit.sh),
# check the source out in a clean worktree and apply patches/*.patch, take
# the image's own .config (CONFIG_IKCONFIG) plus media.config, check that
# only media options changed (check-config.sh), make modules_prepare,
# build drivers/media against a Module.symvers made from the stock
# image's export table, strip the debug info, check the modules
# (verify.py), write the manifest (package.py). Publishing is the
# workflow's (.github/workflows/build.yml).
#
# Exit status: 0 built, 3 a patch of patches/ does not apply to the
# kernel's source (the workflow reports it apart), 1 any other failure.
#
# Debian/Ubuntu packages: gcc-10-arm-linux-gnueabihf (or any
# arm-linux-gnueabihf gcc >= 8) with its plugin headers
# (gcc-10-plugin-dev-arm-linux-gnueabihf: the stock kernels set
# GCC_PLUGINS, which the build needs a plugin-capable compiler to keep)
# binutils-arm-linux-gnueabihf make flex bison bc libssl-dev libelf-dev
# lz4 git python3 (kimage.py needs lz4, lzop for those compressions).

set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
src=$repo/target/linux
work=$repo/target/work
out=
commit=
linux_release=
recipe=
cross=arm-linux-gnueabihf-
cc=
abi_check=0
jobs=$(nproc)
url=https://github.com/MiSTer-devel/Linux-Kernel_MiSTer

while [[ $# -gt 0 ]]; do
	case $1 in
	--src) src=$2; shift 2 ;;
	--work) work=$2; shift 2 ;;
	--out) out=$2; shift 2 ;;
	--commit) commit=$2; shift 2 ;;
	--linux-release) linux_release=$2; shift 2 ;;
	--recipe) recipe=$2; shift 2 ;;
	--cross) cross=$2; shift 2 ;;
	--cc) cc=$2; shift 2 ;;
	--abi-check) abi_check=1; shift ;;
	-j) jobs=$2; shift 2 ;;
	-h | --help) sed -n '4,40p' "$0"; exit 0 ;;
	-*) echo "build.sh: unknown option $1" >&2; exit 2 ;;
	*) break ;;
	esac
done
[[ $# -eq 1 ]] || { sed -n '4,40p' "$0" >&2; exit 2; }
zimage=$(realpath "$1")
if [[ -z $cc ]]; then
	if command -v "${cross}gcc-10" >/dev/null; then cc=${cross}gcc-10; else cc=${cross}gcc; fi
fi

kimage() { python3 -I "$here/kimage.py" "$@"; }
log() { echo "build.sh: $*" >&2; }

mkdir -p "$work/stock"
release=$(kimage release "$zimage")
build_date=$(kimage builddate "$zimage")
vermagic=$(kimage vermagic "$zimage")
kimage version "$zimage" >"$work/stock/version"
kimage config "$zimage" >"$work/stock/config"
kimage exports "$zimage" >"$work/stock/exports"
kimage symvers "$zimage" >"$work/stock/Module.symvers"
log "kernel $release built $build_date, vermagic '$vermagic', $(wc -l <"$work/stock/exports") exports"

if [[ ! -d $src/.git ]]; then
	git clone -q --filter=blob:none "$url" "$src"
fi
# The release's suffix is given on make's command line by MiSTer's
# builds (CONFIG_LOCALVERSION is empty): without it, setlocalversion
# would add "+" for a git tree.
localversion=${release#"${release%%-*}"}
branch=MiSTer-v$(cut -d. -f1-2 <<<"${release%%-*}")
git -C "$src" fetch -q origin "+refs/heads/$branch:refs/remotes/origin/$branch"
id=$(python3 -I -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.read().rstrip("\n").encode()).hexdigest()[:16])' <"$work/stock/version")
# A kernel whose commit was pinned by hand (commits.json) uses it; the
# search still runs, its answer logged when it differs.
pinned=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("kernels", {}).get(sys.argv[2], {}).get("commit", ""))' \
	"$here/commits.json" "$id")
if [[ -z $commit ]]; then
	found=$("$here/find-commit.sh" "$src" "$release" "$build_date" "$work/stock/config" "$branch" || true)
	if [[ -n $pinned ]]; then
		[[ $found == "$pinned" ]] || log "find-commit.sh gives '${found:-nothing}', commits.json pins $pinned: using the pin"
		commit=$pinned
	elif [[ -n $found ]]; then
		commit=$found
	else
		log "no commit of $branch matches this kernel (pin one in commits.json)"
		exit 1
	fi
fi
log "source: $url commit $commit"

tree=$work/src
if [[ -d $tree ]]; then
	git -C "$src" worktree remove --force "$tree" 2>/dev/null || rm -rf "$tree"
fi
git -C "$src" worktree prune
git -C "$src" worktree add -q --detach "$tree" "$commit"
for p in "$here"/patches/*.patch; do
	log "patch $(basename "$p")"
	if ! git -C "$tree" apply --whitespace=nowarn "$p"; then
		log "patch $(basename "$p") does not apply to $commit"
		exit 3
	fi
done

make_k() {
	local dir=$1
	shift
	make -s -C "$tree" O="$dir" ARCH=arm CROSS_COMPILE="$cross" CC="$cc" \
		RUSTC=/nonexistent LOCALVERSION="$localversion" -j"$jobs" "$@"
}

# The image's own config, then the media options.
build=$work/build
rm -rf "$build"
mkdir -p "$build"
cp "$work/stock/config" "$build/.config"
ARCH=arm "$tree/scripts/kconfig/merge_config.sh" -m -O "$build" "$build/.config" \
	"$here/media.config" >/dev/null
make_k "$build" olddefconfig
"$here/check-config.sh" "$work/stock/config" "$build/.config" "$here/media.config"
kver=$(make_k "$build" kernelrelease)
[[ $kver == "$release" ]] || { log "source gives $kver, image is $release"; exit 1; }

# The modules, linked against the stock image's exports.
make_k "$build" modules_prepare
cp "$work/stock/Module.symvers" "$build/Module.symvers"
# drivers/media as an external module tree, its output under $build
# (MO=, Linux 6.13+), the source tree left clean.
make_k "$build" M="$tree/drivers/media" MO="$build/media" modules

out=${out:-$repo/target/out/$id}
rm -rf "$out"
mkdir -p "$out"
while read -r ko; do
	"${cross}strip" --strip-debug -o "$out/$(basename "$ko")" "$ko"
done < <(find "$build/media" -name '*.ko' | sort)
compgen -G "$out/*.ko" >/dev/null || { log "no module was built"; exit 1; }
python3 -I "$here/verify.py" --root uvcvideo --exports "$work/stock/exports" --vermagic "$vermagic" \
	--order "$out/load-order" "$out"/*.ko
# Only what uvcvideo needs is shipped.
for ko in "$out"/*.ko; do
	grep -qxF "$(basename "$ko")" "$out/load-order" || rm "$ko"
done
python3 -I "$here/package.py" --zimage "$zimage" --order "$out/load-order" --dir "$out" \
	--commit "$commit" --linux-release "$linux_release" --source "$url" --recipe "$recipe" >/dev/null
rm "$out/load-order"

if [[ $abi_check -eq 1 ]]; then
	"$here/abi-check.sh" "$tree" "$work" "$cross" "$cc" "$jobs" "$localversion"
fi
log "package in $out (kernel id $id)"
echo "$out"
