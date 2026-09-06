"""独立 inference daemon launcher 测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from backend.inference_daemon import main as inference_daemon_main


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = (
    REPOSITORY_ROOT
    / "runtimes"
    / "launchers"
    / "inference"
    / "start_inference_daemon.py"
)


def _load_launcher_module(module_name: str) -> object:
    """从源码路径加载一次独立 launcher 模块。"""

    module_spec = importlib.util.spec_from_file_location(module_name, LAUNCHER_PATH)
    assert module_spec is not None
    assert module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("launcher_argument", "daemon_argument"),
    (
        ("--probe", "--probe"),
        ("--probe-local-buffer", "--probe-local-buffer"),
    ),
)
def test_launcher_runs_probes_inline(
    launcher_argument: str,
    daemon_argument: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两类 probe 都必须在 launcher 进程内精确转发。"""

    launcher = _load_launcher_module(
        f"inference_daemon_launcher_{daemon_argument.removeprefix('--').replace('-', '_')}"
    )
    captured_arguments: list[list[str] | None] = []
    monkeypatch.setattr(
        launcher,
        "ensure_windows_long_paths_enabled",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        launcher,
        "build_python_module_environment",
        lambda _app_root: {},
    )
    monkeypatch.setattr(inference_daemon_main, "main", captured_arguments.append)

    result = launcher.main(
        [launcher_argument, "--app-root", str(REPOSITORY_ROOT)]
    )

    assert result is None
    assert captured_arguments == [[daemon_argument]]


def test_launcher_forwards_check_to_python_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非 probe 模式继续使用统一 Python module launcher。"""

    launcher = _load_launcher_module("inference_daemon_launcher_check")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        launcher,
        "ensure_windows_long_paths_enabled",
        lambda **_kwargs: True,
    )

    def run_python_module(**kwargs: object) -> int:
        captured.update(kwargs)
        return 17

    monkeypatch.setattr(launcher, "run_python_module", run_python_module)

    result = launcher.main(["--check", "--app-root", str(REPOSITORY_ROOT)])

    assert result == 17
    assert captured["module_name"] == "backend.inference_daemon.main"
    assert captured["module_args"] == ["--check"]
