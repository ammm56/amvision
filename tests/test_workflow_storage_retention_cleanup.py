"""Storage Retention Cleanup 节点和通用策略测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
from threading import Event

import pytest

from backend.nodes.core_nodes.io.output.storage.storage_retention_cleanup import (
    CORE_NODE_SPEC,
    _storage_retention_cleanup_handler,
)
from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.io import acquire_path_write_locks
from backend.service.application.runtime.io.path_write_coordinator import (
    PathWriteCoordinator,
)
from backend.service.application.runtime.io import path_write_coordinator
from backend.service.application.runtime.io.storage_retention import (
    calculate_retention_cutoff,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRequest,
    WorkflowNodeRuntimeRegistry,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.filesystem.retention_files import (
    delete_local_retention_file_if_version,
    iter_local_retention_pages,
)


PROJECT_ID = "project-1"
APPLICATION_ID = "workflow-app-retention-test"
OBJECT_RESULTS_ROOT = (
    f"projects/{PROJECT_ID}/results/workflow-applications/{APPLICATION_ID}"
)


def test_storage_retention_node_definition_exposes_one_complete_result() -> None:
    """验证节点目录契约只有动态目标输入和单一完整结果输出。"""

    definition = CORE_NODE_SPEC.node_definition

    assert definition.node_type_id == "core.io.storage-retention-cleanup"
    assert [port.name for port in definition.input_ports] == ["target_directory"]
    assert [port.name for port in definition.output_ports] == ["result"]
    assert definition.parameter_input_bindings[0].parameter_name == "target_directory"
    assert "check_interval_hours" not in definition.parameter_schema["properties"]


def test_graph_executor_uses_connected_target_directory(tmp_path: Path) -> None:
    """验证动态目标端口通过统一参数解析进入真实 Workflow 图执行。"""

    storage, target = _create_filesystem_target(tmp_path)
    for index in range(3):
        _write_file(
            target / f"graph-{index}.json",
            modified_time=datetime.now(tz=timezone.utc) - timedelta(minutes=3 - index),
        )
    registry = WorkflowNodeRuntimeRegistry()
    registry.register_python_callable(
        CORE_NODE_SPEC.node_definition,
        CORE_NODE_SPEC.handler,
    )
    template = WorkflowGraphTemplate(
        template_id="storage-retention-graph-test",
        template_version="1.0.0",
        display_name="Storage Retention Graph Test",
        nodes=(
            WorkflowGraphNode(
                node_id="cleanup",
                node_type_id=CORE_NODE_SPEC.node_definition.node_type_id,
                parameters={
                    "retention_policy": "count",
                    "max_file_count": 2,
                    "recursive": True,
                    "include_patterns": ["*.json"],
                    "delete_empty_directories": False,
                    "delete_limit": 1000,
                    "dry_run": False,
                },
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="target_directory",
                display_name="Target Directory",
                payload_type_id="value.v1",
                target_node_id="cleanup",
                target_port="target_directory",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="result",
                display_name="Result",
                payload_type_id="value.v1",
                source_node_id="cleanup",
                source_port="result",
            ),
        ),
    )

    graph_result = WorkflowGraphExecutor(registry=registry).execute(
        template=template,
        input_values={"target_directory": {"value": str(target)}},
        execution_metadata={
            "dataset_storage": storage,
            "project_id": PROJECT_ID,
            "application_id": APPLICATION_ID,
            "workflow_run_id": "workflow-run-graph-test",
        },
    )

    result = graph_result.outputs["result"]["value"]
    assert result["deleted_file_count"] == 1
    assert sorted(path.name for path in target.glob("*.json")) == [
        "graph-1.json",
        "graph-2.json",
    ]


def test_retention_cutoff_uses_calendar_month_and_year_boundaries() -> None:
    """验证月末、闰年和普通日的日历截止时间。"""

    march_end = datetime(2024, 3, 31, 9, 30, tzinfo=timezone.utc)
    leap_day = datetime(2024, 2, 29, 9, 30, tzinfo=timezone.utc)

    assert calculate_retention_cutoff(
        march_end,
        retention_value=1,
        retention_unit="month",
    ) == datetime(2024, 2, 29, 9, 30, tzinfo=timezone.utc)
    assert calculate_retention_cutoff(
        leap_day,
        retention_value=1,
        retention_unit="year",
    ) == datetime(2023, 2, 28, 9, 30, tzinfo=timezone.utc)
    assert calculate_retention_cutoff(
        march_end,
        retention_value=3,
        retention_unit="day",
    ) == datetime(2024, 3, 28, 9, 30, tzinfo=timezone.utc)


def test_count_policy_deletes_stable_oldest_batch_without_compensation(
    tmp_path: Path,
) -> None:
    """验证数量策略按修改时间和相对路径稳定分批删除。"""

    storage, target = _create_filesystem_target(tmp_path)
    same_time = datetime.now(tz=timezone.utc) - timedelta(days=1)
    for index in range(10):
        _write_file(target / f"result-{index:02d}.json", modified_time=same_time)

    first = _execute(
        storage,
        target_directory=str(target),
        retention_policy="count",
        max_file_count=5,
        delete_limit=3,
        dry_run=False,
    )

    assert first["state"] == "partial"
    assert first["eligible_file_count"] == 5
    assert first["deleted_file_count"] == 3
    assert first["has_more"] is True
    assert not (target / "result-00.json").exists()
    assert not (target / "result-01.json").exists()
    assert not (target / "result-02.json").exists()

    second = _execute(
        storage,
        target_directory=str(target),
        retention_policy="count",
        max_file_count=5,
        delete_limit=3,
        dry_run=False,
    )

    assert second["state"] == "completed"
    assert second["eligible_file_count"] == 2
    assert second["deleted_file_count"] == 2
    assert sorted(path.name for path in target.glob("*.json")) == [
        f"result-{index:02d}.json" for index in range(5, 10)
    ]


def test_age_policy_dry_run_and_delete_are_strictly_time_based(tmp_path: Path) -> None:
    """验证 dry-run 不修改文件，真实执行只删除严格早于截止点的文件。"""

    storage, target = _create_filesystem_target(tmp_path)
    _write_file(
        target / "expired.jpg",
        modified_time=datetime.now(tz=timezone.utc) - timedelta(days=3),
    )
    _write_file(
        target / "recent.jpg",
        modified_time=datetime.now(tz=timezone.utc) - timedelta(hours=1),
    )
    _write_file(
        target / "ignored.json",
        modified_time=datetime.now(tz=timezone.utc) - timedelta(days=3),
    )

    preview = _execute(
        storage,
        target_directory=str(target),
        retention_policy="age",
        retention_value=1,
        retention_unit="day",
        include_patterns=["*.jpg"],
        dry_run=True,
    )

    assert preview["state"] == "dry_run"
    assert preview["scanned_file_count"] == 3
    assert preview["matched_file_count"] == 2
    assert preview["eligible_file_count"] == 1
    assert preview["deleted_file_count"] == 0
    assert preview["has_more"] is True
    assert (target / "expired.jpg").exists()

    result = _execute(
        storage,
        target_directory=str(target),
        retention_policy="age",
        retention_value=1,
        retention_unit="day",
        include_patterns=["*.jpg"],
        dry_run=False,
    )

    assert result["state"] == "completed"
    assert result["deleted_file_count"] == 1
    assert not (target / "expired.jpg").exists()
    assert (target / "recent.jpg").exists()
    assert (target / "ignored.json").exists()


def test_age_and_count_policy_uses_union_of_oldest_prefixes(tmp_path: Path) -> None:
    """验证组合策略删除时间和数量约束中更长的最旧前缀。"""

    storage, target = _create_filesystem_target(tmp_path)
    now = datetime.now(tz=timezone.utc)
    for index in range(8):
        age_days = 10 - index if index < 3 else 0
        _write_file(
            target / f"item-{index}.txt",
            modified_time=now - timedelta(days=age_days, minutes=8 - index),
        )

    result = _execute(
        storage,
        target_directory=str(target),
        retention_policy="age-and-count",
        retention_value=2,
        retention_unit="day",
        max_file_count=4,
        dry_run=False,
    )

    assert result["eligible_file_count"] == 4
    assert result["deleted_file_count"] == 4
    assert sorted(path.name for path in target.glob("*.txt")) == [
        "item-4.txt",
        "item-5.txt",
        "item-6.txt",
        "item-7.txt",
    ]


def test_object_store_policy_is_limited_to_current_workflow_app_results(
    tmp_path: Path,
) -> None:
    """验证 ObjectStore 能实际清理当前 App 结果，并拒绝其他 namespace。"""

    storage = _create_storage(tmp_path)
    target = f"{OBJECT_RESULTS_ROOT}/runs/run-1"
    storage.prepare_prefix(target)
    for index in range(6):
        object_key = f"{target}/result-{index}.json"
        storage.write_bytes(object_key, b"{}")
        _set_modified_time(
            storage.resolve(object_key),
            datetime.now(tz=timezone.utc) - timedelta(minutes=10 - index),
        )

    result = _execute(
        storage,
        target_directory=target,
        retention_policy="count",
        max_file_count=4,
        dry_run=False,
    )

    assert result["location_kind"] == "object-store"
    assert result["deleted_file_count"] == 2
    assert len(list(storage.resolve(target).glob("*.json"))) == 4

    storage.prepare_prefix("projects/project-1/models")
    with pytest.raises(InvalidRequestError, match="不属于当前 Workflow App 结果域"):
        _execute(
            storage,
            target_directory="projects/project-1/models",
            retention_policy="count",
            max_file_count=1,
            dry_run=False,
        )


def test_cleanup_skips_locked_file_without_waiting_or_deleting_next(
    tmp_path: Path,
) -> None:
    """验证清理遇到正在写入的最旧文件时立即跳过且不补删下一项。"""

    storage, target = _create_filesystem_target(tmp_path)
    oldest = target / "oldest.json"
    newest = target / "newest.json"
    _write_file(
        oldest,
        modified_time=datetime.now(tz=timezone.utc) - timedelta(minutes=2),
    )
    _write_file(
        newest,
        modified_time=datetime.now(tz=timezone.utc) - timedelta(minutes=1),
    )
    lock_ready = Event()
    release_lock = Event()

    def hold_lock() -> None:
        with acquire_path_write_locks(_request(storage, {}), (oldest,)):
            lock_ready.set()
            release_lock.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(hold_lock)
        assert lock_ready.wait(timeout=5)
        result = _execute(
            storage,
            target_directory=str(target),
            retention_policy="count",
            max_file_count=1,
            dry_run=False,
        )
        release_lock.set()
        future.result(timeout=5)

    assert result["deleted_file_count"] == 0
    assert result["skipped_locked_count"] == 1
    assert result["has_more"] is True
    assert oldest.exists()
    assert newest.exists()


def test_concurrent_cleanup_returns_target_locked_without_scanning(
    tmp_path: Path,
) -> None:
    """验证同一目标已有清理调用时立即返回，不排队也不删除。"""

    storage, target = _create_filesystem_target(tmp_path)
    _write_file(
        target / "oldest.json",
        modified_time=datetime.now(tz=timezone.utc) - timedelta(minutes=1),
    )
    coordination_path = target / ".amvision-retention-cleanup-operation"
    lock_ready = Event()
    release_lock = Event()

    def hold_target_lock() -> None:
        with acquire_path_write_locks(
            _request(storage, {}),
            (coordination_path,),
        ):
            lock_ready.set()
            release_lock.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(hold_target_lock)
        assert lock_ready.wait(timeout=5)
        result = _execute(
            storage,
            target_directory=str(target),
            retention_policy="count",
            max_file_count=1,
            dry_run=False,
        )
        release_lock.set()
        future.result(timeout=5)

    assert result["state"] == "target_locked"
    assert result["target_lock_conflict"] is True
    assert result["scanned_file_count"] == 0
    assert result["deleted_file_count"] == 0
    assert result["has_more"] is True
    assert (target / "oldest.json").exists()


def test_path_lock_is_shared_across_processes_and_released() -> None:
    """验证固定大小 byte-range lock 在进程间互斥且退出后可恢复。"""

    path = Path("cross-process-retention-lock-test").resolve()
    script = """
