"""Workflow Trigger 阶段 4 benchmark 契约测试。"""

from __future__ import annotations

import pytest

from tests.integration.local_message_channel_stage4_trigger_benchmark import (
    BenchmarkSettings,
    _aggregate_resources,
    _find_stage0_cell,
    _payload_incremental_working_set,
)


def test_stage4_benchmark_requires_five_rounds(tmp_path) -> None:
    """拒绝不足以形成多轮中位数的设置。"""

    with pytest.raises(ValueError, match="rounds"):
        BenchmarkSettings(
            output_path=str(tmp_path / "result.json"),
            stage0_report_path=str(tmp_path / "baseline.json"),
            rounds=4,
        )


def test_stage4_benchmark_reads_exact_stage0_cell() -> None:
    """基准查找必须同时匹配正文大小和并发数。"""

    expected = {
        "response_size_bytes": 1024,
        "concurrency": 8,
        "summary": {"median_of_rounds_ms": {"p95": 2.0, "p99": 3.0}},
    }
    report = {"workflow_trigger": {"cells": [expected]}}
    assert (
        _find_stage0_cell(
            report,
            response_size_bytes=1024,
            concurrency=8,
        )
        is expected
    )
    with pytest.raises(ValueError, match="concurrency=16"):
        _find_stage0_cell(
            report,
            response_size_bytes=1024,
            concurrency=16,
        )


def test_stage4_resource_aggregation_uses_per_cell_round_medians() -> None:
    """资源比较不使用单轮最好值或峰值。"""

    def round_row(value: float) -> dict[str, object]:
        return {
            "resources": {
                "server_process": {
                    "cpu_seconds": value,
                    "working_set_bytes": value * 10,
                },
                "client_processes": [
                    {
                        "cpu_seconds": value,
                        "working_set_bytes": value * 10,
                    }
                ],
            }
        }

    cells = [
        {"summary": {"rounds": [round_row(value) for value in (1, 2, 100)]}},
        {"summary": {"rounds": [round_row(value) for value in (3, 4, 100)]}},
    ]
    assert _aggregate_resources(cells) == {
        "cpu_seconds": 12.0,
        "working_set_bytes": 120.0,
        "page_faults": 0.0,
    }


def test_stage4_working_set_gate_subtracts_same_concurrency_inline_base() -> None:
    """工作集增量必须排除已迁移模块造成的 spawn import 基座。"""

    def cell(size: int, concurrency: int, working_set: float) -> dict[str, object]:
        return {
            "response_size_bytes": size,
            "concurrency": concurrency,
            "summary": {
                "rounds": [
                    {
                        "resources": {
                            "server_process": {
                                "working_set_bytes": working_set,
                            },
                            "client_processes": [],
                        }
                    }
                ]
            },
        }

    cells = [cell(1024, 1, 100), cell(1024 * 1024, 1, 140)]
    assert _payload_incremental_working_set(cells) == 40.0
