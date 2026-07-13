"""release 组装流程测试。"""

from __future__ import annotations

import importlib.util
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
    assert (release_dir / "custom_nodes" / "opencv_geometry_nodes" / "manifest.json").is_file()
    assert (release_dir / "custom_nodes" / "opencv_measurement_nodes" / "manifest.json").is_file()
    assert (release_dir / "custom_nodes" / "opencv_shape_nodes" / "manifest.json").is_file()
    assert (release_dir / "custom_nodes" / "opencv_defect_nodes" / "manifest.json").is_file()
    assert (release_dir / "custom_nodes" / "opencv_matching_nodes" / "manifest.json").is_file()
    assert (release_dir / "custom_nodes" / "_opencv_shared" / "backend" / "runtime" / "images.py").is_file()
    assert (release_dir / "custom_nodes" / "_opencv_shared" / "workflow" / "payload_contracts.json").is_file()
    assert (release_dir / "custom_nodes" / "_scaffold" / "README.md").is_file()
    assert not (release_dir / "custom_nodes" / "__pycache__").exists()
    assert (release_dir / "tools" / "ffmpeg" / "windows-x64" / "ffmpeg.exe").is_file()
    assert (release_dir / "tools" / "ffmpeg" / "linux-x64" / "ffprobe").is_file()
    assert (release_dir / "tools" / "tensorrt" / "bin" / "trtexec.exe").is_file()
    assert (
        release_dir / "tools" / "tensorrt" / "python" / "tensorrt-10.16.1.11-cp312.whl"
    ).is_file()
    assert (release_dir / "tools" / "tensorrt" / "doc" / "README.txt").is_file()
    assert not (release_dir / "tools" / "tensorrt" / "include").exists()
    assert not (release_dir / "tools" / "tensorrt" / "lib").exists()
    assert (release_dir / "tools" / "cudnn" / "bin" / "12.9" / "x64" / "cudnn64_9.dll").is_file()
    assert (release_dir / "tools" / "cudnn" / "LICENSE").is_file()
    assert (release_dir / "frontend" / "index.html").is_file()
    assert (release_dir / "frontend" / "runtime-config.json").is_file()
    assert (release_dir / "python").is_dir()
    assert result.bundled_python_mode == "placeholder-empty"

    requirements_text = (release_dir / "app" / "requirements.txt").read_text(encoding="utf-8")
    assert "torch==2.8.0" in requirements_text
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


def test_assemble_release_cpu_profile_excludes_nvidia_runtime_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 CPU-only profile 不复制 NVIDIA 运行时，也不会携带 CUDA/TensorRT requirements。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full-cpu",
            output_root=tmp_path,
        )
    )

    release_dir = tmp_path / "full-cpu"
    assert result.release_dir == release_dir.resolve()
    assert (release_dir / "app" / "backend").is_dir()
    assert (release_dir / "frontend" / "index.html").is_file()
    assert (release_dir / "tools" / "ffmpeg" / "windows-x64" / "ffmpeg.exe").is_file()
    assert not (release_dir / "tools" / "tensorrt").exists()
    assert not (release_dir / "tools" / "cudnn").exists()

    requirements_text = (release_dir / "app" / "requirements.txt").read_text(encoding="utf-8")
    assert "tensorrt-cu12==" not in requirements_text
    assert "cuda-python==" not in requirements_text
    assert "onnxruntime>=1.22,<2" in requirements_text
    assert "openvino>=2026.1.0" in requirements_text
    assert "当前 release profile 已排除这些 GPU-only 依赖" in requirements_text

    assert result.worker_profile_ids == ("dataset-import", "dataset-export", "inference")
    assert (release_dir / "manifests" / "worker-profiles" / "dataset-import.json").is_file()
    assert (release_dir / "manifests" / "worker-profiles" / "dataset-export.json").is_file()
    assert (release_dir / "manifests" / "worker-profiles" / "inference.json").is_file()
    assert not (release_dir / "manifests" / "worker-profiles" / "training.json").exists()
    assert not (release_dir / "launchers" / "worker" / "start-training-worker.bat").exists()

    release_manifest = json.loads(
        (release_dir / "manifests" / "release-profiles" / "full-cpu.json").read_text(
            encoding="utf-8"
        )
    )
    assert release_manifest["artifacts"]["include_tensorrt_runtime"] is False
    assert release_manifest["artifacts"]["include_cudnn_runtime"] is False
    assert release_manifest["artifacts"]["requirements_exclude_packages"] == [
        "tensorrt-cu12",
        "cuda-python",
    ]
    assert [worker["profile_id"] for worker in release_manifest["workers"]] == [
        "dataset-import",
        "dataset-export",
        "inference",
    ]