from pathlib import Path
import sys
from backend.service.application.runtime.io.path_write_coordinator import PathWriteCoordinator
with PathWriteCoordinator().try_acquire((Path(sys.argv[1]),)) as acquired:
    print(str(acquired).lower())
"""
    coordinator = PathWriteCoordinator()
    with coordinator.try_acquire((path,)) as acquired:
        assert acquired is True
        blocked = subprocess.run(
            [sys.executable, "-c", script, str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    released = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert blocked.stdout.strip() == "false"
    assert released.stdout.strip() == "true"


def test_path_lock_uses_sparse_offset_without_growing_lock_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 63-bit 锁偏移不会把共享锁文件扩展到对应大小。"""

    lock_root = tmp_path / "locks"
    lock_file = lock_root / "path-locks.v1"
    monkeypatch.setattr(path_write_coordinator, "_LOCK_ROOT", lock_root)
    monkeypatch.setattr(path_write_coordinator, "_LOCK_FILE_PATH", lock_file)

    with PathWriteCoordinator().try_acquire(
        (tmp_path / "result-a.json", tmp_path / "result-b.json")
    ) as acquired:
        assert acquired is True

    assert lock_file.is_file()
    assert lock_file.stat().st_size == 0


def test_target_not_found_is_success_and_protected_root_is_rejected(
    tmp_path: Path,
) -> None:
    """验证不存在目标幂等成功，ObjectStore 根目录和平台数据根目录不可清理。"""

    storage = _create_storage(tmp_path)
    missing = (tmp_path / "not-created" / "results").resolve()

    result = _execute(
        storage,
        target_directory=str(missing),
        retention_policy="count",
        max_file_count=1,
        dry_run=False,
    )

    assert result["state"] == "target_not_found"
    assert result["scanned_file_count"] == 0
    with pytest.raises(InvalidRequestError, match="受保护"):
        _execute(
            storage,
            target_directory=str(storage.root_dir),
            retention_policy="count",
            max_file_count=1,
            dry_run=False,
        )


