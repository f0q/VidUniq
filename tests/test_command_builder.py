import random

from viduniq.core import ffmpeg as ff
from viduniq.core.constants import OUTPUT_PRESETS, RANDOM_ANY_FILTER, RANDOM_COLOR_FILTER, preset_by_label

ORIG = OUTPUT_PRESETS[0]
REELS = preset_by_label("Reels/TikTok")
POST = preset_by_label("Instagram Post")


def info(**kw):
    base = dict(width=1280, height=720, duration=10.0, has_audio=True, fps=30.0)
    base.update(kw)
    return ff.MediaInfo(**base)


def fc(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_original_no_changes_keeps_even_scale():
    cmd = ff.build_command("ffmpeg", "in.mp4", "out.mp4", info(width=1281, height=721), ff.JobSettings(ORIG))
    assert "scale=1280:720[fmt]" in fc(cmd)
    assert cmd[cmd.index("[vout]") + 2] == "0:a"
    assert "-an" not in cmd
    assert "-shortest" not in cmd
    assert cmd[-1] == "out.mp4"


def test_every_preset_pads_to_its_size():
    for p in OUTPUT_PRESETS[1:]:
        cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(), ff.JobSettings(p))
        assert f"pad={p.width}:{p.height}" in fc(cmd), p.name


def test_blur_background_for_any_preset():
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(), ff.JobSettings(POST, blur_background=True))
    graph = fc(cmd)
    assert "gblur=sigma=25[bg]" in graph
    assert "crop=1080:1080" in graph
    assert "pad=" not in graph


def test_zoom_in_crops_to_target_and_zoom_out_pads():
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(), ff.JobSettings(ORIG, zoom=150))
    assert "trunc(iw*1.5000/2)*2" in fc(cmd) and "crop=1280:720" in fc(cmd)
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(), ff.JobSettings(REELS, zoom=80))
    assert "pad=1080:1920:(ow-iw)/2:(oh-ih)/2" in fc(cmd)


def test_speed_changes_video_and_audio():
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(), ff.JobSettings(ORIG, speed=150))
    assert "setpts=PTS/1.5000" in fc(cmd)
    assert "[0:a]atempo=1.5000[aout]" in fc(cmd)
    assert "[aout]" in cmd


def test_atempo_chain_splits_out_of_range():
    assert ff._atempo_chain(3.0) == ["atempo=2.0", "atempo=1.5000"]
    assert ff._atempo_chain(0.25) == ["atempo=0.5", "atempo=0.5000"]
    assert ff._atempo_chain(1.0) == []


def test_no_audio_source_gets_silent_track():
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(has_audio=False), ff.JobSettings(ORIG, speed=120))
    assert "anullsrc" in " ".join(cmd)
    assert "-shortest" in cmd
    assert cmd[cmd.index("[vout]") + 2] == "1:a"
    assert "atempo" not in fc(cmd)


def test_mute_removes_audio_entirely():
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(), ff.JobSettings(ORIG, mute_audio=True))
    assert "-an" in cmd
    assert "anullsrc" not in " ".join(cmd)


def test_gif_input_uses_silence():
    cmd = ff.build_command("ffmpeg", "in.gif", "o.mp4", info(is_gif=True, has_audio=False), ff.JobSettings(REELS))
    assert "anullsrc" in " ".join(cmd) and "-shortest" in cmd


def test_overlay_index_is_tracked(tmp_path):
    png = tmp_path / "logo.png"
    png.write_bytes(b"x")
    gif = tmp_path / "anim.gif"
    gif.write_bytes(b"x")
    # без аудио → anullsrc занимает вход 1, overlay должен стать входом 2
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(has_audio=False),
                           ff.JobSettings(ORIG, overlay_file=str(png), overlay_pos="Низ-Право"))
    assert "[2:v]format=rgba[ovl]" in fc(cmd)
    assert "overlay=x=W-w-20:y=H-h-20:shortest=1" in fc(cmd)
    assert cmd[cmd.index(str(png)) - 3:cmd.index(str(png))] == ["-loop", "1", "-i"]
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(), ff.JobSettings(ORIG, overlay_file=str(gif)))
    assert "[1:v]format=rgba[ovl]" in fc(cmd)
    assert "-stream_loop" in cmd


def test_missing_overlay_is_ignored():
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(), ff.JobSettings(ORIG, overlay_file="/nope.png"))
    assert "overlay" not in fc(cmd)


def test_filters_and_random_are_resolved():
    rng = random.Random(1)
    names = ["Сепия", RANDOM_COLOR_FILTER, RANDOM_ANY_FILTER, "Нет такого"]
    chain = ff.resolve_filters(names, rng)
    assert chain[0].startswith("colorchannelmixer")
    assert chain[1].startswith("eq=brightness=")
    assert len(chain) == 3


def test_metadata_and_codec_flags():
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(), ff.JobSettings(ORIG, strip_metadata=True))
    assert cmd[cmd.index("-map_metadata") + 1] == "-1"
    assert "libx264" in cmd
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info(), ff.JobSettings(ORIG, strip_metadata=False, hw_encode=True))
    assert "-map_metadata" not in cmd
    assert "h264_videotoolbox" in cmd


def test_expected_duration_accounts_for_speed():
    assert ff.expected_duration(info(duration=10), ff.JobSettings(ORIG, speed=200)) == 5.0
