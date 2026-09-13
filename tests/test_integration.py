"""Прогон реального ffmpeg на синтетических образцах. Пропускается, если ffmpeg не найден."""
import json
import os
import subprocess
import threading

import pytest

from viduniq.core import ffmpeg as ff
from viduniq.core.constants import preset_by_label, OUTPUT_PRESETS

pytestmark = pytest.mark.skipif(ff.locate("ffmpeg") is None or ff.locate("ffprobe") is None,
                                reason="ffmpeg не найден")


def _gen(path, audio=True, size="640x360", dur=2, gif=False):
    cmd = [ff.require("ffmpeg"), "-y", "-v", "error",
           "-f", "lavfi", "-i", f"testsrc=duration={dur}:size={size}:rate=25"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"]
    if gif:
        cmd += ["-t", str(dur), str(path)]
    elif str(path).endswith(".png"):
        cmd += ["-frames:v", "1", str(path)]
    else:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        cmd += ["-c:a", "aac"] if audio else []
        cmd += ["-metadata", "title=SECRET", "-t", str(dur), str(path)]
    subprocess.run(cmd, check=True)
    return str(path)


def _probe_raw(path):
    out = subprocess.run([ff.require("ffprobe"), "-v", "error", "-print_format", "json",
                          "-show_streams", "-show_format", path], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    d = tmp_path_factory.mktemp("samples")
    return {
        "audio": _gen(d / "a.mp4", audio=True),
        "silent": _gen(d / "s.mp4", audio=False),
        "gif": _gen(d / "g.gif", audio=False, size="200x150", gif=True),
        "logo": _gen(d / "logo.png", audio=False, size="64x64", dur=1),
    }


def _run(src, dst, settings):
    info = ff.probe(src)
    cmd = ff.build_command(ff.require("ffmpeg"), src, dst, info, settings)
    progress = []
    ff.run_with_progress(cmd, ff.expected_duration(info, settings), progress.append, threading.Event())
    assert progress and progress[-1] == 1.0
    return ff.probe(dst)


def test_probe(samples):
    i = ff.probe(samples["audio"])
    assert (i.width, i.height, i.has_audio) == (640, 360, True)
    assert 1.9 < i.duration < 2.2
    assert ff.probe(samples["silent"]).has_audio is False
    g = ff.probe(samples["gif"])
    assert g.is_gif and (g.width, g.height) == (200, 150)


@pytest.mark.parametrize("label", ["Reels/TikTok", "Instagram Post", "YouTube", "Pinterest"])
def test_presets_resize(samples, tmp_path, label):
    p = preset_by_label(label)
    out = _run(samples["audio"], str(tmp_path / f"{p.slug}.mp4"), ff.JobSettings(p, blur_background=(label == "YouTube")))
    assert (out.width, out.height) == (p.width, p.height)
    assert out.has_audio


def test_original_zoom_speed_filters_metadata(samples, tmp_path):
    dst = str(tmp_path / "o.mp4")
    s = ff.JobSettings(OUTPUT_PRESETS[0], zoom=120, speed=200, filters=["Сепия", "Случ. цвет (яркость/контраст/...)"],
                       strip_metadata=True)
    out = _run(samples["audio"], dst, s)
    assert (out.width, out.height) == (640, 360)
    assert 0.8 < out.duration < 1.3          # 2с / 2.0
    tags = _probe_raw(dst)["format"].get("tags", {})
    assert "title" not in {k.lower() for k in tags}


def test_silent_and_gif_inputs_and_mute(samples, tmp_path):
    out = _run(samples["silent"], str(tmp_path / "s.mp4"), ff.JobSettings(preset_by_label("Reels/TikTok"), speed=150))
    assert out.has_audio and 1.1 < out.duration < 1.6
    out = _run(samples["gif"], str(tmp_path / "g.mp4"), ff.JobSettings(preset_by_label("Instagram Post")))
    assert (out.width, out.height) == (1080, 1080) and out.has_audio and 1.7 < out.duration < 2.4
    out = _run(samples["audio"], str(tmp_path / "m.mp4"), ff.JobSettings(OUTPUT_PRESETS[0], mute_audio=True))
    assert not out.has_audio


def test_overlay_png_keeps_full_duration(samples, tmp_path):
    s = ff.JobSettings(OUTPUT_PRESETS[0], overlay_file=samples["logo"], overlay_pos="Низ-Право")
    out = _run(samples["audio"], str(tmp_path / "ov.mp4"), s)
    assert 1.9 < out.duration < 2.2


def test_cancel_stops_ffmpeg(samples, tmp_path):
    src = _gen(tmp_path / "long.mp4", audio=True, dur=20)
    info = ff.probe(src)
    dst = str(tmp_path / "long_out.mp4")
    cmd = ff.build_command(ff.require("ffmpeg"), src, dst, info, ff.JobSettings(preset_by_label("YouTube")))
    ev = threading.Event()

    def _p(frac):
        if frac > 0.05:
            ev.set()

    with pytest.raises(ff.Cancelled):
        ff.run_with_progress(cmd, info.duration, _p, ev)
    out = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
    assert not any("ffmpeg" in ln and "long_out.mp4" in ln for ln in out.splitlines())


@pytest.mark.skipif(not ff.has_videotoolbox(), reason="нет VideoToolbox")
def test_hw_encode(samples, tmp_path):
    out = _run(samples["audio"], str(tmp_path / "hw.mp4"), ff.JobSettings(preset_by_label("Reels/TikTok"), hw_encode=True))
    assert (out.width, out.height) == (1080, 1920)