def test_scan_skips_control_temp_and_linked_files(tmp_path: Path) -> None:
    """验证内部控制文件、原子临时文件和符号链接不进入清理范围。"""

    _storage, target = _create_filesystem_target(tmp_path)
    _write_file(
        target / "normal.json",
        modified_time=datetime.now(tz=timezone.utc) - timedelta(days=1),
    )
    _write_file(
        target / ".amvision-write-journal",
        modified_time=datetime.now(tz=timezone.utc) - timedelta(days=1),
    )
    _write_file(
        target / ".atomic.tmp",
        modified_time=datetime.now(tz=timezone.utc) - timedelta(days=1),
    )
    linked_target = target / "outside.json"
    _write_file(
        linked_target,
        modified_time=datetime.now(tz=timezone.utc) - timedelta(days=1),
    )
    linked_file = target / "linked.json"
    try:
        linked_file.symlink_to(linked_target)
    except OSError:
        linked_file = None

    items = [
        item
        for page in iter_local_retention_pages(
            target,
            recursive=True,
            page_size=2,
        )
        for item in page.items
    ]

    assert sorted(item.object_key for item in items) == [
        "normal.json",
        "outside.json",
    ]
    if linked_file is not None:
        assert linked_file.exists()


def test_cleanup_rejects_symlink_target_directory(tmp_path: Path) -> None:
    """验证通用路径解析后仍能拒绝目标目录本身的符号链接。"""

    storage, target = _create_filesystem_target(tmp_path)
    linked_target = tmp_path / "linked-results"
    try:
        linked_target.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("当前系统未允许创建目录符号链接")

    with pytest.raises(InvalidRequestError, match="符号链接|reparse point"):
        _execute(
            storage,
            target_directory=str(linked_target),
            retention_policy="count",
            max_file_count=1,
            dry_run=False,
        )