def test_assemble_release_copies_bundled_python_from_explicit_source_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证显式提供 bundled Python 来源目录时会直接复制运行时。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    bundled_python_source_dir = tmp_path / "source-python"
    bundled_python_source_dir.mkdir(parents=True, exist_ok=True)
    (bundled_python_source_dir / "python.exe").write_text("python", encoding="utf-8")
    (bundled_python_source_dir / "__pycache__").mkdir(parents=True, exist_ok=True)
    (bundled_python_source_dir / "__pycache__" / "ignored.pyc").write_bytes(b"cache")

    result = assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full",
            output_root=tmp_path,
            bundled_python_source_dir=bundled_python_source_dir,
        )
    )

    release_dir = tmp_path / "full"
    assert result.bundled_python_mode == "copied-from-source"
    assert (release_dir / "python" / "python.exe").is_file()
    assert not (release_dir / "python" / "__pycache__").exists()

    release_manifest = json.loads(
        (release_dir / "manifests" / "release-profiles" / "full.json").read_text(
            encoding="utf-8"
        )
    )
    assert release_manifest["bundled_python"] == {
        "python_dir": "python",
        "mode": "copied-from-source",
        "included": True,
        "managed_manually": False,
    }


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
    assert (release_dir / "custom_nodes" / "opencv_geometry_nodes" / "manifest.json").is_file()
    assert (release_dir / "custom_nodes" / "opencv_measurement_nodes" / "manifest.json").is_file()
    assert (release_dir / "custom_nodes" / "opencv_shape_nodes" / "manifest.json").is_file()
    assert (release_dir / "custom_nodes" / "opencv_defect_nodes" / "manifest.json").is_file()
    assert (release_dir / "custom_nodes" / "opencv_matching_nodes" / "manifest.json").is_file()
    assert (release_dir / "custom_nodes" / "_opencv_shared" / "backend" / "runtime" / "images.py").is_file()
    assert (release_dir / "custom_nodes" / "_opencv_shared" / "workflow" / "payload_contracts.json").is_file()


def test_assemble_release_recovers_existing_python_dir_when_overwrite_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证覆盖发布失败时会把原有 python 目录恢复回来。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    release_dir = tmp_path / "full"
    existing_python_dir = release_dir / "python"
    existing_python_dir.mkdir(parents=True, exist_ok=True)
    marker_file = existing_python_dir / "marker.txt"
    marker_file.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(release_assembly, "SOURCE_FRONTEND_DIST_DIR", tmp_path / "missing-frontend-dist")

    with pytest.raises(FileNotFoundError):
        assemble_release(
            ReleaseAssemblyRequest(
                profile_id="full",
                output_root=tmp_path,
                overwrite=True,
            )
        )

    assert marker_file.read_text(encoding="utf-8") == "keep"


