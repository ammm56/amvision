"""阶段 5 Queue/RpcMailbox 基准契约测试。"""

from __future__ import annotations

import pytest

from tests.integration.local_message_channel_stage5_queue_benchmark import (
    BenchmarkSettings,
    _payload,
)


def test_stage5_payload_uses_exact_requested_wire_size() -> None:
    """比较双方必须接收同一精确长度 envelope bytes。"""

    for size in (1024, 6 * 1024, 64 * 1024):
        assert len(_payload(size, seed=20260827 + size)) == size


def test_stage5_settings_require_formal_five_rounds() -> None:
    """正式报告不能用少于五轮的单次结果代替。"""

    with pytest.raises(ValueError, match="rounds"):
        BenchmarkSettings(output_path="ignored.json", rounds=4)
