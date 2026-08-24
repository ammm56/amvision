"""release 组装流程测试。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import backend.maintenance.release_assembly as release_assembly
from backend.maintenance.main import run_command
from backend.maintenance.release_assembly import (
    ReleaseAssemblyRequest,
    assemble_release,
)


def test_assemble_release_materializes_windows_x64_nvidia_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 Windows x64 NVIDIA profile 只生成目标平台需要的完整布局。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-nvidia",
            output_root=tmp_path,
        )
    )

    release_dir = tmp_path / "full-windows-x64-nvidia"
    assert result.release_dir == release_dir.resolve()
    assert (release_dir / "app" / "backend").is_dir()
    assert (
        release_dir
        / "app"
        / "backend"
        / "runtime"
        / "processes"
        / "process_tree_supervisor.py"
    ).is_file()
    assert (release_dir / "config" / "backend-service.json").is_file()
    assert (release_dir / "launchers" / "common.py").is_file()
    assert (
        release_dir / "launchers" / "service" / "start_backend_service.py"
    ).is_file()
    assert (release_dir / "launchers" / "enable_windows_long_paths.py").is_file()
    assert (
        release_dir / "launchers" / "service" / "start-backend-service.bat"
    ).is_file()
    assert (
        release_dir / "launchers" / "maintenance" / "invoke_backend_maintenance.py"
    ).is_file()
    assert (
        release_dir / "launchers" / "inference" / "start_inference_daemon.py"
    ).is_file()
    assert (
        release_dir / "launchers" / "inference" / "start-inference-daemon.bat"
    ).is_file()
    assert (release_dir / "start_amvision_full.py").is_file()
    assert (release_dir / "start-amvision-full.bat").is_file()
    assert 'set "PYTHONUTF8=1"' in (release_dir / "start-amvision-full.bat").read_text(
        encoding="utf-8"
    )
    assert not (release_dir / "start-amvision-full.sh").exists()
    assert (release_dir / "stop_amvision_full.py").is_file()
    assert (release_dir / "stop-amvision-full.bat").is_file()
    assert not (release_dir / "stop-amvision-full.sh").exists()
    for document_name in (
        "README.md",
        "LICENSE",
        "LICENSE.zh-CN",
        "COMMERCIAL_LICENSE_REQUIRED.md",
    ):
        copied_document = release_dir / document_name
        assert copied_document.is_file()
        assert (
            copied_document.read_bytes()
            == (release_assembly.REPOSITORY_ROOT / document_name).read_bytes()
        )
    assert (release_dir / "app" / "requirements.txt").is_file()
    assert (release_dir / "custom_nodes" / "opencv_nodes" / "manifest.json").is_file()
    assert (
        release_dir / "custom_nodes" / "opencv_nodes" / "categories" / "geometry"
    ).is_dir()
    assert (
        release_dir
        / "custom_nodes"
        / "opencv_nodes"
        / "shared"
        / "backend"
        / "runtime"
        / "images.py"
    ).is_file()
    assert (
        release_dir
        / "custom_nodes"
        / "opencv_nodes"
        / "shared"
        / "workflow"
        / "payload_contracts.json"
    ).is_file()
    assert (
        release_dir
        / "custom_nodes"
        / "opencv_nodes"
        / "shared"
        / "workflow"
        / "payload_contracts.json"
    ).is_file()
    assert (release_dir / "custom_nodes" / "_scaffold" / "README.md").is_file()
    assert not (release_dir / "custom_nodes" / "__pycache__").exists()
    assert (release_dir / "tools" / "ffmpeg" / "windows-x64" / "ffmpeg.exe").is_file()
    assert not (release_dir / "tools" / "ffmpeg" / "linux-x64").exists()
    assert (release_dir / "tools" / "tensorrt" / "bin" / "trtexec.exe").is_file()
    assert (
        release_dir
        / "tools"
        / "tensorrt"
        / "python"
        / "tensorrt-10.16.1.11-cp312-none-win_amd64.whl"
    ).is_file()
    assert (release_dir / "tools" / "tensorrt" / "doc" / "README.txt").is_file()
    assert not (release_dir / "tools" / "tensorrt" / "include").exists()
    assert not (release_dir / "tools" / "tensorrt" / "lib").exists()
    assert (
        release_dir / "tools" / "cudnn" / "bin" / "12.9" / "x64" / "cudnn64_9.dll"
    ).is_file()
    assert (release_dir / "tools" / "cudnn" / "LICENSE").is_file()
    assert (release_dir / "frontend" / "index.html").is_file()
    assert (release_dir / "frontend" / "runtime-config.json").is_file()
    assert (release_dir / "python").is_dir()
    assert result.bundled_python_mode == "placeholder-empty"

    requirements_text = (release_dir / "app" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    assert "torch==2.12.1" in requirements_text
    assert "onnxruntime>=1.22,<2" in requirements_text
    assert "openvino>=2026.1.0" in requirements_text
    assert "tensorrt-cu12==10.16.1.11" in requirements_text

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
        assert (
            release_dir / "manifests" / "worker-profiles" / f"{profile_id}.json"
        ).is_file()
        assert not (
            release_dir / "launchers" / "worker" / f"start-{profile_id}-worker.bat"
        ).exists()
        assert not (
            release_dir / "launchers" / "worker" / f"start-{profile_id}-worker.sh"
        ).exists()

    release_manifest = json.loads(
        (
            release_dir
            / "manifests"
            / "release-profiles"
            / "full-windows-x64-nvidia.json"
        ).read_text(encoding="utf-8")
    )
    assert release_manifest["profile_id"] == "full-windows-x64-nvidia"
    assert release_manifest["target"] == {
        "os": "windows",
        "arch": "x64",
        "platform_tag": "windows-x64",
    }
    assert release_manifest["accelerator"] == {"kind": "nvidia"}
    assert release_manifest["requirements_file"] == "app/requirements.txt"
    assert release_manifest["bundled_python"] == {
        "python_dir": "python",
        "mode": "placeholder-empty",
        "included": False,
        "managed_manually": True,
    }
    assert release_manifest["layout"]["custom_nodes_dir"] == "custom_nodes"
    assert release_manifest["layout"]["python_dir"] == "python"
    assert (
        release_manifest["service"]["windows_launcher"]
        == "launchers/service/start-backend-service.bat"
    )
    assert release_manifest["service"]["log_pattern"] == (
        "logs/full-stack/backend-service-YYYYMMDD.log"
    )
    assert release_manifest["inference_daemon"]["python_launcher"] == (
        "launchers/inference/start_inference_daemon.py"
    )
    assert release_manifest["inference_daemon"]["windows_launcher"] == (
        "launchers/inference/start-inference-daemon.bat"
    )
    assert release_manifest["inference_daemon"]["log_pattern"] == (
        "logs/full-stack/inference-daemon-YYYYMMDD.log"
    )
    assert release_manifest["stack"]["windows_launcher"] == "start-amvision-full.bat"
    assert (
        release_manifest["stack"]["stop_windows_launcher"] == "stop-amvision-full.bat"
    )
    assert (
        release_manifest["stack"]["state_file"] == "logs/full-stack/runtime-state.json"
    )
    assert [worker["profile_id"] for worker in release_manifest["workers"]] == list(
        expected_worker_profile_ids
    )
    assert (
        release_manifest["workers"][0]["python_launcher"]
        == "launchers/worker/start_backend_worker.py"
    )
    assert release_manifest["workers"][0]["log_pattern"] == (
        "logs/full-stack/backend-worker-dataset-import-YYYYMMDD.log"
    )
    start_batch_text = (release_dir / "start-amvision-full.bat").read_text(
        encoding="utf-8"
    )
    assert 'set "PYTHON_EXE=python"' not in start_batch_text
    assert "bundled Python not found" in start_batch_text
    start_python_text = (release_dir / "start_amvision_full.py").read_text(
        encoding="utf-8"
    )
    main_offset = start_python_text.index("def main(")
    migration_offset = start_python_text.index("_run_database_migration(", main_offset)
    daemon_start_offset = start_python_text.index("_start_component(", migration_offset)
    assert migration_offset < daemon_start_offset


def test_assemble_release_rejects_reserved_ubuntu_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 Ubuntu profile 位置可预留，但当前阶段不会误组装未实现的包。"""

    source_profile_dir = tmp_path / "release-profiles"
    source_profile_dir.mkdir(parents=True, exist_ok=True)
    (source_profile_dir / "full-ubuntu-x64-cpu.json").write_text(
        json.dumps(
            {
                "profile_id": "full-ubuntu-x64-cpu",
                "target": {
                    "os": "ubuntu",
                    "arch": "x64",
                    "platform_tag": "ubuntu-x64",
                },
                "accelerator": {"kind": "cpu"},
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        release_assembly,
        "SOURCE_RELEASE_PROFILES_DIR",
        source_profile_dir,
    )

    with pytest.raises(ValueError, match="尚未实现 release target"):
        assemble_release(
            ReleaseAssemblyRequest(
                profile_id="full-ubuntu-x64-cpu",
                output_root=tmp_path,
            )
        )


def test_assemble_release_windows_x64_cpu_excludes_nvidia_runtime_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 CPU-only profile 不复制 NVIDIA 运行时，也不会携带 CUDA/TensorRT requirements。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-cpu",
            output_root=tmp_path,
        )
    )

    release_dir = tmp_path / "full-windows-x64-cpu"
    assert result.release_dir == release_dir.resolve()
    assert (release_dir / "app" / "backend").is_dir()
    assert (release_dir / "frontend" / "index.html").is_file()
    assert (release_dir / "tools" / "ffmpeg" / "windows-x64" / "ffmpeg.exe").is_file()
    assert not (release_dir / "tools" / "tensorrt").exists()
    assert not (release_dir / "tools" / "cudnn").exists()
    assert not (release_dir / "tools" / "ffmpeg" / "linux-x64").exists()
    assert not (release_dir / "start-amvision-full.sh").exists()

    requirements_text = (release_dir / "app" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    assert "tensorrt-cu12==" not in requirements_text
    assert "cuda-python==" not in requirements_text
    assert "onnxruntime>=1.22,<2" in requirements_text
    assert "openvino>=2026.1.0" in requirements_text
    assert "torch==2.12.1" in requirements_text

    assert result.worker_profile_ids == (
        "dataset-import",
        "dataset-export",
        "training",
        "conversion",
        "evaluation",
        "inference",
    )
    assert (release_dir / "manifests" / "worker-profiles" / "training.json").is_file()
    assert not (
        release_dir / "launchers" / "worker" / "start-training-worker.bat"
    ).exists()

    release_manifest = json.loads(
        (
            release_dir / "manifests" / "release-profiles" / "full-windows-x64-cpu.json"
        ).read_text(encoding="utf-8")
    )
    assert release_manifest["artifacts"]["include_tensorrt_runtime"] is False
    assert release_manifest["artifacts"]["include_cudnn_runtime"] is False
    assert release_manifest["accelerator"] == {"kind": "cpu"}
    assert release_manifest["artifacts"]["requirements_exclude_packages"] == []
    assert [worker["profile_id"] for worker in release_manifest["workers"]] == [
        "dataset-import",
        "dataset-export",
        "training",
        "conversion",
        "evaluation",
        "inference",
    ]


def test_validate_layout_reports_target_specific_required_and_forbidden_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证布局检查会识别 Windows CPU 包所需路径和禁止混入的资产。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-cpu",
            output_root=tmp_path,
        )
    )
    (result.release_dir / "python" / "python.exe").write_text(
        "python", encoding="utf-8"
    )
    monkeypatch.chdir(result.release_dir)
    runtime = SimpleNamespace(workspace_dir=result.release_dir)

    layout_result = run_command("validate-layout", runtime)

    assert layout_result["target"]["platform_tag"] == "windows-x64"
    assert layout_result["accelerator"] == {"kind": "cpu"}
    assert layout_result["paths"]["root_readme"]["exists"] is True
    assert layout_result["paths"]["python_executable"]["exists"] is True
    assert layout_result["paths"]["ffmpeg_tools"]["exists"] is True
    assert all(
        entry["valid"] is True for entry in layout_result["forbidden_paths"].values()
    )

    (result.release_dir / "tools" / "tensorrt").mkdir(parents=True)
    invalid_layout_result = run_command("validate-layout", runtime)
    assert (
        invalid_layout_result["forbidden_paths"]["cpu_tensorrt_tools"]["valid"] is False
    )


