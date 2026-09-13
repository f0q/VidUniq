<p align="center"><img src="viduniq/resources/icon.png" width="96"></p>
<h1 align="center">VidUniq</h1>
<p align="center"><a href="README.md">Русский</a> · <b>English</b></p>
<p align="center">Video uniqueizer for Reels, TikTok, Shorts, Instagram, VK, Telegram and other social networks.<br>
Native macOS app (Apple Silicon) — FFmpeg is bundled, nothing to install.</p>

> A fork of [0xd5f/Video-Uniqueizer](https://github.com/0xd5f/Video-Uniqueizer) with a redesigned UI, fixed processing and a ready-to-use `.dmg`.

## Download

**[Releases → VidUniq-x.y.z-arm64.dmg](https://github.com/f0q/Video-Uniqueizer/releases/latest)** — macOS 12+, Apple Silicon (M1–M4).

1. Open the `.dmg` and drag **VidUniq** to **Applications**.
2. Launch it. macOS will show a warning on first launch — see below, this is expected.

> [!IMPORTANT]
> **"Cannot verify the developer" / "App is damaged" — this is not a virus and not a bug.**
> Apple charges $99/year for a code-signing certificate; VidUniq is a free open-source project without one.
> macOS shows the same warning for **any** unsigned app. The source is open and every build runs publicly in
> [GitHub Actions](https://github.com/f0q/Video-Uniqueizer/actions), so you can verify the `.dmg` contains exactly what is in this repository.
>
> **How to open (once):**
> - double-click **«Снять карантин.command»** ("Remove quarantine") from the disk image after copying VidUniq to Applications, **or**
> - **System Settings → Privacy & Security**, scroll down → **"Open Anyway"**, **or**
> - in Terminal: `xattr -cr /Applications/VidUniq.app`
>
> After that the app opens with a normal double-click.

## Features

- Batch processing of videos and GIFs; drag & drop files **and folders** anywhere onto the window
- 17 social-media presets (Reels/TikTok, Shorts, Instagram Post/Story/Portrait/Landscape, VK, Telegram, YouTube, Facebook, Twitter, Snapchat, Pinterest) — **all of them work**, with black bars or a blurred background
- Filters: random color shift, grayscale, sepia, invert, blur, flip, pixelate, VHS, contrast/saturation/brightness, warm/cool
- Zoom and speed — fixed or randomized within a range per file
- Image or GIF overlay in 9 positions
- Metadata stripping, audio removal
- Hardware encoding via VideoToolbox on Apple Silicon (several times faster), with automatic fallback to libx264
- Real per-file and overall progress, a **Cancel** button, per-file errors don't stop the queue
- Settings persist between launches; the window shrinks down to 880×520; follows macOS light/dark theme

<p align="center"><img src="docs/screenshot.png" width="900"></p>

## What changed compared to the original

| Before | After |
|---|---|
| PyQt5 with QSS themes; dropdown menus were unreadable on macOS | PySide6 (Qt 6), native style, system dark mode |
| Window couldn't be made shorter | Settings panel scrolls; minimum size 880×520 |
| Drag & drop only onto the list | Drop anywhere; folders expanded recursively; visual drop hint |
| Only Reels/TikTok out of 17 formats actually worked | Every preset scales/pads the frame; blurred background for any preset |
| Zoom with "Original" padded the frame to 1080×1920 | Zoom crops/pads to the source size |
| Videos without an audio track crashed ffmpeg | A silent track is added automatically |
| Progress only by file count, no cancel | Time-based progress inside each file; Cancel kills ffmpeg and removes the partial file |
| Output folder asked every run | "Next to the source in `uniq/`" or a custom folder; settings are saved |
| Python, dependencies and ffmpeg had to be installed by hand | Everything inside one `.dmg` |

## Roadmap

The project grows with interest. **Star the repo** — it's the main signal to keep going.

| Stars | What's next |
|---|---|
| ✅ now | macOS Apple Silicon `.dmg`, all presets, VideoToolbox, progress & cancel |
| **100 ⭐** | **Windows (`.exe`) and macOS Intel builds** |
| 250 ⭐ | Settings profiles (save/load per network), several variants from one video in a single run |
| 500 ⭐ | Parallel processing, result preview before running |

Ideas and bugs → [Issues](https://github.com/f0q/Video-Uniqueizer/issues). Pull requests are welcome.

## Running from source

Requires Python ≥ 3.10 and ffmpeg/ffprobe (on `PATH`, e.g. `brew install ffmpeg`, or in `vendor/ffmpeg/`).

```bash
git clone https://github.com/f0q/Video-Uniqueizer.git && cd Video-Uniqueizer
uv venv && uv pip install -e ".[dev]"     # or: python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
uv run python main.py
```

Tests (`tests/test_integration.py` runs the real ffmpeg on synthetic clips):

```bash
uv run pytest
```

## Building the `.app` and `.dmg`

```bash
scripts/fetch_ffmpeg.sh    # static ffmpeg + ffprobe (arm64) → vendor/ffmpeg/
scripts/build_mac.sh       # → dist/VidUniq.app and dist/VidUniq-<version>-arm64.dmg
```

GitHub Actions (`.github/workflows/build-macos.yml`) builds a DMG on every push to `main` and publishes a release on `v*` tags.

## Layout

```
main.py                    entry point
viduniq/app.py             QApplication, logging (~/Library/Logs/VidUniq/app.log)
viduniq/core/constants.py  presets, filters, overlay positions
viduniq/core/ffmpeg.py     ffmpeg discovery, probe, command builder, run with progress
viduniq/core/worker.py     processing queue in a QThread
viduniq/ui/                main window, file list, settings panel
scripts/                   fetch_ffmpeg.sh, make_icns.sh, build_mac.sh
VidUniq.spec               PyInstaller
```

## License and credits

The original [Video-Uniqueizer](https://github.com/0xd5f/Video-Uniqueizer) was written by [0xd5f](https://github.com/0xd5f) and published without a license; this fork is distributed on the same terms. The bundle includes static [FFmpeg](https://ffmpeg.org) binaries (GPL, built by [martin-riedl.de](https://ffmpeg.martin-riedl.de)) and [Qt/PySide6](https://www.qt.io) (LGPL).
