"""release 组装流程测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import backend.maintenance.release_assembly as release_assembly
from backend.maintenance.release_assembly import ReleaseAssemblyRequest, assemble_release


def test_assemble_release_materializes_full_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 full profile 会生成完整的 release 布局和专用 worker wrapper。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full",
            output_root=tmp_path,
        )
    )

    release_dir = tmp_path / "full"
    assert result.release_dir == release_dir.resolve()
    assert (release_dir / "app" / "backend").is_dir()
    assert (release_dir / "config" / "backend-service.json").is_file()
    assert (release_dir / "launchers" / "common.py").is_file()
    assert (release_dir / "launchers" / "service" / "start_backend_service.py").is_file()
    assert (release_dir / "launchers" / "service" / "start-backend-service.bat").is_file()
    assert (release_dir / "launchers" / "maintenance" / "invoke_backend_maintenance.py").is_file()
    assert (release_dir / "start_amvision_full.py").is_file()
    assert (release_dir / "start-amvision-full.bat").is_file()
    assert (release_dir / "start-amvision-full.sh").is_file()
    assert (release_dir / "stop_amvision_full.py").is_file()
    assert (release_dir / "stop-amvision-full.bat").is_file()
    assert (release_dir / "stop-amvision-full.sh").is_file()
    assert (release_dir / "app" / "requirements.txt").is_file()
    assert (release_dir / "custom_nodes" / "opencv_basic_nodes" / "manifest.json").is_file()
    assert (release_dir / "custom_nodes" / "_scaffold" / "README.md").is_file()
    assert not (release_dir / "custom_nodes" / "__pycache__").exists()
    assert (release_dir / "frontend").is_dir()
    assert (release_dir / "python").is_dir()
    assert result.bundled_python_mode == "placeholder-empty"

    requirements_text = (release_dir / "app" / "requirements.txt").read_text(encoding="utf-8")
    assert "torch==2.8.0" in requirements_text
    assert "onnxruntime>=1.22,<2" in requirements_text
    assert "openvino>=2026.1.0" in requirements_text
    assert "tensorrt-cu12==10.13.2.6" in requirements_text

    expected_worker_profile_ids = (
        "dataset-import",
        "dataset-export",
        "training",
        "conversion",
        "evaluation",
        "inference",
    )
    assert result.worker_profile_ids == expected_worker_profile_ids
    for profile_id in expected_worker_profile_ids:
        assert (release_dir / "manifests" / "worker-profiles" / f"{profile_id}.json").is_file()
        assert (release_dir / "launchers" / "worker" / f"start-{profile_id}-worker.bat").is_file()
        assert (release_dir / "launchers" / "worker" / f"start-{profile_id}-worker.sh").is_file()

    release_manifest = json.loads(
        (release_dir / "manifests" / "release-profiles" / "full.json").read_text(
            encoding="utf-8"
        )
    )
    assert release_manifest["requirements_file"] == "app/requirements.txt"
    assert release_manifest["bundled_python"] == {
        "python_dir": "python",
        "mode": "placeholder-empty",
        "included": False,
        "managed_manually": True,
    }
    assert release_manifest["layout"]["custom_nodes_dir"] == "custom_nodes"
    assert release_manifest["layout"]["python_dir"] == "python"
    assert release_manifest["service"]["windows_launcher"] == "launchers/service/start-backend-service.bat"
    assert release_manifest["stack"]["windows_launcher"] == "start-amvision-full.bat"
    assert release_manifest["stack"]["stop_windows_launcher"] == "stop-amvision-full.bat"
    assert release_manifest["stack"]["state_file"] == "logs/full-stack/runtime-state.json"
    assert [worker["profile_id"] for worker in release_manifest["workers"]] == list(
        expected_worker_profile_ids
    )
    assert release_manifest["workers"][0]["python_launcher"] == "launchers/worker/start_backend_worker.py"


def test_assemble_release_requires_force_to_overwrite_existing_directory(tmp_path: Path) -> None:
    """验证 release 目录已存在时必须显式允许覆盖。"""

    release_dir = tmp_path / "full"
    release_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(FileExistsError):
        assemble_release(
            ReleaseAssemblyRequest(
                profile_id="full",
                output_root=tmp_path,
            )
        )


def test_assemble_release_preserves_existing_python_dir_when_overwriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证覆盖发布时会保留已有 python 目录内容。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    release_dir = tmp_path / "full"
    existing_python_dir = release_dir / "python"
    existing_python_dir.mkdir(parents=True, exist_ok=True)
    marker_file = existing_python_dir / "marker.txt"
    marker_file.write_text("keep", encoding="utf-8")

    stale_file = release_dir / "app" / "stale.txt"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text("stale", encoding="utf-8")

    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full",
            output_root=tmp_path,
            overwrite=True,
        )
    )

    assert result.bundled_python_dir == (release_dir / "python").resolve()
    assert result.bundled_python_mode == "preserved-existing"
    assert marker_file.read_text(encoding="utf-8") == "keep"
    assert not stale_file.exists()
    assert (release_dir / "app" / "backend").is_dir()
    assert (release_dir / "custom_nodes" / "opencv_basic_nodes" / "manifest.json").is_file()


def _patch_release_runtime_asset_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """用轻量测试目录替换 release 组装使用的运行期资产源目录。"""

    source_custom_nodes_dir = tmp_path / "source-custom-nodes"
    (source_custom_nodes_dir / "opencv_basic_nodes").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "opencv_basic_nodes" / "manifest.json").write_text(
        '{"id": "opencv.basic-nodes"}\n',
        encoding="utf-8",
    )
    (source_custom_nodes_dir / "_scaffold").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "_scaffold" / "README.md").write_text("template\n", encoding="utf-8")
    (source_custom_nodes_dir / "__pycache__").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "__pycache__" / "cached.pyc").write_bytes(b"cache")

    monkeypatch.setattr(release_assembly, "SOURCE_CUSTOM_NODES_DIR", source_custom_nodes_dir)