def test_assemble_release_requires_force_to_overwrite_existing_directory(
    tmp_path: Path,
) -> None:
    """验证 release 目录已存在时必须显式允许覆盖。"""

    release_dir = tmp_path / "full-windows-x64-nvidia"
    release_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(FileExistsError):
        assemble_release(
            ReleaseAssemblyRequest(
                profile_id="full-windows-x64-nvidia",
                output_root=tmp_path,
            )
        )


def test_assemble_release_preserves_existing_python_dir_when_overwriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证覆盖发布时会保留已有 python 目录内容。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    release_dir = tmp_path / "full-windows-x64-nvidia"
    existing_python_dir = release_dir / "python"
    existing_python_dir.mkdir(parents=True, exist_ok=True)
    marker_file = existing_python_dir / "marker.txt"
    marker_file.write_text("keep", encoding="utf-8")

    stale_file = release_dir / "app" / "stale.txt"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text("stale", encoding="utf-8")

    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-nvidia",
            output_root=tmp_path,
            overwrite=True,
        )
    )

    assert result.bundled_python_dir == (release_dir / "python").resolve()
    assert result.bundled_python_mode == "placeholder-empty"
    assert marker_file.read_text(encoding="utf-8") == "keep"
    assert not stale_file.exists()
    assert (release_dir / "app" / "backend").is_dir()
    assert (release_dir / "custom_nodes" / "opencv_nodes" / "manifest.json").is_file()
    assert (
        release_dir / "custom_nodes" / "opencv_nodes" / "categories" / "geometry"
    ).is_dir()
    assert (
        release_dir
        / "custom_nodes"
        / "opencv_nodes"
        / "shared"
        / "backend"
        / "runtime"
        / "images.py"
    ).is_file()