def test_conditional_delete_refuses_file_changed_after_scan(tmp_path: Path) -> None:
    """验证扫描后被替换的文件不会按旧 metadata 删除。"""

    _storage, target = _create_filesystem_target(tmp_path)
    file_path = target / "result.json"
    _write_file(
        file_path,
        modified_time=datetime.now(tz=timezone.utc) - timedelta(days=1),
    )
    page = next(
        iter_local_retention_pages(target, recursive=True, page_size=512)
    )
    scanned_item = page.items[0]
    file_path.write_bytes(b"new-version-with-another-size")

    state = delete_local_retention_file_if_version(
        file_path,
        expected_version=scanned_item.version,
    )

    assert state == "changed"
    assert file_path.read_bytes() == b"new-version-with-another-size"


def test_delete_empty_directories_removes_children_but_keeps_target(
    tmp_path: Path,
) -> None:
    """验证可选空目录清理自底向上执行且始终保留目标根目录。"""

    storage, target = _create_filesystem_target(tmp_path)
    nested = target / "year" / "month" / "day"
    _write_file(
        nested / "expired.json",
        modified_time=datetime.now(tz=timezone.utc) - timedelta(days=3),
    )

    result = _execute(
        storage,
        target_directory=str(target),
        retention_policy="age",
        retention_value=1,
        retention_unit="day",
        delete_empty_directories=True,
        dry_run=False,
    )

    assert result["deleted_file_count"] == 1
    assert target.is_dir()
    assert not (target / "year").exists()


