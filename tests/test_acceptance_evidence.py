"""验收隔离与失败阶段持久化的边界测试。"""

import json
from pathlib import Path

import pytest

from tests.integration.acceptance_evidence import (
    copy_pretrained_assets, create_run_directory, read_case_progress, record_case_failure, record_case_progress,
)
from tests.integration.yolo_model_full_chain_smoke import build_e2e_process_environment
from tests.integration.yolo_model_full_chain_smoke import select_conversion_build


def test_evidence_uses_shared_atomic_replacement(tmp_path: Path, monkeypatch) -> None:
    """证据写入复用已有平台原子替换，失败不能破坏旧文件或被清理错误覆盖。"""
    from tests.integration import acceptance_evidence as evidence

    target = tmp_path / "progress.json"
    target.write_text('{"stage":"previous"}')
    failure = PermissionError("busy")

    def reject(source: Path, destination: Path) -> None:
        """核对先完整写入临时文件，再原子发布。"""
        assert json.loads(source.read_text()) == {"stage": "next"}
        assert destination == target
        raise failure

    monkeypatch.setattr(evidence, "replace_path_with_retry", reject)
    with pytest.raises(PermissionError) as caught:
        evidence.write_evidence(target, {"stage": "next"})
    assert caught.value is failure
    assert json.loads(target.read_text()) == {"stage": "previous"}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("run_id", ["../other", "../", "a/b", "a\\b", ".", "..", "C:\\temp"])
def test_run_directory_rejects_paths(tmp_path: Path, run_id: str) -> None:
    """验收标识不能选择任意文件系统路径。"""
    with pytest.raises(ValueError):
        create_run_directory(tmp_path, run_id)


def test_run_directory_preserves_previous_evidence(tmp_path: Path) -> None:
    """重复运行标识必须拒绝，不能覆盖已有失败记录。"""
    directory = create_run_directory(tmp_path, "run-1")
    record_case_progress(directory, "conversion", model_version_id="original", training_task_id="train-1")
    record_case_progress(directory, "deployment", model_build_id="build-1")
    with pytest.raises(FileExistsError):
        create_run_directory(tmp_path, "run-1")
    evidence = read_case_progress(directory)
    assert evidence["model_version_id"] == "original"
    assert evidence["training_task_id"] == "train-1"
    assert evidence["model_build_id"] == "build-1"
    assert json.loads((directory / "progress.json").read_text())["stage"] == "deployment"
    assert not list(directory.glob("*.tmp"))


def test_storage_and_worker_paths_are_owned_by_run(tmp_path: Path, monkeypatch) -> None:
    """继承环境中的开发目录不能污染本轮 ObjectStore、队列或 workspace。"""
    monkeypatch.setenv("AMVISION_DATASET_STORAGE__ROOT_DIR", str(tmp_path / "customer-data"))
    monkeypatch.setenv("AMVISION_WORKER_WORKSPACE__ROOT_DIR", str(tmp_path / "customer-worker"))
    monkeypatch.setenv("AMVISION_DEVICE_LEASES__ROOT_DIR", "host-device-leases")
    first = build_e2e_process_environment(run_dir=tmp_path / "a", port=18360)
    second = build_e2e_process_environment(run_dir=tmp_path / "b", port=18361)
    for key in ("AMVISION_DATASET_STORAGE__ROOT_DIR", "AMVISION_WORKER_DATASET_STORAGE__ROOT_DIR",
                "AMVISION_WORKER_WORKSPACE__ROOT_DIR", "AMVISION_QUEUE__ROOT_DIR", "AMVISION_LOCAL_MEMORY__ROOT_DIR"):
        assert Path(first[key]).is_relative_to(tmp_path / "a")
        assert first[key] != second[key]
    # 物理 GPU 协调仍属于主机，不能为测试建立另一套无效的锁。
    assert first["AMVISION_DEVICE_LEASES__ROOT_DIR"] == "host-device-leases"


@pytest.mark.parametrize("explicit", [False, True])
def test_worker_launcher_preserves_explicit_workspace(tmp_path: Path, monkeypatch, explicit: bool) -> None:
    """穿过 launcher 装配，核对最终子进程收到的 workspace。"""
    from runtimes.launchers.worker import start_backend_worker as launcher

    repository = Path(__file__).resolve().parents[1]
    expected = str(tmp_path / "conversion") if explicit else "./data/worker/conversion"
    monkeypatch.delenv("AMVISION_WORKER_WORKSPACE__ROOT_DIR", raising=False)
    if explicit:
        monkeypatch.setenv("AMVISION_WORKER_WORKSPACE__ROOT_DIR", expected)
    captured = {}

    def capture(**kwargs):
        """只记录子进程配置，不启动实际 worker。"""
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(launcher, "ensure_windows_long_paths_enabled", lambda **_: True)
    monkeypatch.setattr(launcher, "run_python_module", capture)
    assert launcher.main([
        "--app-root", str(repository), "--worker-profile-file",
        "runtimes/manifests/worker-profiles/conversion.json", "--topology-id", "test",
        "--topology-generation", "1", "--topology-epoch-id", "epoch", "--worker-instance-id", "worker",
        "--worker-runtime-root", str(tmp_path / "workers"),
    ]) == 0
    assert captured["extra_env"]["AMVISION_WORKER_WORKSPACE__ROOT_DIR"] == expected


