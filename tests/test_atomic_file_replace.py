"""本地原子文件替换测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.service.infrastructure.filesystem.atomic_files import (
    replace_path_with_retry,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_replace_path_with_retry_recovers_windows_sharing_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 WinError 5/32/33 的短暂占用会按预算重试。"""

    source_path = tmp_path / "source.tmp"
    target_path = tmp_path / "target.json"
    source_path.write_text("new", encoding="utf-8")
    target_path.write_text("old", encoding="utf-8")
    original_replace = Path.replace
    attempt_count = 0

    def replace_with_transient_lock(
        current_source_path: Path,
        current_target_path: str | Path,
    ) -> Path:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count <= 3:
            error = PermissionError("simulated Windows sharing violation")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error
        return original_replace(current_source_path, current_target_path)

    monkeypatch.setattr(Path, "replace", replace_with_transient_lock)

    replace_path_with_retry(
        source_path,
        target_path,
        retry_timeout_seconds=1.0,
    )

    assert attempt_count == 4
    assert target_path.read_text(encoding="utf-8") == "new"
    assert not source_path.exists()


def test_local_dataset_storage_json_write_uses_atomic_replace_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证对象存储 JSON 写入复用统一的 Windows 短暂占用恢复。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    original_replace = Path.replace
    sharing_violation_count = 0

    def replace_with_transient_lock(
        source_path: Path,
        target_path: str | Path,
    ) -> Path:
        nonlocal sharing_violation_count
        if Path(target_path).name == "events.json" and sharing_violation_count < 2:
            sharing_violation_count += 1
            error = PermissionError("simulated Windows sharing violation")
            error.winerror = 32  # type: ignore[attr-defined]
            raise error
        return original_replace(source_path, target_path)

    monkeypatch.setattr(Path, "replace", replace_with_transient_lock)

    dataset_storage.write_json(
        "workflows/runtime/app-runtimes/runtime-1/events.json",
        [{"sequence": 1}],
    )

    assert sharing_violation_count == 2
    assert dataset_storage.read_json(
        "workflows/runtime/app-runtimes/runtime-1/events.json"
    ) == [{"sequence": 1}]


def test_local_dataset_storage_text_write_uses_atomic_replace_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证文本写入不会原地截断，并复用 Windows 短暂占用恢复。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    original_replace = Path.replace
    sharing_violation_count = 0

    def replace_with_transient_lock(
        source_path: Path,
        target_path: str | Path,
    ) -> Path:
        nonlocal sharing_violation_count
        if Path(target_path).name == "manifest.json" and sharing_violation_count < 2:
            sharing_violation_count += 1
            error = PermissionError("simulated Windows sharing violation")
            error.winerror = 32  # type: ignore[attr-defined]
            raise error
        return original_replace(source_path, target_path)

    monkeypatch.setattr(Path, "replace", replace_with_transient_lock)

    dataset_storage.write_text("models/manifest.json", '{"status":"ready"}\n')

    assert sharing_violation_count == 2
    assert (
        dataset_storage.resolve("models/manifest.json").read_text(encoding="utf-8")
        == '{"status":"ready"}\n'
    )
    assert not list(dataset_storage.resolve("models").glob("*.tmp"))
