from __future__ import annotations

from mitchel_pipeline import __main__


def test_selftest_flag_routes_without_starting_tk(monkeypatch):
    called = []
    monkeypatch.setattr("mitchel_pipeline.selftest.selftest", lambda: called.append(True) or 0)

    assert __main__.main(["--selftest"]) == 0
    assert called == [True]
