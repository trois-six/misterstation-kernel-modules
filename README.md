# misterstation-kernel-modules

Linux kernel modules for the **stock** MiSTer kernel, built automatically
for every MiSTer Linux release: the V4L2/UVC camera drivers a
[Sinden light gun](https://sindenlightgun.com/) needs (the stock kernel
has no media support). The kernel itself is not changed: the modules are
built from the exact source and configuration of each stock kernel, so
they load into it as shipped, and MiSTer's Linux updates keep working.
Made for [MiSTerStation](https://github.com/trois-six/misterstation),
usable by anything that loads kernel modules on MiSTer.

## Installing and updating: the Downloader database

The modules are installed and updated like every other MiSTer file: a
[Downloader](https://github.com/MiSTer-devel/Downloader_MiSTer) database,
read by MiSTer's `downloader`/`update_all` and by MiSTerStation's
updater. Nothing is downloaded until the database is enabled. Add this to
the end of `/media/fat/downloader.ini` (MiSTerStation offers to do it,
with the [Sinden cores](https://github.com/trois-six/misterstation-sinden-cores)
database, the first time it sees a Sinden):

```ini
[misterstation_kernel_modules]
db_url = 'https://raw.githubusercontent.com/trois-six/misterstation-kernel-modules/db/db.json.zip'
```

* **db_id** `misterstation_kernel_modules` (the INI section must be the
  same; it never changes).
* **URL**: `db.json.zip` on the `db` branch of this repository, replaced
  in one commit by the workflow, only when its content changes.
* **Install path**: `linux_modules/<kernel release>/<id>/`, where
  `<kernel release>` is `uname -r` (`6.18.38-MiSTer`) and `<id>` the
  first 16 hex digits of the SHA-256 of the kernel's `/proc/version`
  (without its newline): one folder per kernel build, so modules are
  never mixed between two builds of the same version number. Each folder
  holds the `.ko` files and `manifest.json`. (`linux/` itself is
  reserved to MiSTer's Linux image: Downloader refuses any database file
  there.)
* **Which kernels**: the 3 newest kernels built (`config.json`, `keep`),
  so the modules of the kernel still running are there while a Linux
  update waits for its reboot. Downloader removes the folders of older
  kernels.
* **Download filters**: the files carry the tags `essential`,
  `linuxmodules`, `sinden` and `lightgun`: a positive filter
  (`filter = arcade console`) keeps them, as it keeps Distribution's
  essential files.

### manifest.json

```json
{
 "format": 1,
 "id": "3a53fb98bca8210a",
 "kernel_release": "6.18.38-MiSTer",
 "proc_version": "Linux version 6.18.38-MiSTer (saar@Gryphon) (...) #2 SMP Sat Sep 12 20:19:51 CST 2026",
 "vermagic": "6.18.38-MiSTer SMP mod_unload ARMv7 p2v8 ",
 "zimage_sha256": "...",
 "linux_release": "260912",
 "source_commit": "6a581bac47c32dfd2525f9874fd263cf08058610",
 "source": "https://github.com/MiSTer-devel/Linux-Kernel_MiSTer",
 "recipe": "...",
 "modules": [{"file": "mc.ko", "size": 51924, "sha256": "..."}, "..."]
}
```

`modules` is in load order (dependencies first); unload in reverse. A
loader must use a folder only when `proc_version` equals the running
kernel's `/proc/version` exactly, and should check each module's size,
SHA-256 and vermagic before loading it. By hand, as root:

```sh
d=/media/fat/linux_modules/$(uname -r)/$(tr -d '\n' </proc/version | sha256sum | cut -c1-16)
for m in $(python3 -c 'import json,sys; print(" ".join(m["file"] for m in json.load(open(sys.argv[1]))["modules"]))' "$d/manifest.json"); do
  insmod "$d/$m"
done
```

## What is built

| Module | Role |
|---|---|
| `mc.ko` | media controller |
| `videodev.ko` | V4L2 core |
| `videobuf2-common.ko`, `videobuf2-memops.ko`, `videobuf2-vmalloc.ko`, `videobuf2-v4l2.ko` | video buffers (MMAP and USERPTR) |
| `uvc.ko`, `uvcvideo.ko` | USB video class driver |

About 0.6 MB in all. The first build, for linux_release 260912 (kernel
`6.18.38-MiSTer`, id `3a53fb98bca8210a`, source commit `6a581bac4`), is
the release
[`6.18.38-MiSTer_3a53fb98bca8210a_417caced`](https://github.com/trois-six/misterstation-kernel-modules/releases/tag/6.18.38-MiSTer_3a53fb98bca8210a_417caced):
its ABI check found the 2128 built-in objects identical with and without
the media options and the 9723 exports equal to the stock image's.

Two patches (`recipe/patches/`):

* `0001-media-videobuf2-build-without-dma-buf.patch`: videobuf2 builds
  without `DMA_SHARED_BUFFER`, a bool the stock kernel lacks (selecting
  it would change the kernel): DMABUF queues and exports are refused with
  `EINVAL`, MMAP and USERPTR are unchanged. Off by default, so a normal
  kernel build is unchanged.
* `0002-media-uvcvideo-cap-compressed-payload-size.patch`: the payload
  limit of [Linux-Kernel_MiSTer PR 117](https://github.com/MiSTer-devel/Linux-Kernel_MiSTer/pull/117)
  for compressed streams, so that two guns share one USB controller.

## How it is built

`recipe/build.sh ZIMAGE_DTB` (Debian/Ubuntu packages in its header):

1. `kimage.py` reads the stock `zImage_dtb` without its sources: the
   `/proc/version` banner, the release, the vermagic, the build time, the
   embedded config (`CONFIG_IKCONFIG`) and the export tables;
2. the source commit: the kernel carries no commit id, so
   `find-commit.sh` takes the newest commit of
   [Linux-Kernel_MiSTer](https://github.com/MiSTer-devel/Linux-Kernel_MiSTer)'s
   `MiSTer-v<major>.<minor>` branch made before the build whose version
   and full defconfig equal the image's; `commits.json` pins a kernel's
   commit by hand when the search cannot tell (it records 260912's,
   `6a581bac4`, checked by hand);
3. the patches, the image's own config plus `media.config` (media options
   as modules), `check-config.sh` (only media options changed), the
   modules built against the stock image's export table;
4. `verify.py` checks every module as the kernel's loader does: vermagic
   equal to the stock kernel's, every undefined symbol exported by the
   stock kernel (or another module of the set), GPL-only exports used by
   GPL modules, namespaces imported, dependencies present; and gives the
   load order;
5. `--abi-check`: the vmlinux built from the stock config and the one
   built with the media options are made of identical objects (but the
   embedded config), and the export table built from the commit equals
   the stock image's.

## The workflow

`.github/workflows/build.yml`, daily (`41 5 * * *`), on a push of the
recipe and by hand:

* **detect**: reads the `linux` entry of
  [Distribution_MiSTer](https://github.com/MiSTer-devel/Distribution_MiSTer)'s
  database; stops when that Linux release was built with the current
  recipe (the git tree of `recipe/`).
* **build** (a new Linux release, or a recipe change): downloads the
  release (MD5 checked), reads its kernel; a kernel already built with
  this recipe (a Linux release that changed only the root file system)
  only gets the Linux release recorded; otherwise builds with
  `--abi-check` and publishes a release tagged
  `<kernel release>_<id>_<recipe>` with the modules, `manifest.json` and
  the corresponding source.
* **database**: merges the build into `index.json`, keeps the 3 newest
  kernels, generates `db.json.zip`, validates it with Downloader's own
  code (`scripts/check-db.py`), installs it with Downloader into a
  scratch directory (every file downloaded from its release with
  Downloader's MD5 and size checks), publishes it on the `db` branch
  when it changed and deletes the releases of dropped builds.
* A failed build, a patch that no longer applies to a new kernel, or a
  database that does not validate opens an issue (closed by the next
  successful run).

## Security

Kernel modules run with the kernel's privileges. The trust chain is the
same as for every file Downloader installs (MiSTer's binary, its cores,
its Linux image): the database comes over HTTPS from this repository's
`db` branch, which only this repository's workflow writes; each file is
downloaded over HTTPS from this repository's releases and checked
against the database's MD5 and size. The modules are built in the open by
that workflow from public sources; the build log, the exact source tree
and the recipe are published with every release. There is no separate
signature: anyone able to change these files on the SD card can already
replace the kernel itself (`linux/zImage_dtb`) or any script run as
root, so a signature checked on the card would not protect anything a
Downloader file does not. MiSTerStation's loader also refuses a folder
whose `proc_version` is not the running kernel's, and any module whose
size, SHA-256 (against the manifest) or vermagic does not match.

## License

GPL-2.0-only (`LICENSE`), like the kernel the modules derive from. Each
release carries its corresponding source: the patched kernel tree and
this repository's recipe at the commit that built it.
