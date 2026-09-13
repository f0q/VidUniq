from viduniq.bot.access import MAX_STRANGER_ATTEMPTS, AccessStore


def test_base_admin_and_dynamic(tmp_path):
    a = AccessStore(str(tmp_path / "access.json"), base_allowed={1}, admins={9})
    assert a.is_allowed(1) and a.is_allowed(9) and a.is_admin(9) and not a.is_admin(1)
    assert not a.is_allowed(2)
    assert a.add(2) is True and a.is_allowed(2)
    assert a.add(2) is False
    assert a.remove(2) and not a.is_allowed(2)
    assert a.remove(1) and not a.is_allowed(1)          # базовый тоже можно убрать
    a.add(1)
    b = AccessStore(str(tmp_path / "access.json"), base_allowed=set(), admins={9})   # перечитать с диска
    assert b.is_allowed(1) and not b.is_allowed(2)


def test_stranger_reply_once_then_block(tmp_path):
    a = AccessStore(str(tmp_path / "access.json"))
    assert a.stranger_attempt(5) is True                 # первая — отвечаем с ID
    for _ in range(MAX_STRANGER_ATTEMPTS - 2):
        assert a.stranger_attempt(5) is False            # дальше молчим
    assert not a.is_blocked(5)
    assert a.stranger_attempt(5) is False                # 10-я → блок
    assert a.is_blocked(5) and not a.is_allowed(5)
    assert a.stranger_attempt(5) is False
    assert a.add(5) and a.is_allowed(5) and not a.is_blocked(5)   # админ может простить
    a.block(5)
    assert not a.is_allowed(5) and 5 in a.snapshot()["blocked"]


def test_stats_and_snapshot(tmp_path):
    a = AccessStore(str(tmp_path / "access.json"), base_allowed={1, 2})
    a.touch(1, "alice", files=2)
    a.touch(1, files=1)
    a.stranger_attempt(7)
    snap = a.snapshot()
    ids = [u for u, _ in snap["allowed"]]
    assert ids == [1, 2]
    st = dict(snap["allowed"])[1]
    assert st.files == 3 and st.name == "alice" and st.last_seen > 0
    assert snap["strangers"] == {7: 1}
