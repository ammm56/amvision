"""TensorRT 本地运行时目录解析测试。"""

from __future__ import annotations

import os

from backend.service.application.runtime.support.tensorrt_runtime import (
    CUDNN_BIN_DIR_ENV_VAR,
    TENSORRT_BIN_DIR_ENV_VAR,
    build_tensorrt_process_environment,
    resolve_cudnn_bin_dir,
    resolve_tensorrt_bin_dir,
)


def test_resolve_tensorrt_bin_dir_uses_release_tools_dir(tmp_path, monkeypatch) -> None:
    """优先解析发布目录中的 tools/tensorrt/bin。"""

    monkeypatch.delenv(TENSORRT_BIN_DIR_ENV_VAR, raising=False)
    tensorrt_bin_dir = tmp_path / "tools" / "tensorrt" / "bin"
    tensorrt_bin_dir.mkdir(parents=True)

    resolved_bin_dir = resolve_tensorrt_bin_dir(app_root=tmp_path, required=True)

    assert resolved_bin_dir == tensorrt_bin_dir.resolve()


def test_build_tensorrt_process_environment_prepends_bin_dir(tmp_path, monkeypatch) -> None:
    """构造子进程环境时会把 TensorRT bin 加到 PATH 前面。"""

    monkeypatch.delenv(TENSORRT_BIN_DIR_ENV_VAR, raising=False)
    monkeypatch.delenv(CUDNN_BIN_DIR_ENV_VAR, raising=False)
    tensorrt_bin_dir = tmp_path / "tools" / "tensorrt" / "bin"
    tensorrt_bin_dir.mkdir(parents=True)
    cudnn_bin_dir = tmp_path / "tools" / "cudnn" / "bin" / "12.9" / "x64"
    cudnn_bin_dir.mkdir(parents=True)

    runtime_env = build_tensorrt_process_environment(
        base_env={"PATH": "original-path"},
        app_root=tmp_path,
    )

    path_parts = runtime_env["PATH"].split(os.pathsep)
    assert path_parts[:2] == [str(tensorrt_bin_dir.resolve()), str(cudnn_bin_dir.resolve())]
    assert runtime_env[TENSORRT_BIN_DIR_ENV_VAR] == str(tensorrt_bin_dir.resolve())
    assert runtime_env[CUDNN_BIN_DIR_ENV_VAR] == str(cudnn_bin_dir.resolve())


def test_resolve_cudnn_bin_dir_prefers_cuda_129_layout(tmp_path, monkeypatch) -> None:
    """默认优先解析项目约定的 cuDNN CUDA 12.9 DLL 目录。"""

    monkeypatch.delenv(CUDNN_BIN_DIR_ENV_VAR, raising=False)
    cudnn_bin_dir = tmp_path / "tools" / "cudnn" / "bin" / "12.9" / "x64"
    cudnn_bin_dir.mkdir(parents=True)
    (tmp_path / "tools" / "cudnn" / "bin" / "13.2" / "x64").mkdir(parents=True)

    resolved_bin_dir = resolve_cudnn_bin_dir(app_root=tmp_path, required=True)

    assert resolved_bin_dir == cudnn_bin_dir.resolve()