def test_release_full_stop_waits_root_exit_before_force_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """验证 stop 脚本会先等待 root 自行退出，再决定是否强制停止。"""

    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    assemble_release(
        ReleaseAssemblyRequest(
            profile_id="full",
            output_root=tmp_path,
        )
    )

    release_dir = tmp_path / "full"
    stop_script_path = release_dir / "stop_amvision_full.py"
    stop_module = _load_module_from_file("release_full_stop_script", stop_script_path)

    state_file_path = release_dir / "logs" / "stop-test" / "runtime-state.json"
    state_file_path.parent.mkdir(parents=True, exist_ok=True)
    state_file_path.write_text(
        json.dumps(
            {
                "root_pid": 99,
                "components": [
                    {"name": "backend-service", "pid": 11, "stop_mode": "process-tree"},
                    {"name": "backend-worker:training", "pid": 12, "stop_mode": "process-tree"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    recorded_stop_calls: list[tuple[int, str, float]] = []
    recorded_root_wait_calls: list[tuple[int, float]] = []

    monkeypatch.setattr(stop_module, "_pid_is_alive", lambda pid: pid in {11, 12, 99})

    def _fake_stop_recorded_process(
        pid: int,
        *,
        stop_mode: str,
        graceful_timeout_seconds: float,
    ) -> bool:
        recorded_stop_calls.append((pid, stop_mode, graceful_timeout_seconds))
        return True

    def _fake_wait_root_process_exit(
        pid: int,
        *,
        graceful_timeout_seconds: float,
    ) -> bool:
        recorded_root_wait_calls.append((pid, graceful_timeout_seconds))
        return True

    monkeypatch.setattr(stop_module, "_stop_recorded_process", _fake_stop_recorded_process)
    monkeypatch.setattr(stop_module, "_wait_root_process_exit", _fake_wait_root_process_exit)

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
    assert recorded_stop_calls == [
        (12, "process-tree", 30.0),
        (11, "process-tree", 30.0),
    ]
    assert recorded_root_wait_calls == [(99, 30.0)]
    assert "等待 full-stack-root 自行退出" in captured.out
    assert "full-stack-root 未在等待窗口内退出" not in captured.out
    assert "停止 full-stack-root 超时" not in captured.out
    assert "已停止 full-stack-root，pid=99" in captured.out
    assert not state_file_path.exists()


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
    (source_custom_nodes_dir / "opencv_geometry_nodes").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "opencv_geometry_nodes" / "manifest.json").write_text(
        '{"id": "opencv.geometry-nodes"}\n',
        encoding="utf-8",
    )
    (source_custom_nodes_dir / "opencv_measurement_nodes").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "opencv_measurement_nodes" / "manifest.json").write_text(
        '{"id": "opencv.measurement-nodes"}\n',
        encoding="utf-8",
    )
    (source_custom_nodes_dir / "opencv_shape_nodes").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "opencv_shape_nodes" / "manifest.json").write_text(
        '{"id": "opencv.shape-nodes"}\n',
        encoding="utf-8",
    )
    (source_custom_nodes_dir / "opencv_defect_nodes").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "opencv_defect_nodes" / "manifest.json").write_text(
        '{"id": "opencv.defect-nodes"}\n',
        encoding="utf-8",
    )
    (source_custom_nodes_dir / "opencv_matching_nodes").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "opencv_matching_nodes" / "manifest.json").write_text(
        '{"id": "opencv.matching-nodes"}\n',
        encoding="utf-8",
    )
    (source_custom_nodes_dir / "_opencv_shared" / "backend" / "runtime").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "_opencv_shared" / "backend" / "runtime" / "images.py").write_text(
        '"""shared image runtime"""\n',
        encoding="utf-8",
    )
    (source_custom_nodes_dir / "_opencv_shared" / "workflow").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "_opencv_shared" / "workflow" / "payload_contracts.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (source_custom_nodes_dir / "_scaffold").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "_scaffold" / "README.md").write_text("template\n", encoding="utf-8")
    (source_custom_nodes_dir / "__pycache__").mkdir(parents=True, exist_ok=True)
    (source_custom_nodes_dir / "__pycache__" / "cached.pyc").write_bytes(b"cache")

    monkeypatch.setattr(release_assembly, "SOURCE_CUSTOM_NODES_DIR", source_custom_nodes_dir)

    source_frontend_dist_dir = tmp_path / "source-frontend-dist"
    (source_frontend_dist_dir / "assets").mkdir(parents=True, exist_ok=True)
    (source_frontend_dist_dir / "index.html").write_text("<html>frontend</html>\n", encoding="utf-8")
    (source_frontend_dist_dir / "assets" / "app.js").write_text("console.log('app')\n", encoding="utf-8")
    (source_frontend_dist_dir / "runtime-config.template.json").write_text(
        '{"apiBaseUrl": "http://127.0.0.1:8000/api/v1"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(release_assembly, "SOURCE_FRONTEND_DIST_DIR", source_frontend_dist_dir)

    source_frontend_runtime_config_template_file = tmp_path / "runtime-config.template.json"
    source_frontend_runtime_config_template_file.write_text(
        '{"apiBaseUrl": "http://127.0.0.1:8000/api/v1", "wsBaseUrl": "ws://127.0.0.1:8000/ws/v1"}\n',
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
    (source_ffmpeg_runtime_dir / "windows-x64" / "ffmpeg.exe").write_text("ffmpeg", encoding="utf-8")
    (source_ffmpeg_runtime_dir / "windows-x64" / "ffprobe.exe").write_text("ffprobe", encoding="utf-8")
    (source_ffmpeg_runtime_dir / "linux-x64" / "ffmpeg").write_text("ffmpeg", encoding="utf-8")
    (source_ffmpeg_runtime_dir / "linux-x64" / "ffprobe").write_text("ffprobe", encoding="utf-8")
    monkeypatch.setattr(release_assembly, "SOURCE_FFMPEG_RUNTIME_DIR", source_ffmpeg_runtime_dir)

    source_tensorrt_runtime_dir = tmp_path / "source-tensorrt"
    (source_tensorrt_runtime_dir / "bin").mkdir(parents=True, exist_ok=True)
    (source_tensorrt_runtime_dir / "python").mkdir(parents=True, exist_ok=True)
    (source_tensorrt_runtime_dir / "doc").mkdir(parents=True, exist_ok=True)
    (source_tensorrt_runtime_dir / "include").mkdir(parents=True, exist_ok=True)
    (source_tensorrt_runtime_dir / "lib").mkdir(parents=True, exist_ok=True)
    (source_tensorrt_runtime_dir / "bin" / "trtexec.exe").write_text("trtexec", encoding="utf-8")
    (source_tensorrt_runtime_dir / "bin" / "nvinfer_11.dll").write_text("dll", encoding="utf-8")
    (source_tensorrt_runtime_dir / "python" / "tensorrt-10.16.1.11-cp312.whl").write_text(
        "wheel",
        encoding="utf-8",
    )
    (source_tensorrt_runtime_dir / "doc" / "README.txt").write_text("readme", encoding="utf-8")
    (source_tensorrt_runtime_dir / "include" / "NvInfer.h").write_text("header", encoding="utf-8")
    (source_tensorrt_runtime_dir / "lib" / "nvinfer.lib").write_text("lib", encoding="utf-8")
    monkeypatch.setattr(
        release_assembly,
        "SOURCE_TENSORRT_RUNTIME_DIR",
        source_tensorrt_runtime_dir,
    )

    source_cudnn_runtime_dir = tmp_path / "source-cudnn"
    (source_cudnn_runtime_dir / "bin" / "12.9" / "x64").mkdir(parents=True, exist_ok=True)
    (source_cudnn_runtime_dir / "bin" / "13.2" / "x64").mkdir(parents=True, exist_ok=True)
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
