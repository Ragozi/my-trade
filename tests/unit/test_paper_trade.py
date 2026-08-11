"""Tests for the paper trading runner process safeguards."""

from __future__ import annotations

from scripts import paper_trade


def test_instance_lock_is_held_until_handle_closes(tmp_path) -> None:
    first = paper_trade._acquire_instance_lock(str(tmp_path))
    assert first is not None
    try:
        assert paper_trade._acquire_instance_lock(str(tmp_path)) is None
    finally:
        first.close()

    second = paper_trade._acquire_instance_lock(str(tmp_path))
    assert second is not None
    second.close()