def test_assemble_release_marks_preserved_python_with_executable_as_included(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证只有可启动的既有 Python 运行时才会标记为已包含。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    release_dir = tmp_path / "full-windows-x64-nvidia"
    existing_python_dir = release_dir / "python"
    existing_python_dir.mkdir(parents=True, exist_ok=True)
    (existing_python_dir / "python.exe").write_bytes(b"test-python")

    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-nvidia",
            output_root=tmp_path,
            overwrite=True,
        )
    )

    release_manifest = json.loads(
        result.release_manifest_path.read_text(encoding="utf-8")
    )
    assert result.bundled_python_mode == "preserved-existing"
    assert release_manifest["bundled_python"]["included"] is True


def test_assemble_release_recovers_existing_python_dir_when_overwrite_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证覆盖发布失败时会把原有 python 目录恢复回来。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    release_dir = tmp_path / "full-windows-x64-nvidia"
    existing_python_dir = release_dir / "python"
    existing_python_dir.mkdir(parents=True, exist_ok=True)
    marker_file = existing_python_dir / "marker.txt"
    marker_file.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(
        release_assembly, "SOURCE_FRONTEND_DIST_DIR", tmp_path / "missing-frontend-dist"
    )

    with pytest.raises(FileNotFoundError):
        assemble_release(
            ReleaseAssemblyRequest(
                profile_id="full-windows-x64-nvidia",
                output_root=tmp_path,
                overwrite=True,
            )
        )

    assert marker_file.read_text(encoding="utf-8") == "keep"


