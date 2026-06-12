"""release/full 真实启动验收。

本文件只在显式指定时运行，用于现场调试前确认发布目录可以启动、
保持短时间驻留、返回基础 API，并通过 stop 脚本清理。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen

import psutil
import pytest


def test_release_full_stack_start_health_openapi_and_stop() -> None:
    """验证 release/full 可以启动、短时驻留并被 stop 脚本回收。"""

    release_root = _resolve_release_root()
    python_executable = _resolve_release_python(release_root)
    start_script = release_root / "start_amvision_full.py"
    stop_script = release_root / "stop_amvision_full.py"
    if not start_script.is_file() or not stop_script.is_file():
        pytest.skip("release/full 尚未组装，跳过发布目录真实启动验收")

    port = int(os.environ.get("AMVISION_RELEASE_FULL_PORT", "8000"))
    logs_subdir = os.environ.get(
        "AMVISION_RELEASE_FULL_LOGS_SUBDIR",
        f"integration-full-stack-{int(time.time())}",
    )
    soak_seconds = float(os.environ.get("AMVISION_RELEASE_FULL_SOAK_SECONDS", "10"))
    state_file = release_root / "logs" / logs_subdir / "runtime-state.json"
    resource_baseline_file = state_file.parent / "resource-baseline.json"
    component_resource_refs: list[tuple[int, float]] = []

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(
            {
                "root_pid": -1,
                "components": [{"name": "stale-worker", "pid": -1}],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    start_process = subprocess.Popen(
        [
            str(python_executable),
            str(start_script),
            "--app-root",
            str(release_root),
            "--python-executable",
            str(python_executable),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--logs-subdir",
            logs_subdir,
            "--startup-delay-seconds",
            "0.5",
        ],
        cwd=release_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    try:
        _wait_for_http_json(f"http://127.0.0.1:{port}/api/v1/system/health", timeout_seconds=90)
        docs_html = _wait_for_http_text(f"http://127.0.0.1:{port}/docs", timeout_seconds=30)
        assert "swagger" in docs_html.lower() or "openapi" in docs_html.lower()

        openapi_payload = _wait_for_http_json(f"http://127.0.0.1:{port}/openapi.json", timeout_seconds=30)
        paths = openapi_payload.get("paths")
        assert isinstance(paths, dict)
        assert "/api/v1/models/detection/training-tasks" in paths
        assert "/api/v1/models/classification/conversion-tasks/{task_id}/result" in paths
        assert "/api/v1/models/segmentation/deployment-instances" in paths

        assert state_file.is_file()
        state_payload = json.loads(state_file.read_text(encoding="utf-8"))
        assert state_payload.get("root_pid") != -1
        components = state_payload.get("components")
        assert isinstance(components, list)
        component_names = {item.get("name") for item in components if isinstance(item, dict)}
        assert {
            "backend-service",
            "backend-worker:dataset-import",
            "backend-worker:dataset-export",
            "backend-worker:training",
            "backend-worker:conversion",
            "backend-worker:evaluation",
            "backend-worker:inference",
        }.issubset(component_names)
        _assert_component_logs_exist(release_root, components)
        initial_resources = _collect_process_resources(components)
        component_resource_refs = [
            (int(item["pid"]), float(item["create_time"]))
            for item in initial_resources
        ]

        deadline = time.monotonic() + max(0.0, soak_seconds)
        while time.monotonic() < deadline:
            assert start_process.poll() is None
            _wait_for_http_json(f"http://127.0.0.1:{port}/api/v1/system/health", timeout_seconds=10)
            time.sleep(min(2.0, max(0.1, deadline - time.monotonic())))

        final_resources = _collect_process_resources(components)
        resource_baseline_file.write_text(
            json.dumps(
                {
                    "soak_seconds": soak_seconds,
                    "initial": initial_resources,
                    "final": final_resources,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        assert resource_baseline_file.is_file()
    finally:
        stop_result = subprocess.run(
            [
                str(python_executable),
                str(stop_script),
                "--app-root",
                str(release_root),
                "--logs-subdir",
                logs_subdir,
            ],
            cwd=release_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
            check=False,
        )
        if start_process.poll() is None:
            start_process.terminate()
            try:
                start_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                start_process.kill()
                start_process.wait(timeout=15)
        assert stop_result.returncode == 0, stop_result.stdout
        assert not state_file.exists()
        _assert_process_refs_stopped(component_resource_refs)


def _resolve_release_root() -> Path:
    """解析本次要验收的 release/full 根目录。"""

    configured = os.environ.get("AMVISION_RELEASE_FULL_ROOT")
    if configured:
        return Path(configured).resolve()
    return (Path(__file__).resolve().parents[2] / "release" / "full").resolve()


def _resolve_release_python(release_root: Path) -> Path:
    """解析 release/full 中的 Python 解释器。"""

    configured = os.environ.get("AMVISION_RELEASE_FULL_PYTHON")
    if configured:
        return Path(configured).resolve()
    candidate = release_root / "python" / ("python.exe" if os.name == "nt" else "bin/python")
    if not candidate.is_file():
        pytest.skip("release/full/python 不存在，跳过发布目录真实启动验收")
    return candidate


def _assert_component_logs_exist(release_root: Path, components: list[object]) -> None:
    """确认 full stack 中每个组件都写出了独立日志文件。"""

    for component in components:
        assert isinstance(component, dict)
        log_file_raw = component.get("log_file")
        assert isinstance(log_file_raw, str) and log_file_raw.strip()
        log_file_path = _resolve_runtime_path(release_root, log_file_raw)
        assert log_file_path.is_file(), f"组件日志文件不存在: {log_file_path}"


def _collect_process_resources(components: list[object]) -> list[dict[str, object]]:
    """采集 full stack 组件进程的资源快照。"""

    rows: list[dict[str, object]] = []
    for component in components:
        assert isinstance(component, dict)
        name = component.get("name")
        pid = component.get("pid")
        assert isinstance(name, str) and name
        assert isinstance(pid, int) and pid > 0
        try:
            process = psutil.Process(pid)
            with process.oneshot():
                memory_info = process.memory_info()
                cpu_times = process.cpu_times()
                status = process.status()
                row = {
                    "name": name,
                    "pid": pid,
                    "create_time": process.create_time(),
                    "status": status,
                    "rss_bytes": memory_info.rss,
                    "num_threads": process.num_threads(),
                    "user_cpu_seconds": cpu_times.user,
                    "system_cpu_seconds": cpu_times.system,
                }
        except psutil.Error as exc:
            raise AssertionError(f"无法读取组件进程资源: name={name}, pid={pid}") from exc
        assert row["status"] != psutil.STATUS_ZOMBIE
        assert int(row["rss_bytes"]) > 0
        assert int(row["num_threads"]) >= 1
        rows.append(row)
    return rows


def _assert_process_refs_stopped(process_refs: list[tuple[int, float]]) -> None:
    """确认 stop 脚本已经回收启动时记录的组件进程。"""

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if all(not _process_ref_is_alive(pid, create_time) for pid, create_time in process_refs):
            return
        time.sleep(0.5)
    alive_pids = [
        pid
        for pid, create_time in process_refs
        if _process_ref_is_alive(pid, create_time)
    ]
    raise AssertionError(f"stop 后仍有组件进程存活: {alive_pids}")


def _process_ref_is_alive(pid: int, create_time: float) -> bool:
    """按 pid 和 create_time 判断是否仍是同一个进程。"""

    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return f'"{pid}"' in result.stdout
    try:
        process = psutil.Process(pid)
        return abs(process.create_time() - create_time) < 1.0 and process.is_running()
    except psutil.Error:
        return False


def _resolve_runtime_path(release_root: Path, value: str) -> Path:
    """解析 release runtime 状态文件中的相对或绝对路径。"""

    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (release_root / candidate).resolve()


def _wait_for_http_json(url: str, *, timeout_seconds: float) -> dict[str, object]:
    """等待指定 HTTP JSON 接口可访问。"""

    text = _wait_for_http_text(url, timeout_seconds=timeout_seconds)
    payload = json.loads(text)
    assert isinstance(payload, dict)
    return payload


def _wait_for_http_text(url: str, *, timeout_seconds: float) -> str:
    """等待指定 HTTP 接口返回文本。"""

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=5) as response:
                assert response.status == 200
                return response.read().decode("utf-8", errors="replace")
        except (OSError, URLError, AssertionError) as exc:
            last_error = exc
            time.sleep(1.0)
    raise AssertionError(f"等待 HTTP 接口超时: {url}") from last_error
