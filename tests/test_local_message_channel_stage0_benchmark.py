"""LocalMessage Channel 阶段 0 测量工具回归测试。"""

from __future__ import annotations

from dataclasses import asdict, fields
import json
from pathlib import Path
import sqlite3

import pytest

from backend.contracts.ipc.local_message_profiles import (
    INFERENCE_RPC_PROFILE_V1,
    RPC_ENVELOPE_RESERVE_BYTES,
    RPC_PUBLIC_RESPONSE_CAPACITY_BYTES,
    TRAINING_TELEMETRY_EVENT_PROFILE_V1,
    WORKFLOW_TRIGGER_RPC_PROFILE_V1,
)
from tests.integration.local_message_channel_stage0_benchmark import (
    BenchmarkSettings,
    _run_inference_round,
    _run_queue_round,
    _run_telemetry_round,
    _run_trigger_round,
    build_payload_inventory,
    collect_observed_local_payload_sizes,
    collect_current_contracts,
    summarize_rounds,
    summarize_samples,
)


def test_stage0_settings_require_five_rounds(tmp_path: Path) -> None:
    """正式基线不能用单轮偶然结果冻结 profile。"""

    settings = BenchmarkSettings(output_path=tmp_path / "result.json", rounds=4)

    with pytest.raises(ValueError, match="至少需要 5 轮"):
        settings.validate()


def test_stage0_summary_uses_median_of_round_percentiles() -> None:
    """阶段 0 裁决使用多轮中位数，不合并后裁剪尾延迟。"""

    assert summarize_samples([1.0, 2.0, 3.0, 4.0])["p95"] == 3.85
    rounds = [
        {"mean": value, "p50": value, "p95": value, "p99": value, "max": value}
        for value in (9.0, 1.0, 7.0, 3.0, 5.0)
    ]

    summary = summarize_rounds(rounds)

    assert summary["round_count"] == 5
    assert summary["median_of_rounds_ms"] == {
        "mean": 5.0,
        "p50": 5.0,
        "p95": 5.0,
        "p99": 5.0,
        "max": 5.0,
    }


def test_stage0_payload_inventory_uses_current_public_shapes() -> None:
    """profile 输入分布必须包含 Trigger、五类推理和训练遥测。"""

    inventory = build_payload_inventory()
    samples = inventory["samples"]

    assert inventory["codec"] == "pydantic-core-compact-utf8-json"
    assert samples["trigger.prepare"]["serialized_size_bytes"] > 0
    assert samples["trigger.request"]["serialized_size_bytes"] > 0
    for task_type in ("classification", "detection", "segmentation", "pose", "obb"):
        assert samples[f"inference.{task_type}.request"]["serialized_size_bytes"] > 0
    assert samples["training.telemetry"]["serialized_size_bytes"] < 4096
    assert (
        samples["inference.segmentation-normal-100x100.response"][
            "serialized_size_bytes"
        ]
        < INFERENCE_RPC_PROFILE_V1.inline_response_capacity_bytes
    )
    assert (
        samples["inference.segmentation-dense-100x1000.response"][
            "serialized_size_bytes"
        ]
        > INFERENCE_RPC_PROFILE_V1.inline_response_capacity_bytes
    )


def test_stage0_contract_inventory_keeps_domain_admission_outside_profile() -> None:
    """transport profile 不得重新吸收推理或 Workflow 的执行并发。"""

    contracts = collect_current_contracts()

    assert contracts["workflow_trigger"]["descriptor_count"] == 128
    assert contracts["inference"]["overflow_page_count"] == 256
    assert "max_concurrent_requests" not in contracts["inference"]
    assert contracts["training_telemetry"]["min_publish_interval_seconds"] == 0.1


def test_stage0_profiles_keep_capacity_and_domain_policy_separate() -> None:
    """冻结 profile 覆盖 32 MiB 正文与 envelope，且不吸收业务并发。"""

    for profile in (WORKFLOW_TRIGGER_RPC_PROFILE_V1, INFERENCE_RPC_PROFILE_V1):
        assert profile.max_response_bytes == (
            RPC_PUBLIC_RESPONSE_CAPACITY_BYTES + RPC_ENVELOPE_RESERVE_BYTES
        )
        assert profile.overflow_capacity_bytes == 128 * 1024 * 1024
        assert (
            profile.max_overflow_pages_per_response
            * profile.overflow_page_capacity_bytes
            >= profile.max_response_bytes
        )
        assert "max_concurrent_requests" not in {
            field.name for field in fields(profile)
        }
    assert WORKFLOW_TRIGGER_RPC_PROFILE_V1.inline_response_capacity_bytes == 64 * 1024
    assert INFERENCE_RPC_PROFILE_V1.inline_response_capacity_bytes == 256 * 1024
    assert TRAINING_TELEMETRY_EVENT_PROFILE_V1.payload_capacity_bytes == 4096
    assert TRAINING_TELEMETRY_EVENT_PROFILE_V1.poll_interval_seconds == 0.05
    assert TRAINING_TELEMETRY_EVENT_PROFILE_V1.scan_interval_seconds == 0.1


