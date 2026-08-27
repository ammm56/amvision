"""阶段 2 Training Telemetry 性能门禁工具测试。"""

from __future__ import annotations

import json

from tests.integration.local_message_channel_stage2_telemetry_benchmark import (
    evaluate_latency_gate,
    load_stage0_telemetry_baseline,
)


def test_stage2_latency_gate_uses_one_millisecond_or_ten_percent() -> None:
    """验证低延迟与高延迟都使用文档冻结的允许回退规则。"""

    passed = evaluate_latency_gate(
        baseline={"p95": 5.0, "p99": 50.0},
        current={"p95": 6.0, "p99": 55.0},
    )
    failed = evaluate_latency_gate(
        baseline={"p95": 5.0, "p99": 50.0},
        current={"p95": 6.01, "p99": 55.01},
    )

    assert passed["passed"] is True
    assert failed["passed"] is False


def test_stage2_loader_selects_fifty_millisecond_cell(tmp_path) -> None:
    """验证比较器不会误用 10 ms 或 100 ms 的阶段 0 cell。"""

    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(
            {
                "training_telemetry": {
                    "cells": [
                        {
                            "poll_interval_seconds": 0.01,
                            "summary": {
                                "median_of_rounds_ms": {"p95": 10.0, "p99": 11.0}
                            },
                        },
                        {
                            "poll_interval_seconds": 0.05,
                            "summary": {
                                "median_of_rounds_ms": {"p95": 49.0, "p99": 51.0}
                            },
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    baseline, digest = load_stage0_telemetry_baseline(path)

    assert baseline == {"p95": 49.0, "p99": 51.0}
    assert len(digest) == 64
