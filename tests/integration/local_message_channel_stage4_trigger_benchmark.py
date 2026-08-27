"""阶段 4 Workflow Trigger adapter 对阶段 0 正式链路的同机回归基准。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import statistics
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.contracts.ipc.local_message_profiles import (  # noqa: E402
    WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1,
)
from tests.integration.local_message_channel_stage0_benchmark import (  # noqa: E402
    _compact_json,
    _response_payload,
    _run_trigger_round,
    summarize_rounds,
)


MIB = 1024 * 1024
DEFAULT_RESPONSE_SIZES = (1024, MIB, 8 * MIB, 16 * MIB, 32 * MIB)
DEFAULT_CONCURRENCY = (1, 2, 8, 16)


@dataclass(frozen=True, slots=True)
class BenchmarkSettings:
    """固定阶段 4 的预热、进程拓扑与负载矩阵。"""

    output_path: str
    stage0_report_path: str
    rounds: int = 5
    warmup_iterations: int = 10
    inline_iterations: int = 30
    large_iterations: int = 3
    response_sizes: tuple[int, ...] = DEFAULT_RESPONSE_SIZES
    concurrency: tuple[int, ...] = DEFAULT_CONCURRENCY
    seed: int = 20260827

    def __post_init__(self) -> None:
        """拒绝不能与阶段 0 形成多轮中位数的设置。"""

        if self.rounds < 5:
            raise ValueError("阶段 4 benchmark rounds 不能小于 5")
        if self.warmup_iterations < 0:
            raise ValueError("阶段 4 warmup_iterations 不能小于 0")
        if min(self.inline_iterations, self.large_iterations) <= 0:
            raise ValueError("阶段 4 iterations 必须大于 0")
        if not self.response_sizes or min(self.response_sizes) <= 0:
            raise ValueError("阶段 4 response_sizes 必须为正数")
        if not self.concurrency or min(self.concurrency) <= 0:
            raise ValueError("阶段 4 concurrency 必须为正数")
        if max(self.response_sizes) > 32 * MIB:
            raise ValueError("公开 Workflow Trigger 结构化正文上限为 32 MiB")


def _find_stage0_cell(
    report: dict[str, object],
    *,
    response_size_bytes: int,
    concurrency: int,
) -> dict[str, object]:
    """按完整负载 identity 取得阶段 0 单元格。"""

    trigger = report.get("workflow_trigger")
    cells = trigger.get("cells") if isinstance(trigger, dict) else None
    if not isinstance(cells, list):
        raise ValueError("阶段 0 report 缺少 workflow_trigger.cells")
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        if (
            int(cell.get("response_size_bytes", -1)) == response_size_bytes
            and int(cell.get("concurrency", -1)) == concurrency
        ):
            return cell
    raise ValueError(
        "阶段 0 report 缺少 Trigger cell: "
        f"response={response_size_bytes}, concurrency={concurrency}"
    )


def _median_round_metric(rounds: list[dict[str, object]], metric: str) -> float:
    """返回多轮同名延迟指标的中位数。"""

    return round(statistics.median(float(item[metric]) for item in rounds), 6)


def _round_resource_total(round_report: dict[str, object], metric: str) -> float:
    """汇总一轮 server 和所有 client 的指定资源。"""

    resources = round_report.get("resources")
    if not isinstance(resources, dict):
        raise ValueError("benchmark round 缺少 resources")
    server = resources.get("server_process")
    clients = resources.get("client_processes")
    if not isinstance(server, dict) or not isinstance(clients, list):
        raise ValueError("benchmark round resources 格式不正确")
    total = float(server.get(metric, 0.0))
    for client in clients:
        if isinstance(client, dict):
            total += float(client.get(metric, 0.0))
    return total


def _aggregate_resources(cells: list[dict[str, object]]) -> dict[str, float]:
    """跨矩阵汇总每个 cell 的多轮中位资源。"""

    result: dict[str, float] = {}
    for metric in ("cpu_seconds", "working_set_bytes", "page_faults"):
        cell_medians: list[float] = []
        for cell in cells:
            summary = cell.get("summary")
            rounds = summary.get("rounds") if isinstance(summary, dict) else None
            if not isinstance(rounds, list):
                raise ValueError("benchmark cell 缺少 rounds")
            cell_medians.append(
                statistics.median(
                    _round_resource_total(item, metric)
                    for item in rounds
                    if isinstance(item, dict)
                )
            )
        result[metric] = round(sum(cell_medians), 6)
    return result


def _payload_incremental_working_set(
    cells: list[dict[str, object]],
) -> float:
    """扣除同并发 inline 进程基座后，汇总大正文工作集增量。

    阶段 0 到阶段 4 之间 Training/Inference 已完成独立迁移，
    spawn 子进程的绝对 import 基座已不同。使用同一报告、同并发
    1 KiB cell 作为基座，才能隔离 Trigger payload 本身的工作集。
    """

    by_identity = {
        (int(cell["response_size_bytes"]), int(cell["concurrency"])): cell
        for cell in cells
    }
    total = 0.0
    for (response_size, concurrency), cell in by_identity.items():
        if response_size <= 1024:
            continue
        baseline = by_identity.get((1024, concurrency))
        if baseline is None:
            raise ValueError(
                f"working set 增量缺少 1 KiB/c{concurrency} 基座"
            )
        current_value = _aggregate_resources([cell])["working_set_bytes"]
        baseline_value = _aggregate_resources([baseline])["working_set_bytes"]
        total += max(0.0, current_value - baseline_value)
    return round(total, 6)


def run(settings: BenchmarkSettings) -> dict[str, object]:
    """运行完整 Trigger 矩阵并执行阶段 4 回退门禁。"""

    stage0 = json.loads(Path(settings.stage0_report_path).read_text(encoding="utf-8"))
    output_path = Path(settings.output_path).resolve()
    work_root = output_path.parent / "work"
    current_cells: list[dict[str, object]] = []
    comparison_cells: list[dict[str, object]] = []
    for target_size in settings.response_sizes:
        payload = _compact_json(
            _response_payload(target_size, seed=settings.seed + target_size)
        )
        iterations = (
            settings.inline_iterations
            if target_size <= 64 * 1024
            else settings.large_iterations
        )
        for concurrency in settings.concurrency:
            print(
                f"stage4 trigger cell response={len(payload)} concurrency={concurrency}",
                flush=True,
            )
            rounds = [
                _run_trigger_round(
                    buffers_root=(
                        work_root
                        / f"{target_size}-{concurrency}-{round_index}"
                    ),
                    response_payload=payload,
                    concurrency=concurrency,
                    iterations=max(iterations, concurrency),
                    warmup_iterations=(
                        settings.warmup_iterations
                        if target_size <= 64 * 1024
                        else min(1, settings.warmup_iterations)
                    ),
                )
                for round_index in range(settings.rounds)
            ]
            summary = summarize_rounds(rounds)
            current_cell = {
                "response_size_bytes": len(payload),
                "concurrency": concurrency,
                "summary": summary,
            }
            current_cells.append(current_cell)
            baseline_cell = _find_stage0_cell(
                stage0,
                response_size_bytes=len(payload),
                concurrency=concurrency,
            )
            baseline_summary = baseline_cell.get("summary")
            baseline_medians = (
                baseline_summary.get("median_of_rounds_ms")
                if isinstance(baseline_summary, dict)
                else None
            )
            current_medians = summary["median_of_rounds_ms"]
            if not isinstance(baseline_medians, dict) or not isinstance(
                current_medians, dict
            ):
                raise ValueError("benchmark cell 缺少 median_of_rounds_ms")
            gates: dict[str, bool] = {}
            allowed: dict[str, float] = {}
            for metric in ("p95", "p99"):
                baseline_value = float(baseline_medians[metric])
                permitted = (
                    baseline_value + max(1.0, baseline_value * 0.10)
                    if target_size <= 64 * 1024
                    else baseline_value * 1.10
                )
                allowed[metric] = round(permitted, 6)
                gates[metric] = float(current_medians[metric]) <= permitted
            comparison_cells.append(
                {
                    "response_size_bytes": len(payload),
                    "concurrency": concurrency,
                    "stage0_ms": {
                        metric: float(baseline_medians[metric])
                        for metric in ("p95", "p99")
                    },
                    "current_ms": {
                        metric: float(current_medians[metric])
                        for metric in ("p95", "p99")
                    },
                    "allowed_ms": allowed,
                    "gates": gates,
                }
            )

    baseline_trigger = stage0.get("workflow_trigger")
    baseline_cells = (
        baseline_trigger.get("cells")
        if isinstance(baseline_trigger, dict)
        else None
    )
    if not isinstance(baseline_cells, list):
        raise ValueError("阶段 0 report 缺少 Workflow Trigger 资源数据")
    selected_baseline_cells = [
        _find_stage0_cell(
            stage0,
            response_size_bytes=int(cell["response_size_bytes"]),
            concurrency=int(cell["concurrency"]),
        )
        for cell in current_cells
    ]
    current_resources = _aggregate_resources(current_cells)
    baseline_resources = _aggregate_resources(selected_baseline_cells)
    current_incremental_working_set = _payload_incremental_working_set(
        current_cells
    )
    baseline_incremental_working_set = _payload_incremental_working_set(
        selected_baseline_cells
    )
    resource_gates = {
        "cpu_seconds": (
            current_resources["cpu_seconds"]
            <= baseline_resources["cpu_seconds"] * 1.10
        ),
        "payload_incremental_working_set_bytes": (
            current_incremental_working_set
            <= baseline_incremental_working_set * 1.10
        ),
        "page_faults": (
            current_resources["page_faults"]
            <= baseline_resources["page_faults"] * 1.10
        ),
    }
    latency_passed = all(
        all(bool(value) for value in cell["gates"].values())
        for cell in comparison_cells
        if isinstance(cell.get("gates"), dict)
    )
    result = {
        "format_id": "amvision.local-message-channel-stage4-trigger-benchmark.v1",
        "settings": asdict(settings),
        "transport": "local-message-workflow-trigger-mailbox.v1",
        "profile_id": WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1.profile_id,
        "cells": current_cells,
        "comparisons": comparison_cells,
        "resources": {
            "stage0": baseline_resources,
            "current": current_resources,
            "payload_incremental_working_set_bytes": {
                "stage0": baseline_incremental_working_set,
                "current": current_incremental_working_set,
            },
            "gates": resource_gates,
        },
        "latency_gates_passed": latency_passed,
        "resource_gates_passed": all(resource_gates.values()),
        "all_gates_passed": latency_passed and all(resource_gates.values()),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    encoded_bytes = encoded.encode("utf-8")
    output_path.write_bytes(encoded_bytes)
    result["report_sha256"] = hashlib.sha256(encoded_bytes).hexdigest()
    return result


def main() -> int:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(ROOT / ".tmp/local-message-channel-stage4/trigger-benchmark.json"),
    )
    parser.add_argument(
        "--stage0-report",
        default=str(ROOT / ".tmp/local-message-channel-stage0/baseline.json"),
    )
    parser.add_argument(
        "--response-size",
        type=int,
        action="append",
        dest="response_sizes",
        help="可重复指定调试用正文大小；默认运行全矩阵",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        action="append",
        dest="concurrency",
        help="可重复指定调试用并发数；默认运行全矩阵",
    )
    arguments = parser.parse_args()
    result = run(
        BenchmarkSettings(
            output_path=arguments.output,
            stage0_report_path=arguments.stage0_report,
            response_sizes=tuple(arguments.response_sizes or DEFAULT_RESPONSE_SIZES),
            concurrency=tuple(arguments.concurrency or DEFAULT_CONCURRENCY),
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
