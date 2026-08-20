"""full Supervisor 按日日志测试。"""

from __future__ import annotations

from datetime import datetime

from runtimes.launchers.common import DailyAppendLogCapture, build_daily_log_path


def test_daily_log_capture_appends_to_yyyy_mm_dd_file_and_switches_at_midnight(
    tmp_path,
) -> None:
    """同一天持续 append，跨过午夜后的首条输出自动进入新日期文件。"""

    capture = DailyAppendLogCapture(
        logs_dir=tmp_path,
        component_name="backend-worker:training",
    )

    try:
        first_path = capture.append(
            b"first\n",
            now=datetime(2026, 8, 20, 23, 59, 59),
        )
        capture.append(
            b"second\n",
            now=datetime(2026, 8, 20, 23, 59, 59),
        )
        second_path = capture.append(
            b"next-day\n",
            now=datetime(2026, 8, 21, 0, 0, 0),
        )

        assert first_path.name == "backend-worker-training-20260820.log"
        assert second_path.name == "backend-worker-training-20260821.log"
        assert first_path.read_bytes() == b"first\nsecond\n"
        assert second_path.read_bytes() == b"next-day\n"
        assert capture.log_pattern == "backend-worker-training-YYYYMMDD.log"
        assert capture.tail_text() == "first\nsecond\nnext-day\n"
    finally:
        capture.close()


def test_build_daily_log_path_uses_local_calendar_date(tmp_path) -> None:
    """一次性命令也使用相同的 YYYYMMDD 命名。"""

    path = build_daily_log_path(
        tmp_path,
        "database migration",
        now=datetime(2026, 12, 31, 23, 0, 0),
    )

    assert path == tmp_path / "database-migration-20261231.log"
