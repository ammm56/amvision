"""Workflow Trigger 传输性能门禁工具测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.integration.workflow_trigger_transport_benchmark import (
    _collect_lifecycle_counts,
    _distribution,
    _read_route_generation,
    _split_iterations,
    evaluate_cell,
    evaluate_health_recovery,
    load_settings,
)


def test_benchmark_settings_require_exact_raw_bgr24_size(tmp_path: Path) -> None:
    """raw case 必须准确描述连续 HWC BGR24，不能用错误尺寸污染基准。"""

    raw_path = tmp_path / "image.bgr24"
    raw_path.write_bytes(bytes(range(18)))
    config_path = tmp_path / "benchmark.json"
    config_path.write_text(
        json.dumps(
            {
                "zeromq_trigger_source_ids": ["zero-1"],
                "shared_memory_trigger_source_ids": ["shared-1"],
                "soak_iterations": 0,
                "image_cases": [
                    {
                        "name": "raw",
                        "size_class": "1080p",
                        "path": raw_path.name,
                        "baseline_mode": "bgr24",
                        "candidate_mode": "bgr24-direct",
                        "media_type": "image/raw",
                        "width": 3,
                        "height": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(config_path, None)

    assert settings.image_cases[0].path == raw_path.resolve()
    assert settings.image_cases[0].candidate_mode == "bgr24-direct"
    raw_path.write_bytes(b"invalid")
    with pytest.raises(ValueError, match=r"size=width\*height\*3"):
        load_settings(config_path, None)


def test_performance_gate_applies_20mp_data_plane_and_tail_threshold() -> None:
    """20MP 数据面必须改善 40%，端到端 P99 和长尾仍独立受控。"""

    passing = {
        "case": "20mp-raw",
        "size_class": "20mp",
        "concurrency": 1,
        "round": 1,
        "baseline": {
            "latency_ms": {"p50": 100.0, "p95": 120.0, "p99": 130.0},
            "transport_overhead_ms": {"p50": 50.0, "p95": 70.0, "p99": 80.0},
        },
        "candidate": {
            "latency_ms": {"p50": 75.0, "p95": 90.0, "p99": 100.0},
            "transport_overhead_ms": {"p50": 25.0, "p95": 40.0, "p99": 50.0},
        },
    }
    failing = {
        **passing,
        "candidate": {
            "latency_ms": {"p50": 90.0, "p95": 110.0, "p99": 150.0},
            "transport_overhead_ms": {"p50": 35.0, "p95": 50.0, "p99": 80.0},
        },
    }

    assert evaluate_cell(passing) == []
    failures = evaluate_cell(failing)
    assert any("P99" in item for item in failures)
    assert any("40%" in item for item in failures)


def test_performance_gate_rejects_20mp_without_workflow_timing() -> None:
    """20MP 门禁不能退回用端到端延迟冒充图片数据面延迟。"""

    cell = {
        "case": "20mp-raw",
        "size_class": "20mp",
        "concurrency": 1,
        "round": 1,
        "baseline": {"latency_ms": {"p50": 100.0, "p95": 120.0, "p99": 130.0}},
        "candidate": {"latency_ms": {"p50": 70.0, "p95": 80.0, "p99": 90.0}},
    }

    assert any("缺少逐请求 Workflow timing" in item for item in evaluate_cell(cell))


def test_health_recovery_detects_only_increased_lifecycle_counts() -> None:
    """测试结束后的在途资源只能回到或低于基线，不能新增泄漏。"""

    before = {"mailbox": {"pending_request_count": 0, "used_count": 1}}
    recovered = {"mailbox": {"pending_request_count": 0, "used_count": 0}}
    leaked = {"mailbox": {"pending_request_count": 1, "used_count": 1}}

    assert evaluate_health_recovery(before, recovered) == []
    assert evaluate_health_recovery(before, leaked) == [
        "health 生命周期计数未恢复：mailbox.pending_request_count 0 -> 1"
    ]
    assert _collect_lifecycle_counts(leaked)["mailbox.used_count"] == 1


def test_health_recovery_ignores_monotonic_counters_and_high_water_marks() -> None:
    """累计 overflow 和 max-used 只增不减，不能当成未回收 gauge。"""

    before = {
        "router": {"active_client_channel_overflow_count": 1},
        "pool": {"max_used_count": 2, "used_count": 0},
    }
    after = {
        "router": {"active_client_channel_overflow_count": 5},
        "pool": {"max_used_count": 8, "used_count": 0},
    }

    assert evaluate_health_recovery(before, after) == []


def test_distribution_uses_linear_interpolation() -> None:
    """Python 聚合分位数与 .NET probe 使用相同线性插值。"""

    assert _distribution([10.0, 20.0, 30.0, 40.0]) == {
        "min": 10.0,
        "mean": 25.0,
        "p50": 25.0,
        "p95": 38.5,
        "p99": 39.7,
        "max": 40.0,
    }


def test_split_iterations_preserves_exact_total_without_sample_trimming() -> None:
    """并发 worker 必须精确分摊总量，不能排序后裁掉最高延迟样本。"""

    split = _split_iterations(1_000, 8)

    assert sum(split) == 1_000
    assert max(split) - min(split) <= 1
    assert split == (125, 125, 125, 125, 125, 125, 125, 125)
    assert _split_iterations(10, 3) == (4, 3, 3)


def test_route_generation_comes_from_formal_nested_adapter_health() -> None:
    """基准工具不能从持久化摘要顶层猜测 mailbox route generation。"""

    assert _read_route_generation(
        {
            "health_summary": {
                "supervisor": {
                    "adapter_health": {"route_generation": 9},
                }
            }
        }
    ) == 9
    assert _read_route_generation({"health_summary": {}}) == 0