def test_assemble_release_recovers_python_when_old_release_removal_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证删除旧发布目录失败时也会立刻恢复已移动的 bundled Python。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    release_dir = tmp_path / "full-windows-x64-nvidia"
    existing_python_dir = release_dir / "python"
    existing_python_dir.mkdir(parents=True, exist_ok=True)
    marker_file = existing_python_dir / "marker.txt"
    marker_file.write_text("keep", encoding="utf-8")
    locked_file = release_dir / "data" / "locked.db"
    locked_file.parent.mkdir(parents=True, exist_ok=True)
    locked_file.write_text("locked", encoding="utf-8")

    original_rmtree = release_assembly.shutil.rmtree

    def _fail_old_release_removal(
        path: object, *args: object, **kwargs: object
    ) -> None:
        if Path(path).resolve() == release_dir.resolve():
            raise PermissionError("simulated locked release file")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(release_assembly.shutil, "rmtree", _fail_old_release_removal)

    with pytest.raises(PermissionError, match="simulated locked release file"):
        assemble_release(
            ReleaseAssemblyRequest(
                profile_id="full-windows-x64-nvidia",
                output_root=tmp_path,
                overwrite=True,
            )
        )

    assert marker_file.read_text(encoding="utf-8") == "keep"


def test_release_full_stop_requests_root_cleanup_before_stopping_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """验证 stop 脚本由 root 优雅回收全部组件，不制造 Worker 恢复窗口。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-nvidia",
            output_root=tmp_path,
        )
    )

    release_dir = tmp_path / "full-windows-x64-nvidia"
    stop_script_path = release_dir / "stop_amvision_full.py"
    stop_module = _load_module_from_file("release_full_stop_script", stop_script_path)

    state_file_path = release_dir / "logs" / "stop-test" / "runtime-state.json"
    state_file_path.parent.mkdir(parents=True, exist_ok=True)
    state_file_path.write_text(
        json.dumps(
            {
                "format_id": "amvision.full-supervisor-state.v1",
                "root_process": {"pid": 99, "kind": "root"},
                "components": [
                    {
                        "name": "backend-service",
                        "process": {"pid": 11, "kind": "service"},
                        "stop_mode": "process-tree",
                    },
                    {
                        "name": "backend-worker:training",
                        "process": {"pid": 12, "kind": "worker"},
                        "stop_mode": "process-tree",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    live_pids = {11, 12, 99}
    recorded_stop_calls: list[tuple[int, str, float]] = []
    recorded_root_wait_calls: list[tuple[int, float]] = []

    monkeypatch.setattr(
        stop_module,
        "process_identity_matches",
        lambda identity: identity.get("pid") in live_pids,
    )

    def _fake_stop_recorded_process(
        identity: dict[str, object],
        *,
        stop_mode: str,
        graceful_timeout_seconds: float,
    ) -> bool:
        recorded_stop_calls.append(
            (int(identity["pid"]), stop_mode, graceful_timeout_seconds)
        )
        return True

    def _fake_wait_root_process_exit(
        identity: dict[str, object],
        *,
        graceful_timeout_seconds: float,
    ) -> bool:
        recorded_root_wait_calls.append(
            (int(identity["pid"]), graceful_timeout_seconds)
        )
        live_pids.clear()
        return True

    monkeypatch.setattr(
        stop_module, "_stop_recorded_process", _fake_stop_recorded_process
    )
    monkeypatch.setattr(
        stop_module, "_wait_root_process_exit", _fake_wait_root_process_exit
    )

    exit_code = stop_module.main(
        [
            "--app-root",
            str(release_dir),
            "--logs-subdir",
            "stop-test",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert recorded_stop_calls == []
    assert recorded_root_wait_calls == [(99, 30.0)]
    assert "已请求 full-stack-root 优雅停止" in captured.out
    assert "full-stack-root 未在等待窗口内退出" not in captured.out
    assert "停止 full-stack-root 超时" not in captured.out
    assert "已停止 full-stack-root，pid=99" in captured.out
    assert not state_file_path.exists()
    assert not stop_module._resolve_shutdown_request_file(state_file_path).exists()


def test_release_full_stop_timeout_stops_root_before_residual_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证优雅停止超时后先关闭 root，避免清理 Worker 时被重新拉起。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-nvidia",
            output_root=tmp_path,
        )
    )
    stop_module = _load_module_from_file(
        "release_full_stop_timeout", result.release_dir / "stop_amvision_full.py"
    )
    state_file_path = result.release_dir / "logs" / "timeout" / "runtime-state.json"
    state_file_path.parent.mkdir(parents=True, exist_ok=True)
    state_file_path.write_text(
        json.dumps(
            {
                "format_id": "amvision.full-supervisor-state.v1",
                "root_process": {"pid": 99},
                "components": [
                    {"name": "service", "process": {"pid": 11}},
                    {"name": "worker", "process": {"pid": 12}},
                ],
            }
        ),
        encoding="utf-8",
    )
    live_pids = {11, 12, 99}
    stop_calls: list[int] = []
    monkeypatch.setattr(
        stop_module,
        "process_identity_matches",
        lambda identity: identity.get("pid") in live_pids,
    )
    monkeypatch.setattr(stop_module, "_wait_root_process_exit", lambda *a, **k: False)

    def _stop(
        identity: dict[str, object],
        *,
        stop_mode: str,
        graceful_timeout_seconds: float,
    ) -> bool:
        del stop_mode, graceful_timeout_seconds
        pid = int(identity["pid"])
        stop_calls.append(pid)
        live_pids.discard(pid)
        return True

    monkeypatch.setattr(stop_module, "_stop_recorded_process", _stop)

    assert (
        stop_module.main(
            ["--app-root", str(result.release_dir), "--logs-subdir", "timeout"]
        )
        == 0
    )
    assert stop_calls == [99, 12, 11]


def test_release_full_shutdown_request_targets_exact_root_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证旧 Supervisor 的停止请求不会终止新启动实例。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-cpu",
            output_root=tmp_path,
        )
    )
    start_module = _load_module_from_file(
        "release_full_shutdown_request", result.release_dir / "start_amvision_full.py"
    )
    request_path = tmp_path / "runtime-state.shutdown-request.json"
    current_identity = {"pid": 99, "create_time": 123.0}
    request_path.write_text(
        json.dumps(
            {
                "format_id": "amvision.full-supervisor-shutdown.v1",
                "root_process": current_identity,
            }
        ),
        encoding="utf-8",
    )

    assert (
        start_module._shutdown_requested(
            request_path, root_process_identity=current_identity
        )
        is True
    )
    assert (
        start_module._shutdown_requested(
            request_path,
            root_process_identity={"pid": 100, "create_time": 124.0},
        )
        is False
    )


def test_release_full_start_resolves_the_only_generated_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证根启动器直接使用发布目录中唯一的目标 manifest。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-cpu",
            output_root=tmp_path,
        )
    )
    start_module = _load_module_from_file(
        "release_full_start_script",
        result.release_dir / "start_amvision_full.py",
    )

    manifest_path = start_module._resolve_release_manifest_path(
        result.release_dir, None
    )

    assert manifest_path == result.release_manifest_path


def test_release_full_forwards_explicit_python_to_service_and_worker_launchers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 Supervisor 不会让二级 launcher 回退解析 bundled Python。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-cpu",
            output_root=tmp_path,
        )
    )
    start_module = _load_module_from_file(
        "release_full_explicit_python",
        result.release_dir / "start_amvision_full.py",
    )
    manifest = json.loads(result.release_manifest_path.read_text(encoding="utf-8"))
    python_executable = str((tmp_path / "runtime" / "python.exe").resolve())

    service_command = start_module._build_service_command(
        result.release_dir,
        manifest,
        python_executable=python_executable,
        host="127.0.0.1",
        port=6600,
        service_log_level="info",
    )
    worker_command = start_module._build_worker_command(
        result.release_dir,
        manifest["workers"][0],
        python_executable=python_executable,
        topology=SimpleNamespace(
            topology_id="amvision-backend-workers",
            topology_generation=1,
            topology_epoch_id="topology-epoch-1234567890",
        ),
        worker_instance_id="worker-instance-1234567890",
        worker_runtime_root=result.release_dir / "data" / "runtime",
    )

    for command in (service_command, worker_command):
        assert command[0] == python_executable
        assert command[command.index("--app-root") + 1] == str(result.release_dir)
        assert command[command.index("--python-executable") + 1] == python_executable


def test_release_full_child_environment_removes_parent_conda_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证生产子进程不会继承发布机 conda 环境标记。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-cpu",
            output_root=tmp_path,
        )
    )
    start_module = _load_module_from_file(
        "release_full_sanitized_environment",
        result.release_dir / "start_amvision_full.py",
    )
    monkeypatch.setenv("CONDA_PREFIX", "D:/external/conda/envs/amvision")
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "amvision")
    monkeypatch.setenv("_CE_CONDA", "conda")

    environment = start_module._build_child_process_environment()

    assert "CONDA_PREFIX" not in environment
    assert "CONDA_DEFAULT_ENV" not in environment
    assert "_CE_CONDA" not in environment


def test_release_worker_launcher_imports_backend_from_release_app_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证发行布局中的 Worker launcher 从 app/ 导入 backend。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-cpu",
            output_root=tmp_path,
        )
    )
    worker_module = _load_module_from_file(
        "release_worker_code_root",
        result.release_dir / "launchers" / "worker" / "start_backend_worker.py",
    )
    monkeypatch.setattr(
        worker_module,
        "ensure_windows_long_paths_enabled",
        lambda **_kwargs: True,
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        worker_module,
        "run_python_module",
        lambda **kwargs: calls.append(kwargs) or 0,
    )
    python_executable = str((tmp_path / "runtime" / "python.exe").resolve())

    exit_code = worker_module.main(
        [
            "--app-root",
            str(result.release_dir),
            "--python-executable",
            python_executable,
            "--worker-profile-file",
            "manifests/worker-profiles/dataset-import.json",
            "--topology-id",
            "amvision-backend-workers",
            "--topology-generation",
            "1",
            "--topology-epoch-id",
            "topology-epoch-1234567890",
            "--worker-instance-id",
            "worker-instance-1234567890",
            "--worker-runtime-root",
            "data/runtime/backend-workers",
        ]
    )

    assert exit_code == 0
    assert calls[0]["app_root"] == result.release_dir
    assert calls[0]["python_executable"] == python_executable
    assert str(result.release_dir / "app") in sys.path


def test_release_full_worker_readiness_uses_current_epoch_heartbeat_not_log_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 Worker 就绪只读取当前 epoch 严格心跳，不解析历史日志。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-cpu",
            output_root=tmp_path,
        )
    )
    start_text = (result.release_dir / "start_amvision_full.py").read_text(
        encoding="utf-8"
    )

    assert "contracts.load_worker_heartbeat" in start_text
    assert 'ready_marker = "backend-worker ready"' not in start_text


def test_release_full_start_cleans_started_daemon_when_readiness_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 daemon 初始化或 probe 失败时记录 pid 并回收已经启动的进程。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-cpu",
            output_root=tmp_path,
        )
    )
    bundled_python = result.release_dir / "python" / "python.exe"
    bundled_python.write_bytes(b"test-python")
    start_module = _load_module_from_file(
        "release_full_start_cleanup",
        result.release_dir / "start_amvision_full.py",
    )
    monkeypatch.setattr(
        start_module,
        "ensure_windows_long_paths_enabled",
        lambda **_kwargs: True,
    )
    fake_process = SimpleNamespace(pid=321, poll=lambda: None)
    fake_log_capture = SimpleNamespace(
        current_log_path=result.release_dir
        / "logs"
        / "startup-failure"
        / "daemon-20260820.log",
        log_pattern="daemon-YYYYMMDD.log",
        close=lambda: None,
        tail_text=lambda: "",
        assert_healthy=lambda: None,
    )
    stopped_processes: list[object] = []
    monkeypatch.setattr(start_module, "_run_database_migration", lambda **_kwargs: None)
    monkeypatch.setattr(
        start_module,
        "_start_component",
        lambda *_args, **_kwargs: (fake_process, fake_log_capture),
    )
    monkeypatch.setattr(
        start_module,
        "read_process_identity",
        lambda pid: {
            "pid": pid,
            "create_time": 1.0,
            "executable": "python",
            "working_directory": str(result.release_dir),
            "command_line": ["python"],
        },
    )
    monkeypatch.setattr(
        start_module,
        "_stop_component",
        lambda process: stopped_processes.append(process),
    )

    def fail_daemon_ready(**_kwargs) -> None:
        state_path = (
            result.release_dir / "logs" / "startup-failure" / "runtime-state.json"
        )
        state_payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert state_payload["components"][0]["name"] == "inference-daemon"
        assert state_payload["components"][0]["process"]["pid"] == 321
        raise RuntimeError("daemon probe failed")

    monkeypatch.setattr(
        start_module, "_wait_for_inference_daemon_ready", fail_daemon_ready
    )

    with pytest.raises(RuntimeError, match="daemon probe failed"):
        start_module.main(
            [
                "--app-root",
                str(result.release_dir),
                "--logs-subdir",
                "startup-failure",
            ]
        )

    assert stopped_processes == [fake_process]
    assert not (
        result.release_dir / "logs" / "startup-failure" / "runtime-state.json"
    ).exists()


def test_release_full_database_migration_failure_prevents_component_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 migration 非零退出时 full launcher 不会启动任何常驻组件。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-windows-x64-cpu",
            output_root=tmp_path,
        )
    )
    (result.release_dir / "python" / "python.exe").write_bytes(b"test-python")
    start_module = _load_module_from_file(
        "release_full_migration_failure",
        result.release_dir / "start_amvision_full.py",
    )
    monkeypatch.setattr(
        start_module,
        "ensure_windows_long_paths_enabled",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        start_module,
        "_run_database_migration",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("migration failed")),
    )
    monkeypatch.setattr(
        start_module,
        "_start_component",
        lambda *_args, **_kwargs: pytest.fail("migration 失败后不应启动组件"),
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        start_module.main(["--app-root", str(result.release_dir)])


def _patch_release_runtime_asset_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """用轻量测试目录替换 release 组装使用的运行期资产源目录。"""

    source_custom_nodes_dir = tmp_path / "source-custom-nodes"
    (source_custom_nodes_dir / "opencv_nodes" / "categories" / "geometry").mkdir(
        parents=True, exist_ok=True
    )
    (source_custom_nodes_dir / "opencv_nodes" / "manifest.json").write_text(
        '{"id": "opencv.nodes"}\n',
        encoding="utf-8",
    )
    (source_custom_nodes_dir / "opencv_nodes" / "shared" / "backend" / "runtime").mkdir(
        parents=True, exist_ok=True
    )
    (
        source_custom_nodes_dir
        / "opencv_nodes"
        / "shared"
        / "backend"
        / "runtime"
        / "images.py"
    ).write_text(
        '"""shared image runtime"""\n',
        encoding="utf-8",
    )
    (source_custom_nodes_dir / "opencv_nodes" / "shared" / "workflow").mkdir(
        parents=True, exist_ok=True
    )
    (
        source_custom_nodes_dir
        / "opencv_nodes"
        / "shared"
        / "workflow"
        / "payload_contracts.json"
    ).write_text(
        "{}\n",
        encoding="utf-8",
    )
    (source_custom_nodes_dir / "_scaffold").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "_scaffold" / "README.md").write_text(
        "template\n", encoding="utf-8"
    )
    (source_custom_nodes_dir / "__pycache__").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "__pycache__" / "cached.pyc").write_bytes(b"cache")

    monkeypatch.setattr(
        release_assembly, "SOURCE_CUSTOM_NODES_DIR", source_custom_nodes_dir
    )

    source_frontend_dist_dir = tmp_path / "source-frontend-dist"
    (source_frontend_dist_dir / "assets").mkdir(parents=True, exist_ok=True)
    (source_frontend_dist_dir / "index.html").write_text(
        "<html>frontend</html>\n", encoding="utf-8"
    )
    (source_frontend_dist_dir / "assets" / "app.js").write_text(
        "console.log('app')\n", encoding="utf-8"
    )
    (source_frontend_dist_dir / "runtime-config.template.json").write_text(
        '{"apiBaseUrl": "http://127.0.0.1:5600/api/v1"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        release_assembly, "SOURCE_FRONTEND_DIST_DIR", source_frontend_dist_dir
    )

    source_frontend_runtime_config_template_file = (
        tmp_path / "runtime-config.template.json"
    )
    source_frontend_runtime_config_template_file.write_text(
        '{"apiBaseUrl": "http://127.0.0.1:5600/api/v1", "wsBaseUrl": "ws://127.0.0.1:5600/ws/v1"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        release_assembly,
        "SOURCE_FRONTEND_RUNTIME_CONFIG_TEMPLATE_FILE",
        source_frontend_runtime_config_template_file,
    )
    monkeypatch.setattr(
        release_assembly,
        "SOURCE_FRONTEND_RUNTIME_CONFIG_LOCAL_FILE",
        tmp_path / "runtime-config.local.json",
    )

    source_ffmpeg_runtime_dir = tmp_path / "source-ffmpeg"
    (source_ffmpeg_runtime_dir / "windows-x64").mkdir(parents=True, exist_ok=True)
    (source_ffmpeg_runtime_dir / "linux-x64").mkdir(parents=True, exist_ok=True)
    (source_ffmpeg_runtime_dir / "windows-x64" / "ffmpeg.exe").write_text(
        "ffmpeg", encoding="utf-8"
    )
    (source_ffmpeg_runtime_dir / "windows-x64" / "ffprobe.exe").write_text(
        "ffprobe", encoding="utf-8"
    )
    (source_ffmpeg_runtime_dir / "linux-x64" / "ffmpeg").write_text(
        "ffmpeg", encoding="utf-8"
    )
    (source_ffmpeg_runtime_dir / "linux-x64" / "ffprobe").write_text(
        "ffprobe", encoding="utf-8"
    )
    monkeypatch.setattr(
        release_assembly, "SOURCE_FFMPEG_RUNTIME_DIR", source_ffmpeg_runtime_dir
    )

    source_tensorrt_runtime_dir = tmp_path / "source-tensorrt"
    (source_tensorrt_runtime_dir / "bin").mkdir(parents=True, exist_ok=True)
    (source_tensorrt_runtime_dir / "python").mkdir(parents=True, exist_ok=True)
    (source_tensorrt_runtime_dir / "doc").mkdir(parents=True, exist_ok=True)
    (source_tensorrt_runtime_dir / "include").mkdir(parents=True, exist_ok=True)
    (source_tensorrt_runtime_dir / "lib").mkdir(parents=True, exist_ok=True)
    (source_tensorrt_runtime_dir / "bin" / "trtexec.exe").write_text(
        "trtexec", encoding="utf-8"
    )
    (source_tensorrt_runtime_dir / "bin" / "nvinfer_11.dll").write_text(
        "dll", encoding="utf-8"
    )
    (
        source_tensorrt_runtime_dir
        / "python"
        / "tensorrt-10.16.1.11-cp312-none-win_amd64.whl"
    ).write_text(
        "wheel",
        encoding="utf-8",
    )
    (source_tensorrt_runtime_dir / "doc" / "README.txt").write_text(
        "readme", encoding="utf-8"
    )
    (source_tensorrt_runtime_dir / "include" / "NvInfer.h").write_text(
        "header", encoding="utf-8"
    )
    (source_tensorrt_runtime_dir / "lib" / "nvinfer.lib").write_text(
        "lib", encoding="utf-8"
    )
    monkeypatch.setattr(
        release_assembly,
        "SOURCE_TENSORRT_RUNTIME_DIR",
        source_tensorrt_runtime_dir,
    )

    source_cudnn_runtime_dir = tmp_path / "source-cudnn"
    (source_cudnn_runtime_dir / "bin" / "12.9" / "x64").mkdir(
        parents=True, exist_ok=True
    )
    (source_cudnn_runtime_dir / "bin" / "13.2" / "x64").mkdir(
        parents=True, exist_ok=True
    )
    (source_cudnn_runtime_dir / "bin" / "12.9" / "x64" / "cudnn64_9.dll").write_text(
        "cudnn",
        encoding="utf-8",
    )
    (source_cudnn_runtime_dir / "LICENSE").write_text("license", encoding="utf-8")
    monkeypatch.setattr(
        release_assembly,
        "SOURCE_CUDNN_RUNTIME_DIR",
        source_cudnn_runtime_dir,
    )


def _load_module_from_file(module_name: str, file_path: Path) -> object:
    """从指定文件路径加载测试用模块。"""

    module_spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert module_spec is not None
    assert module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module