def test_e2e_settings_resolve_same_object_store(tmp_path: Path, monkeypatch) -> None:
    """使用正式 Settings 解析环境变量，保证 service 和 worker 指向同一隔离存储。"""
    from backend.service.settings import BackendServiceSettings
    from backend.workers.settings import BackendWorkerSettings

    environment = build_e2e_process_environment(run_dir=tmp_path, port=18360)
    for key, value in environment.items():
        if key.startswith("AMVISION_"):
            monkeypatch.setenv(key, value)
    service, worker = BackendServiceSettings(), BackendWorkerSettings()
    assert Path(service.dataset_storage.root_dir) == tmp_path / "storage"
    assert service.dataset_storage.root_dir == worker.dataset_storage.root_dir
    assert Path(worker.workspace.root_dir) == tmp_path / "runtime/worker"


def test_failure_keeps_original_stage_and_identity(tmp_path: Path) -> None:
    """失败不能把原训练和失败阶段覆盖成另一轮成功。"""
    record_case_progress(tmp_path, "conversion", model_version_id="original")
    result = record_case_failure(tmp_path, RuntimeError("numeric gate"))
    assert result["failed_stage"] == "conversion"
    assert result["status"] == "failed"
    assert result["model_version_id"] == "original"


def test_selected_pretrained_assets_are_independent(tmp_path: Path) -> None:
    """选中权重使用副本；摘要能追溯来源，其他版本不进入隔离存储。"""
    source, destination = tmp_path / "source", tmp_path / "run/storage"
    entry = source / "models/pretrained/yolo26/segmentation/nano/default"
    entry.mkdir(parents=True)
    (entry / "manifest.json").write_text(json.dumps({"model_version_id": "v1", "checkpoint_path": "model.pt"}))
    (entry / "model.pt").write_bytes(b"weights")
    evidence = copy_pretrained_assets(source_root=source, destination_root=destination, model_version_ids={"v1"})
    assert len(evidence) == 2
    copied = destination / (entry / "model.pt").relative_to(source)
    copied.write_bytes(b"changed")
    assert (entry / "model.pt").read_bytes() == b"weights"
    with pytest.raises(ValueError, match="未找到"):
        copy_pretrained_assets(source_root=source, destination_root=tmp_path / "other", model_version_ids={"missing"})


def test_pretrained_asset_cannot_escape_source(tmp_path: Path) -> None:
    """manifest 的 checkpoint 路径不能读取来源目录之外的文件。"""
    source = tmp_path / "source"
    entry = source / "models/pretrained/v1"
    entry.mkdir(parents=True)
    outside = tmp_path / "outside.pt"
    outside.write_bytes(b"outside")
    (entry / "manifest.json").write_text(json.dumps({"model_version_id": "v1", "checkpoint_path": str(outside)}))
    with pytest.raises(ValueError, match="越出"):
        copy_pretrained_assets(source_root=source, destination_root=tmp_path / "run", model_version_ids={"v1"})


def test_conversion_cannot_substitute_another_build_format() -> None:
    """TensorRT 缺失时不能拿 ONNX 登记冒充 TensorRT 验收通过。"""
    with pytest.raises(RuntimeError, match="目标格式"):
        select_conversion_build({"builds":[{"model_build_id":"onnx", "build_format":"onnx"}]},
                                target_format="tensorrt-engine")


def test_pretrained_copy_cannot_retain_absolute_reference(tmp_path: Path) -> None:
    """来源内绝对路径也会让副本引用原权重，必须在启动前拒绝。"""
    source = tmp_path / "source"
    entry = source / "models/pretrained/v1"
    entry.mkdir(parents=True)
    checkpoint = entry / "model.pt"
    checkpoint.write_bytes(b"weights")
    (entry / "manifest.json").write_text(json.dumps({"model_version_id":"v1", "checkpoint_path":str(checkpoint)}))
    with pytest.raises(ValueError, match="相对 checkpoint_path"):
        copy_pretrained_assets(source_root=source, destination_root=tmp_path / "run", model_version_ids={"v1"})
    with pytest.raises(ValueError, match="不得覆盖"):
        copy_pretrained_assets(source_root=source, destination_root=source / "run", model_version_ids={"v1"})
