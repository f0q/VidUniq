from viduniq.core.ffmpeg import parse_progress_line


def test_parse_variants():
    assert parse_progress_line("out_time_us=2500000") == 2.5
    assert parse_progress_line("out_time_ms=2500000") == 2.5
    assert parse_progress_line("out_time=00:01:02.500000") == 62.5
    assert parse_progress_line("out_time_us=N/A") is None
    assert parse_progress_line("out_time_us=-1") == 0.0
    assert parse_progress_line("frame=12") is None
    assert parse_progress_line("progress=continue") is None
