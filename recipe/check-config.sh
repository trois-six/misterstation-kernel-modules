#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
#   check-config.sh STOCK_CONFIG MODULE_CONFIG FRAGMENT
#
# Fails unless MODULE_CONFIG (the stock config, FRAGMENT merged, then
# olddefconfig) differs from STOCK_CONFIG by media options only: every
# option set in one and not the other, or set differently, must be one of
# FRAGMENT's, or one of the media options they select (ALLOWED below,
# each built into the modules only: none is tested outside drivers/media
# and include/media, so built-in code compiles the same). Toolchain lines
# (compiler version and probes) are left out. Anything else would mean
# the modules expect a kernel other than the stock one.

set -euo pipefail

[[ $# -eq 3 ]] || { sed -n '4,13p' "$0" >&2; exit 2; }

ALLOWED='MEDIA_SUPPORT MEDIA_SUPPORT_FILTER MEDIA_SUBDRV_AUTOSELECT
MEDIA_CAMERA_SUPPORT VIDEO_DEV MEDIA_CONTROLLER VIDEO_V4L2_I2C
MEDIA_USB_SUPPORT USB_VIDEO_CLASS USB_VIDEO_CLASS_INPUT_EVDEV UVC_COMMON
VIDEOBUF2_CORE VIDEOBUF2_V4L2 VIDEOBUF2_MEMOPS VIDEOBUF2_VMALLOC
VIDEOBUF2_NO_DMA_SHARED_BUFFER VIDEO_CAMERA_SENSOR VIDEO_CAMERA_LENS'

options() {
	# "NAME=value" per set option ("is not set" and absent are the same
	# to Kconfig and to the code: both left out).
	sed -nE 's/^CONFIG_([A-Za-z0-9_]+)=(.*)$/\1=\2/p' "$1" |
		grep -vE '^(CC_VERSION_TEXT|GCC_VERSION|CLANG_VERSION|AS_VERSION|LD_VERSION|LLD_VERSION|AS_IS_[A-Z_]+|LD_IS_[A-Z_]+|CC_IS_[A-Z_]+|CC_HAS_[A-Z0-9_]+|CC_CAN_[A-Z0-9_]+|AS_HAS_[A-Z0-9_]+|LD_CAN_[A-Z0-9_]+|LD_HAS_[A-Z0-9_]+|TOOLS_SUPPORT_[A-Z_]+|PAHOLE_VERSION|RUSTC_[A-Z_]+|RUST_IS_AVAILABLE|GCC_ASM_[A-Z_]+|GCC10_NO_[A-Z_]+|HAVE_LD_DEAD_CODE_DATA_ELIMINATION|LD_DEAD_CODE_DATA_ELIMINATION)=' |
		sort
}

allowed=$(printf '%s\n' $ALLOWED $(sed -nE 's/^#? ?CONFIG_([A-Za-z0-9_]+)[= ].*/\1/p' "$3") | sort -u)
bad=0
while read -r name; do
	if ! grep -qx "$name" <<<"$allowed"; then
		echo "check-config: $name changed: stock '$(options "$1" | grep "^$name=" || echo unset)'," \
			"module build '$(options "$2" | grep "^$name=" || echo unset)'" >&2
		bad=1
	fi
done < <(diff <(options "$1") <(options "$2") | sed -nE 's/^[<>] ([A-Za-z0-9_]+)=.*/\1/p' | sort -u)
[[ $bad -eq 0 ]] || exit 1
echo "check-config: only media options changed" >&2