def test_stage0_profile_fixture_matches_frozen_code() -> None:
    """审计 fixture 与代码常量必须逐字段一致。"""

    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "local_message_channel_profiles.v1.fixture.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    profiles = fixture["profiles"]

    assert profiles[WORKFLOW_TRIGGER_RPC_PROFILE_V1.profile_id] == {
        key: value
        for key, value in asdict(WORKFLOW_TRIGGER_RPC_PROFILE_V1).items()
        if key != "profile_id"
    }
    assert profiles[INFERENCE_RPC_PROFILE_V1.profile_id] == {
        key: value
        for key, value in asdict(INFERENCE_RPC_PROFILE_V1).items()
        if key != "profile_id"
    }
    assert profiles[TRAINING_TELEMETRY_EVENT_PROFILE_V1.profile_id] == {
        key: value
        for key, value in asdict(TRAINING_TELEMETRY_EVENT_PROFILE_V1).items()
        if key != "profile_id"
    }


def test_stage0_observed_payload_collector_records_only_lengths(
    tmp_path: Path,
) -> None:
    """本地开发数据观测只输出统计值，不复制业务 JSON。"""

    database_path = tmp_path / "amvision.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE workflow_preview_runs(outputs_json JSON);
            CREATE TABLE workflow_runs(input_payload_json JSON, outputs_json JSON);
            CREATE TABLE tasks(result_json JSON);
            CREATE TABLE queue_outbox_messages(payload_json JSON);
            INSERT INTO workflow_preview_runs VALUES ('{"value":"stage0"}');
            INSERT INTO tasks VALUES ('{"result":true}');
            """
        )
        connection.commit()
    finally:
        connection.close()
    queue_root = tmp_path / "queue"
    queue_file = queue_root / "workflow-runtime" / "ready" / "message.json"
    queue_file.parent.mkdir(parents=True)
    queue_file.write_text('{"payload":"stage0"}', encoding="utf-8")

    observed = collect_observed_local_payload_sizes(
        database_path=database_path,
        queue_root=queue_root,
    )

    preview = observed["database"]["sources"]["workflow_preview_runs.outputs_json"]
    queue = observed["file_queue"]["queues"]["workflow-runtime"]
    assert preview["sample_count"] == 1
    assert preview["max"] == len('{"value":"stage0"}')
    assert queue["sample_count"] == 1
    assert '{"value":"stage0"}' not in str(observed)
    assert '{"payload":"stage0"}' not in str(observed)


def test_stage0_current_transport_rounds_are_isolated_and_lossless(
    tmp_path: Path,
) -> None:
    """四条现状链路必须能独立形成完整 latency 样本。"""

    trigger = _run_trigger_round(
        buffers_root=tmp_path / "trigger",
        response_payload=b"{}",
        concurrency=1,
        iterations=1,
        warmup_iterations=0,
    )
    inference = _run_inference_round(
        buffers_root=tmp_path / "inference",
        result_value="stage0",
        concurrency=1,
        iterations=1,
        warmup_iterations=0,
    )
    telemetry = _run_telemetry_round(
        root=tmp_path / "telemetry",
        iterations=3,
        poll_interval_seconds=0.01,
    )
    queue_object = _run_queue_round(
        mode="python-object-pickle",
        value="stage0",
        concurrency=1,
        iterations=2,
        warmup_iterations=0,
    )
    queue_bytes = _run_queue_round(
        mode="compact-json-bytes",
        value="stage0",
        concurrency=1,
        iterations=2,
        warmup_iterations=0,
    )

    assert trigger["sample_count"] == 1
    assert inference["sample_count"] == 1
    assert telemetry["sample_count"] == 3
    assert queue_object["sample_count"] == 2
    assert queue_bytes["sample_count"] == 2
