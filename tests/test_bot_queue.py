"""Очередь без Telegram: реальный ffmpeg на синтетике."""
import asyncio
import shutil
import subprocess

import pytest

from viduniq.bot.queue import ProcessingQueue, Task
from viduniq.bot.store import UserPrefs
from viduniq.core import ffmpeg as ff

pytestmark = pytest.mark.skipif(ff.locate("ffmpeg") is None, reason="ffmpeg не найден")


def _gen(path, dur=2, size="320x240"):
    subprocess.run([ff.require("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=duration={dur}:size={size}:rate=25",
                    "-f", "lavfi", "-i", f"sine=duration={dur}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-t", str(dur), str(path)], check=True)
    return str(path)


async def _run_queue(tmp_path, tasks, interval=0.2, parallel=1):
    q = ProcessingQueue(str(tmp_path / "tmp"), max_parallel=parallel, progress_interval=interval)
    progress_calls, done = [], []

    async def on_progress(t):
        progress_calls.append((t.id, t.variant, t.progress))

    async def on_done(t):
        done.append(t)

    q.on_progress, q.on_done = on_progress, on_done
    q.start()
    for t in tasks:
        q.submit(t)
    await asyncio.gather(*(t.done_event.wait() for t in tasks))
    await q.stop()
    return q, progress_calls, done


async def test_variants_and_cleanup(tmp_path):
    src = _gen(tmp_path / "in.mp4")
    prefs = UserPrefs(preset_slug="ig_post", variants=2, zoom_range=(90, 110))
    t = Task(user_id=1, chat_id=1, src_path=src, src_name="in.mp4", prefs=prefs)
    seen = {}

    q = ProcessingQueue(str(tmp_path / "tmp"), progress_interval=0.2)

    async def on_done(task):
        for out in task.outputs:
            seen[out] = ff.probe(out)
    q.on_done = on_done
    q.start()
    q.submit(t)
    await t.done_event.wait()
    await q.stop()

    assert t.error is None and len(t.outputs) == 2
    assert all((i.width, i.height) == (1080, 1080) for i in seen.values())
    assert not (tmp_path / "tmp" / t.id).exists()      # результаты удалены после on_done
    assert not (tmp_path / "in.mp4").exists()          # исходник удалён


async def test_cancel_running_and_pending(tmp_path):
    long_src = _gen(tmp_path / "long.mp4", dur=30, size="1280x720")
    src2 = _gen(tmp_path / "second.mp4")
    prefs = UserPrefs(preset_slug="youtube")
    t1 = Task(user_id=5, chat_id=5, src_path=long_src, src_name="long.mp4", prefs=prefs)
    t2 = Task(user_id=5, chat_id=5, src_path=src2, src_name="second.mp4", prefs=prefs)
    q = ProcessingQueue(str(tmp_path / "tmp"), progress_interval=0.2)

    async def on_progress(t):
        if t.progress > 0.02:
            q.cancel_user(5)
    q.on_progress = on_progress
    q.start()
    q.submit(t1)
    q.submit(t2)
    assert q.position(t2) == 2 or q.position(t2) == 1
    await asyncio.wait_for(asyncio.gather(t1.done_event.wait(), t2.done_event.wait()), 60)
    await q.stop()
    assert t1.error == "Отменено" and t2.error == "Отменено"
    assert not _ffmpeg_running("long.mp4")


def _ffmpeg_running(needle: str) -> bool:
    """Ищет живой процесс ffmpeg с needle в аргументах (через /proc или ps — без pgrep)."""
    import os
    if os.path.isdir("/proc"):
        for pid in os.listdir("/proc"):
            if pid.isdigit():
                try:
                    with open(f"/proc/{pid}/cmdline", "rb") as f:
                        cmd = f.read()
                    if b"ffmpeg" in cmd and needle.encode() in cmd:
                        return True
                except OSError:
                    pass
        return False
    out = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
    return any("ffmpeg" in ln and needle in ln for ln in out.splitlines())


async def test_error_does_not_break_queue(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    good = _gen(tmp_path / "good.mp4")
    prefs = UserPrefs()
    t1 = Task(user_id=1, chat_id=1, src_path=str(bad), src_name="bad.mp4", prefs=prefs)
    t2 = Task(user_id=1, chat_id=1, src_path=good, src_name="good.mp4", prefs=prefs)
    q, calls, done = await _run_queue(tmp_path, [t1, t2])
    assert t1.error and not t1.outputs
    assert t2.error is None and len(t2.outputs) == 1
    assert [d.id for d in done] == [t1.id, t2.id]


async def test_per_user_limit(tmp_path):
    q = ProcessingQueue(str(tmp_path / "tmp"), max_pending_per_user=2)
    for i in range(2):
        q.submit(Task(user_id=9, chat_id=9, src_path="x", src_name="x", prefs=UserPrefs()))
    with pytest.raises(RuntimeError):
        q.submit(Task(user_id=9, chat_id=9, src_path="x", src_name="x", prefs=UserPrefs()))
    assert q.pending_for(9) == 2 and q.pending_for(10) == 0