def _create_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建隔离的 LocalDatasetStorage。"""

    return LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "object-store"))
    )


def _create_filesystem_target(
    tmp_path: Path,
) -> tuple[LocalDatasetStorage, Path]:
    """创建与 ObjectStore 根目录分离的绝对路径目标。"""

    storage = _create_storage(tmp_path)
    target = (tmp_path / "external-results").resolve()
    target.mkdir(parents=True)
    return storage, target


def _write_file(path: Path, *, modified_time: datetime) -> None:
    """写入小文件并设置确定修改时间。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(path.name.encode("utf-8"))
    _set_modified_time(path, modified_time)


def _set_modified_time(path: Path, modified_time: datetime) -> None:
    """以纳秒精度设置文件访问和修改时间。"""

    timestamp_ns = int(modified_time.timestamp() * 1_000_000_000)
    os.utime(path, ns=(timestamp_ns, timestamp_ns))


def _request(
    storage: LocalDatasetStorage,
    parameters: dict[str, object],
) -> WorkflowNodeExecutionRequest:
    """构造真实节点 handler 使用的 Workflow 请求。"""

    return WorkflowNodeExecutionRequest(
        node_id="storage-retention-cleanup",
        node_definition=CORE_NODE_SPEC.node_definition,
        parameters=parameters,
        input_values={},
        execution_metadata={
            "dataset_storage": storage,
            "project_id": PROJECT_ID,
            "application_id": APPLICATION_ID,
            "workflow_run_id": "workflow-run-retention-test",
        },
    )


def _execute(
    storage: LocalDatasetStorage,
    *,
    target_directory: str,
    retention_policy: str,
    retention_value: int | None = None,
    retention_unit: str | None = None,
    max_file_count: int | None = None,
    include_patterns: list[str] | None = None,
    delete_empty_directories: bool = False,
    delete_limit: int = 1000,
    dry_run: bool,
) -> dict[str, object]:
    """执行节点并返回 result.value。"""

    parameters: dict[str, object] = {
        "target_directory": target_directory,
        "retention_policy": retention_policy,
        "recursive": True,
        "include_patterns": include_patterns or ["*"],
        "delete_empty_directories": delete_empty_directories,
        "delete_limit": delete_limit,
        "dry_run": dry_run,
    }
    if retention_value is not None:
        parameters["retention_value"] = retention_value
    if retention_unit is not None:
        parameters["retention_unit"] = retention_unit
    if max_file_count is not None:
        parameters["max_file_count"] = max_file_count
    output = _storage_retention_cleanup_handler(_request(storage, parameters))
    return output["result"]["value"]
