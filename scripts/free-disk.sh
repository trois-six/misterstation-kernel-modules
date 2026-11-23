#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Free disk space on a GitHub-hosted Ubuntu runner: the kernel clone, its
# worktree and the two vmlinux builds of the ABI check need about 10 GB.
# Removes preinstalled SDKs the build never uses.
set -u
df -h / | tail -n1
sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc /usr/local/.ghcup \
  /opt/hostedtoolcache/CodeQL /usr/local/share/boost /usr/share/swift \
  /usr/local/share/powershell /usr/local/lib/node_modules /opt/az /opt/microsoft \
  /opt/google /usr/lib/jvm 2>/dev/null || true
docker image prune --all --force >/dev/null 2>&1 || true
sudo swapoff -a 2>/dev/null && sudo rm -f /mnt/swapfile /swapfile 2>/dev/null || true
df -h / | tail -n1
