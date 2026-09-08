"""部署包契约及文件完整性测试，不需要加载视觉模型。"""

import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from backend.contracts.deployments.model_package import ModelDeploymentPackage, safe_package_path
from backend.service.infrastructure.object_store.model_package_archive import read_package, write_package


def sample_package() -> ModelDeploymentPackage:
    """生成非正方形输入的最小 PyTorch 包夹具。"""
    return ModelDeploymentPackage.model_validate({
        "package_id": "test-package", "source_version": "0.1.5", "created_at": "2026-09-08T00:00:00Z",
        "deployment": {"deployment_instance_id": "deployment-1", "display_name": "测试模型", "runtime_backend": "pytorch", "device_name": "cpu", "runtime_configuration": {}},
        "model": {"model_id": "model-1", "model_name": "sample", "model_type": "yolo11", "task_type": "classification", "model_scale": "n"},
        "model_version": {"model_version_id": "version-1"},
        "inference": {"runtime_precision": "fp32", "input_size": {"width": 320, "height": 192}, "labels": ["good", "bad"], "runtime_file": "weights", "checkpoint_file": "weights"},
        "files": [{"key": "weights", "owner": "version", "path": "best.pt", "logical_name": "best.pt", "file_type": "checkpoint", "sha256": hashlib.sha256(b"model").hexdigest(), "byte_size": 5}],
    })


def test_roundtrip_preserves_inference_and_files(tmp_path: Path) -> None:
    """宽高、类别顺序和字节内容保持不变。"""
    source = tmp_path / "source.pt"
    source.write_bytes(b"model")
    manifest = sample_package()
    archive = tmp_path / "model.zip"
    write_package(archive, manifest, {"weights": source})
    restored = read_package(archive, tmp_path / "unpacked")
    assert restored == manifest
    assert (tmp_path / "unpacked/version/best.pt").read_bytes() == b"model"


@pytest.mark.parametrize("path", ["../bad", "a/../b", "/etc/passwd", "C:/bad", "a\\b", "con.txt", "a./b", "a//b", "a\x00b"])
def test_unsafe_paths_are_rejected(path: str) -> None:
    with pytest.raises(ValueError):
        safe_package_path(path)


def test_source_change_does_not_publish_archive(tmp_path: Path) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="变化"):
        write_package(tmp_path / "model.zip", sample_package(), {"weights": source})
    assert not (tmp_path / "model.zip").exists()
    assert not (tmp_path / "model.writing").exists()


def test_bad_hash_and_extra_files_are_rejected(tmp_path: Path) -> None:
    for extra in (False, True):
        archive = tmp_path / f"bad-{extra}.zip"
        with ZipFile(archive, "w") as z:
            z.writestr("manifest.json", sample_package().model_dump_json())
            z.writestr("files/version/best.pt", b"wrong")
            if extra:
                z.writestr("hidden.exe", b"x")
        with pytest.raises(ValueError):
            read_package(archive, tmp_path / f"unpack-{extra}")


def test_missing_reference_and_runtime_state_are_rejected() -> None:
    payload = sample_package().model_dump()
    payload["inference"]["runtime_file"] = "missing"
    with pytest.raises(ValidationError):
        ModelDeploymentPackage.model_validate(payload)
    payload = sample_package().model_dump()
    payload["deployment"]["desired_state"] = "running"
    with pytest.raises(ValidationError):
        ModelDeploymentPackage.model_validate(payload)
