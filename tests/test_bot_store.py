import json

from viduniq.bot.store import PrefsStore, UserPrefs, ZOOM_CHOICES
from viduniq.core.constants import preset_by_label


def test_defaults_to_job():
    from viduniq.core.uniq import Strength
    p = UserPrefs()
    j = p.to_job()
    assert j.preset.is_original and j.blur_background is False and j.hw_encode is False
    assert j.strip_metadata is True and j.mute_audio is False
    assert j.strength == Strength.MEDIUM and j.mirror_mode == "never" and j.touch_audio is True
    assert UserPrefs(strength="strong", mirror=True).to_job().mirror_mode == "random"
    assert UserPrefs(strength="bogus").strength_enum == Strength.MEDIUM


def test_blur_only_for_presets_and_overlay_must_exist(tmp_path):
    p = UserPrefs(preset_slug="reels", blur_bg=True, overlay_path=str(tmp_path / "nope.png"))
    j = p.to_job()
    assert j.preset == preset_by_label("Reels/TikTok") and j.blur_background is True
    assert j.overlay_file is None
    (tmp_path / "logo.png").write_bytes(b"x")
    assert UserPrefs(overlay_path=str(tmp_path / "logo.png")).to_job().overlay_file == str(tmp_path / "logo.png")


def test_unknown_filters_dropped_and_labels():
    p = UserPrefs(filters=["Сепия", "Нет такого"], zoom_range=(90, 110), speed_range=None, speed=105)
    assert p.to_job().filters == ["Сепия"]
    assert p.zoom_label() == "90–110%" and p.speed_label() == "105%"


def test_store_roundtrip_and_bad_file(tmp_path):
    s = PrefsStore(str(tmp_path))
    p = UserPrefs(preset_slug="ig_post", filters=["Сепия"], zoom=100, zoom_range=(80, 120), variants=3)
    s.save(42, p)
    s2 = PrefsStore(str(tmp_path))          # новый экземпляр — читает с диска
    q = s2.get(42)
    assert q == p and q.zoom_range == (80, 120)
    (tmp_path / "7.json").write_text("{garbage", encoding="utf-8")
    assert s2.get(7) == UserPrefs()
    (tmp_path / "8.json").write_text(json.dumps({"preset_slug": "reels", "extra": 1, "zoom_range": [1]}), encoding="utf-8")
    assert s2.get(8).preset_slug == "reels" and s2.get(8).zoom_range is None


def test_reset_removes_overlay(tmp_path):
    s = PrefsStore(str(tmp_path))
    ov = tmp_path / "overlay_1.png"
    ov.write_bytes(b"x")
    s.save(1, UserPrefs(overlay_path=str(ov), variants=4))
    assert s.reset(1) == UserPrefs() and not ov.exists()


def test_zoom_choices_are_consistent():
    for label, (val, rng) in ZOOM_CHOICES.items():
        p = UserPrefs(zoom=val, zoom_range=rng)
        assert p.zoom_label() == label
