"""使用 1,000/10,000 个真实文件验证保留清理耗时和进程资源。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import gc
import json
import os
from pathlib import Path
import tempfile
from time import perf_counter

import psutil

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.core_nodes.io.output.storage.storage_retention_cleanup import (
    CORE_NODE_SPEC,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeRuntimeRegistry,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class BenchmarkResult:
    """保存一个规模用例的真实执行指标。"""

    case: str
    initial_file_count: int
    expected_deleted_count: int
    deleted_file_count: int
    remaining_file_count: int
    node_duration_ms: int
    wall_duration_ms: float
    rss_delta_bytes: int
    private_delta_bytes: int
    handle_delta: int | None
    state: str
    has_more: bool


@dataclass(frozen=True)
class SoakResult:
    """保存重复扫描的资源稳定性指标。"""

    case: str
    iterations: int
    file_count: int
    total_wall_duration_ms: float
    average_wall_duration_ms: float
    rss_delta_bytes: int
    private_delta_bytes: int
    handle_delta: int | None


def main() -> None:
    """创建隔离文件，执行真实 Workflow 图并输出 JSON 指标。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--temp-root", type=Path, default=Path(".tmp"))
    parser.add_argument("--soak-iterations", type=int, default=10)
    args = parser.parse_args()
    if args.soak_iterations <= 0:
        parser.error("--soak-iterations 必须大于 0")
    args.temp_root.mkdir(parents=True, exist_ok=True)
    age_result = _run_age_case(
        args.temp_root,
        file_count=1_000,
        expired_count=600,
    )
    count_result, soak_result = _run_count_case(
        args.temp_root,
        file_count=10_000,
        keep_count=1_000,
        soak_iterations=args.soak_iterations,
    )
    print(
        json.dumps(
            {
                "cases": [asdict(age_result), asdict(count_result)],
                "soak": asdict(soak_result),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _run_age_case(
    temp_root: Path,
    *,
    file_count: int,
    expired_count: int,
) -> BenchmarkResult:
    """验证 1,000 文件的按时间删除。"""

    with tempfile.TemporaryDirectory(
        prefix="storage-retention-age-",
        dir=temp_root,
    ) as temp_dir:
        root = Path(temp_dir).resolve()
        target = root / "results"
        target.mkdir()
        now = datetime.now(tz=timezone.utc)
        for index in range(file_count):
            modified_time = (
                now - timedelta(days=3, seconds=file_count - index)
                if index < expired_count
                else now - timedelta(minutes=5, seconds=file_count - index)
            )
            _create_file(target / f"result-{index:05d}.dat", modified_time)
        return _execute_case(
            case="age-1000",
            root=root,
            target=target,
            parameters={
                "retention_policy": "age",
                "retention_value": 1,
                "retention_unit": "day",
                "delete_limit": file_count,
            },
            initial_file_count=file_count,
            expected_deleted_count=expired_count,
        )


def _run_count_case(
    temp_root: Path,
    *,
    file_count: int,
    keep_count: int,
    soak_iterations: int,
) -> tuple[BenchmarkResult, SoakResult]:
    """验证 10,000 文件的最大数量删除。"""

    with tempfile.TemporaryDirectory(
        prefix="storage-retention-count-",
        dir=temp_root,
    ) as temp_dir:
        root = Path(temp_dir).resolve()
        target = root / "results"
        target.mkdir()
        now = datetime.now(tz=timezone.utc)
        for index in range(file_count):
            _create_file(
                target / f"result-{index:05d}.dat",
                now - timedelta(seconds=file_count - index),
            )
        soak_result = _execute_dry_run_soak(
            root=root,
            target=target,
            iterations=soak_iterations,
            file_count=file_count,
        )
        result = _execute_case(
            case="count-10000",
            root=root,
            target=target,
            parameters={
                "retention_policy": "count",
                "max_file_count": keep_count,
                "delete_limit": file_count,
            },
            initial_file_count=file_count,
            expected_deleted_count=file_count - keep_count,
        )
        remaining_names = sorted(path.name for path in target.glob("*.dat"))
        expected_first_name = f"result-{file_count - keep_count:05d}.dat"
        if not remaining_names or remaining_names[0] != expected_first_name:
            raise AssertionError("数量策略没有稳定保留最新文件")
        return result, soak_result


def _execute_dry_run_soak(
    *,
    root: Path,
    target: Path,
    iterations: int,
    file_count: int,
) -> SoakResult:
    """对同一 10,000 文件目录重复执行完整 dry-run 扫描。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(root / "object-store"))
    )
    registry = WorkflowNodeRuntimeRegistry()
    registry.register_python_callable(
        CORE_NODE_SPEC.node_definition,
        CORE_NODE_SPEC.handler,
    )
    template = _build_template(
        {
            "retention_policy": "count",
            "max_file_count": 1_000,
            "delete_limit": 1_000,
            "dry_run": True,
        }
    )
    process = psutil.Process()
    gc.collect()
    before = _process_metrics(process)
    started_at = perf_counter()
    for iteration in range(iterations):
        graph_result = WorkflowGraphExecutor(registry=registry).execute(
            template=template,
            input_values={"target_directory": {"value": str(target)}},
            execution_metadata={
                "dataset_storage": storage,
                "project_id": "project-1",
                "application_id": "workflow-app-retention-benchmark",
                "workflow_run_id": f"workflow-run-soak-{iteration}",
            },
        )
        payload = graph_result.outputs["result"]["value"]
        if payload["state"] != "dry_run":
            raise AssertionError("重复扫描没有保持 dry_run")
        if int(payload["scanned_file_count"]) != file_count:
            raise AssertionError("重复扫描文件数量不符合预期")
    total_wall_duration_ms = (perf_counter() - started_at) * 1_000
    gc.collect()
    after = _process_metrics(process)
    return SoakResult(
        case="count-10000-dry-run-soak",
        iterations=iterations,
        file_count=file_count,
        total_wall_duration_ms=round(total_wall_duration_ms, 3),
        average_wall_duration_ms=round(total_wall_duration_ms / iterations, 3),
        rss_delta_bytes=after["rss"] - before["rss"],
        private_delta_bytes=after["private"] - before["private"],
        handle_delta=(
            after["handles"] - before["handles"]
            if before["handles"] is not None and after["handles"] is not None
            else None
        ),
    )


def _execute_case(
    *,
    case: str,
    root: Path,
    target: Path,
    parameters: dict[str, object],
    initial_file_count: int,
    expected_deleted_count: int,
) -> BenchmarkResult:
    """通过 WorkflowGraphExecutor 执行一次节点并采集资源变化。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(root / "object-store"))
    )
    registry = WorkflowNodeRuntimeRegistry()
    registry.register_python_callable(
        CORE_NODE_SPEC.node_definition,
        CORE_NODE_SPEC.handler,
    )
    template = _build_template(parameters)
    process = psutil.Process()
    gc.collect()
    before = _process_metrics(process)
    started_at = perf_counter()
    graph_result = WorkflowGraphExecutor(registry=registry).execute(
        template=template,
        input_values={"target_directory": {"value": str(target)}},
        execution_metadata={
            "dataset_storage": storage,
            "project_id": "project-1",
            "application_id": "workflow-app-retention-benchmark",
            "workflow_run_id": f"workflow-run-{case}",
        },
    )
    wall_duration_ms = (perf_counter() - started_at) * 1_000
    gc.collect()
    after = _process_metrics(process)
    payload = graph_result.outputs["result"]["value"]
    remaining_file_count = sum(1 for _path in target.glob("*.dat"))
    if int(payload["deleted_file_count"]) != expected_deleted_count:
        raise AssertionError(f"{case} 删除数量不符合预期")
    if remaining_file_count != initial_file_count - expected_deleted_count:
        raise AssertionError(f"{case} 磁盘剩余数量不符合预期")
    return BenchmarkResult(
        case=case,
        initial_file_count=initial_file_count,
        expected_deleted_count=expected_deleted_count,
        deleted_file_count=int(payload["deleted_file_count"]),
        remaining_file_count=remaining_file_count,
        node_duration_ms=int(payload["duration_ms"]),
        wall_duration_ms=round(wall_duration_ms, 3),
        rss_delta_bytes=after["rss"] - before["rss"],
        private_delta_bytes=after["private"] - before["private"],
        handle_delta=(
            after["handles"] - before["handles"]
            if before["handles"] is not None and after["handles"] is not None
            else None
        ),
        state=str(payload["state"]),
        has_more=bool(payload["has_more"]),
    )


def _build_template(parameters: dict[str, object]) -> WorkflowGraphTemplate:
    """构造与持久 Workflow App 相同的一节点验证图。"""

    return WorkflowGraphTemplate(
        template_id="storage-retention-scale-benchmark",
        template_version="1.0.0",
        display_name="Storage Retention Scale Benchmark",
        nodes=(
            WorkflowGraphNode(
                node_id="storage-retention-cleanup",
                node_type_id=CORE_NODE_SPEC.node_definition.node_type_id,
                parameters={
                    **parameters,
                    "recursive": True,
                    "include_patterns": ["*.dat"],
                    "delete_empty_directories": False,
                    "dry_run": parameters.get("dry_run", False),
                },
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="target_directory",
                display_name="Target Directory",
                payload_type_id="value.v1",
                target_node_id="storage-retention-cleanup",
                target_port="target_directory",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="result",
                display_name="Result",
                payload_type_id="value.v1",
                source_node_id="storage-retention-cleanup",
                source_port="result",
            ),
        ),
    )


def _create_file(path: Path, modified_time: datetime) -> None:
    """创建单字节真实文件并设置稳定修改时间。"""

    path.write_bytes(b"x")
    timestamp_ns = int(modified_time.timestamp() * 1_000_000_000)
    os.utime(path, ns=(timestamp_ns, timestamp_ns))


def _process_metrics(process: psutil.Process) -> dict[str, int | None]:
    """读取 RSS、Private Memory 和 Windows handle 数。"""

    memory = process.memory_full_info()
    handle_count = process.num_handles() if hasattr(process, "num_handles") else None
    return {
        "rss": int(memory.rss),
        "private": int(getattr(memory, "private", memory.rss)),
        "handles": int(handle_count) if handle_count is not None else None,
    }


if __name__ == "__main__":
    main()
