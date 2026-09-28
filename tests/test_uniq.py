import random
from dataclasses import replace

from viduniq.core import ffmpeg as ff
from viduniq.core.batch import prepare_job
from viduniq.core.constants import OUTPUT_PRESETS, preset_by_label
from viduniq.core.uniq import (PROFILES, Strength, UniqParams, audio_chain, describe, random_metadata,
                               roll, rotation_scale, video_chain)


def test_roll_deterministic_and_within_profile():
    for st in (Strength.SOFT, Strength.MEDIUM, Strength.STRONG):
        p1 = roll(st, random.Random(7))
        p2 = roll(st, random.Random(7))
        assert p1 == p2
        prof = PROFILES[st]
        for _ in range(50):
            p = roll(st, random.Random())
            assert prof["zoom"][0] <= p.zoom <= prof["zoom"][1]
            assert prof["speed"][0] <= p.speed <= prof["speed"][1]
            assert prof["rotate"][0] <= abs(p.rotate_deg) <= prof["rotate"][1] + 1e-9
            assert p.trim_start == 0.0 and prof["trim"][0] <= p.trim_end <= prof["trim"][1] + 1e-9
            assert prof["contrast"][0] - 1e-9 <= p.contrast <= prof["contrast"][1] + 1e-9
            assert prof["pitch"][0] - 1e-9 <= p.audio_pitch <= prof["pitch"][1] + 1e-9
            assert prof["crf"][0] <= p.crf <= prof["crf"][1]
            assert p.mirror is False
            assert "creation_time" in p.metadata and "v:encoder" in p.metadata


def test_fps_never_drops_below_source():
    from viduniq.core.uniq import pick_fps
    for src in (23.98, 24, 25, 29.97, 30, 50, 60, 120):
        for seed in range(60):
            f = pick_fps(src, random.Random(seed))
            assert f is None or f >= src - 0.05, (src, f)
            assert f is None or f <= src * 1.25
    assert pick_fps(30, random.Random(1), allowed=False) is None
    assert pick_fps(0, random.Random(1)) is None
    # у 30 fps подходящих кандидатов нет — частота остаётся исходной
    assert {pick_fps(30, random.Random(i)) for i in range(50)} == {None}
    assert {pick_fps(24, random.Random(i)) for i in range(200)} - {None}


def test_roll_keeps_high_fps():
    for seed in range(50):
        assert roll(Strength.STRONG, random.Random(seed), source_fps=60.0).fps is None
        f = roll(Strength.MEDIUM, random.Random(seed), source_fps=24.0).fps
        assert f is None or f >= 24


def test_profiles_are_monotonic():
    for key in ("zoom", "rotate", "trim", "noise"):
        assert PROFILES[Strength.SOFT][key][1] <= PROFILES[Strength.MEDIUM][key][1] <= PROFILES[Strength.STRONG][key][1]


def test_trim_modes():
    rng = random.Random(1)
    end = roll(Strength.MEDIUM, random.Random(1), trim_mode="end")
    start = roll(Strength.MEDIUM, random.Random(1), trim_mode="start")
    off = roll(Strength.MEDIUM, random.Random(1), trim_mode="off")
    assert end.trim_end > 0 and end.trim_start == 0
    assert start.trim_start > 0 and start.trim_end == 0
    assert off.trim_start == 0 and off.trim_end == 0
    assert "обрезка конца" in describe(end) and "обрезка начала" in describe(start)


def test_trim_applied_as_input_options():
    info = _info(duration=10.0)
    job = ff.JobSettings(OUTPUT_PRESETS[0], strength=Strength.MEDIUM, trim_mode="end")
    job = prepare_job(job, None, None, random.Random(3), info)
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info, job)
    i = cmd.index("-i")
    assert "-ss" not in cmd and cmd[i - 2] == "-t"                       # начало не трогаем
    assert abs(float(cmd[i - 1]) - (10.0 - job.uniq.trim_end)) < 0.01
    job = replace(job, uniq=None, trim_mode="start")
    job = prepare_job(job, None, None, random.Random(3), info)
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", info, job)
    assert cmd[cmd.index("-i") - 2] == "-ss"
    # короткий ролик не режем вовсе
    short = _info(duration=1.2)
    job = prepare_job(ff.JobSettings(OUTPUT_PRESETS[0], strength=Strength.STRONG, trim_mode="end"),
                      None, None, random.Random(3), short)
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", short, job)
    assert "-t" not in cmd and "-ss" not in cmd
    assert abs(ff.expected_duration(short, job) - 1.2 / (job.uniq.speed / 100)) < 1e-6


def test_roll_options():
    p = roll(Strength.MEDIUM, random.Random(1), mirror_mode="always", touch_audio=False)
    assert p.mirror and p.audio_pitch == 1.0 and p.audio_gain_db == 0.0 and p.audio_eq_db == 0.0
    off = roll(Strength.OFF, random.Random(1))
    assert off.zoom == 100 and off.speed == 100 and off.rotate_deg == 0 and off.metadata


