from __future__ import annotations

import threading
import time

import pytest

from mitchel_pipeline.run_control import RunCancelled, RunControl


def test_checkpoint_waits_for_resume():
    control = RunControl()
    control.pause()
    passed = threading.Event()
    worker = threading.Thread(target=lambda: (control.checkpoint(), passed.set()))
    worker.start()
    time.sleep(0.05)
    assert not passed.is_set()

    control.resume()
    worker.join(timeout=1)
    assert passed.is_set()


def test_cancel_releases_a_paused_checkpoint():
    control = RunControl()
    control.pause()
    control.cancel()

    with pytest.raises(RunCancelled):
        control.checkpoint()
