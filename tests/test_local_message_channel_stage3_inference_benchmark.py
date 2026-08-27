"""阶段 3 Inference benchmark 契约测试。"""

from __future__ import annotations

import pytest

from tests.integration.local_message_channel_stage3_inference_benchmark import (
    BenchmarkSettings,
    _read_stage0_metric,
)


def test_stage3_benchmark_requires_five_rounds(tmp_path) -> None:
    """拒绝不足以形成多轮中位数的设置。"""

    with pytest.raises(ValueError, match="rounds"):
        BenchmarkSettings(
            output_path=str(tmp_path / "result.json"),
            stage0_report_path=str(tmp_path / "baseline.json"),
            rounds=4,
        )


def test_stage3_benchmark_reads_exact_stage0_small_response_cell() -> None:
    """门禁只能读取阶段 0 Inference 1 KiB、c1 基线。"""

    report = {
        "inference": {
            "cells": [
                {
                    "target_response_size_bytes": 1024,
                    "concurrency": 1,
                    "summary": {"median_of_rounds_ms": {"p95": 2.5, "p99": 3.0}},
                }
            ]
        }
    }
    assert _read_stage0_metric(report, "p95") == 2.5
    assert _read_stage0_metric(report, "p99") == 3.0