def test_random_metadata_plausible():
    import datetime as dt
    now = dt.datetime(2026, 9, 13, tzinfo=dt.timezone.utc)
    m = random_metadata(random.Random(3), now)
    when = dt.datetime.strptime(m["creation_time"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.timezone.utc)
    assert now - dt.timedelta(days=61) < when < now
    assert m["v:encoder"] and m["brand"] in ("isom", "mp42") and m["a:handler_name"]


def test_video_and_audio_chain_strings():
    p = UniqParams(rotate_deg=1.0, brightness=0.02, contrast=1.03, hue_deg=-2, noise=5, vignette=0.2, sharpen=0.3,
                   audio_pitch=1.02, audio_gain_db=-1.5, audio_eq_db=2.0)
    v = video_chain(p, 1080, 1920)
    assert v[0].startswith("scale=trunc(iw*") and v[1].startswith("rotate=0.01745") and v[2] == "crop=1080:1920"
    assert "eq=brightness=0.020:contrast=1.030" in v and "hue=h=-2.00" in v
    assert "noise=alls=5:allf=t" in v and "vignette=angle=0.200" in v and v[-1].startswith("unsharp=5:5:0.30")
    a = audio_chain(p)
    assert a[:3] == ["asetrate=44982", "aresample=44100", "atempo=0.98039"]
    assert "volume=-1.5dB" in a and "bass=g=2.0" in a
    assert video_chain(UniqParams(), 100, 100) == [] and audio_chain(UniqParams()) == []


def test_rotation_scale_covers_frame():
    import math
    for w, h, deg in ((1080, 1920, 2.0), (1920, 1080, 1.0), (1000, 1000, 2.0), (2560, 1080, 2.0)):
        s = rotation_scale(deg, w, h)
        a = math.radians(deg)
        # повёрнутый увеличенный кадр должен вписывать исходный прямоугольник: проверяем крайнюю точку
        need_w = w * math.cos(a) + h * math.sin(a)
        need_h = w * math.sin(a) + h * math.cos(a)
        assert s * w >= need_w - 1e-6 and s * h >= need_h - 1e-6


def test_describe_readable():
    p = roll(Strength.STRONG, random.Random(5))
    d = describe(p)
    assert "режим: сильная" in d and "zoom" in d and "метаданные подменены" in d
    assert describe(UniqParams()) == "без изменений"


def _info(**kw):
    base = dict(width=1280, height=720, duration=10.0, has_audio=True, fps=30.0)
    base.update(kw)
    return ff.MediaInfo(**base)


def test_build_command_with_uniq():
    job = ff.JobSettings(preset_by_label("Reels/TikTok"), strength=Strength.MEDIUM, zoom=150, speed=50)
    job = prepare_job(job, None, None, random.Random(11), _info())
    u = job.uniq
    assert u is not None and u.strength == Strength.MEDIUM
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", _info(), job)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert cmd[cmd.index("-i") - 2:cmd.index("-i")] == ["-t", f"{10.0 - u.trim_end:.2f}"]
    assert f"trunc(iw*{u.zoom / 100:.4f}/2)*2" in fc              # zoom из режима, а не ручной 150
    assert f"setpts=PTS/{u.speed / 100:.4f}" in fc
    assert "rotate=" in fc and "[unq]" in fc
    assert "asetrate=" in fc
    assert cmd[cmd.index("-crf") + 1] == str(u.crf) and cmd[cmd.index("-g") + 1] == str(u.gop)
    assert "-map_metadata" in cmd and f"creation_time={u.metadata['creation_time']}" in cmd
    assert cmd[cmd.index("-metadata:s:v:0") + 1] == f"handler_name={u.metadata['v:handler_name']}"
    assert cmd[cmd.index("-brand") + 1] == u.metadata["brand"] and "+bitexact" in cmd
    assert abs(ff.expected_duration(_info(), job) - (10 - u.trim_end) / (u.speed / 100)) < 1e-6


def test_manual_mode_keeps_ranges_and_swaps_metadata():
    job = ff.JobSettings(OUTPUT_PRESETS[0], zoom=100, speed=100, strip_metadata=True)
    job = prepare_job(job, (110, 110), (90, 90), random.Random(2), _info())
    assert (job.zoom, job.speed) == (110, 90)
    assert job.uniq is not None and job.uniq.strength == Strength.OFF and job.uniq.metadata
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", _info(), job)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "trunc(iw*1.1000/2)*2" in fc and "setpts=PTS/0.9000" in fc and "rotate" not in fc
    assert "-ss" not in cmd
    job2 = prepare_job(ff.JobSettings(OUTPUT_PRESETS[0], strip_metadata=False), None, None, random.Random(2), _info())
    assert job2.uniq is None


def test_mirror_and_no_trim_for_short_clip():
    job = ff.JobSettings(OUTPUT_PRESETS[0], strength=Strength.SOFT, mirror_mode="always")
    job = prepare_job(job, None, None, random.Random(4), _info(duration=1.0))
    cmd = ff.build_command("ffmpeg", "in.mp4", "o.mp4", _info(duration=1.0), job)
    assert "hflip" in cmd[cmd.index("-filter_complex") + 1]
    assert "-ss" not in cmd and "-t" not in cmd
