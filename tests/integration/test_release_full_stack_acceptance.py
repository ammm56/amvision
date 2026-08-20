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
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen

import psutil
import pytest


@dataclass
class _SoakWorkloadProcess:
    """描述 release/full soak 期间可选启动的外部负载进程。"""

    process: subprocess.Popen
    log_file: Path
    stdout_handle: object
    command: list[str]


def test_release_full_stack_start_health_openapi_and_stop() -> None:
    """验证 release/full 可以启动、短时驻留并被 stop 脚本回收。"""

    release_root = _resolve_release_root()
    python_executable = _resolve_release_python(release_root)
    start_script = release_root / "start_amvision_full.py"
    stop_script = release_root / "stop_amvision_full.py"
    if not start_script.is_file() or not stop_script.is_file():
        pytest.skip("release/full 尚未组装，跳过发布目录真实启动验收")

    port = int(os.environ.get("AMVISION_RELEASE_FULL_PORT", "5600"))
    logs_subdir = os.environ.get(
        "AMVISION_RELEASE_FULL_LOGS_SUBDIR",
        f"integration-full-stack-{int(time.time())}",
    )
    soak_seconds = float(os.environ.get("AMVISION_RELEASE_FULL_SOAK_SECONDS", "10"))
    sample_interval_seconds = _resolve_resource_sample_interval(soak_seconds)
    state_file = release_root / "logs" / logs_subdir / "runtime-state.json"
    resource_baseline_file = state_file.parent / "resource-baseline.json"
    component_resource_refs: list[tuple[int, float]] = []
    base_url = f"http://127.0.0.1:{port}"
    workload_process: _SoakWorkloadProcess | None = None

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(
            {
                "format_id": "amvision.full-supervisor-state.v1",
                "root_process": {
                    "pid": -1,
                    "create_time": 0.0,
                    "executable": "missing",
                    "working_directory": str(release_root),
                    "command_line": [],
                },
                "components": [],
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
        _wait_for_http_json(f"{base_url}/api/v1/system/health", timeout_seconds=90)
        docs_html = _wait_for_http_text(f"{base_url}/docs", timeout_seconds=30)
        assert "swagger" in docs_html.lower() or "openapi" in docs_html.lower()

        openapi_payload = _wait_for_http_json(
            f"{base_url}/openapi.json", timeout_seconds=30
        )
        paths = openapi_payload.get("paths")
        assert isinstance(paths, dict)
        assert "/api/v1/models/detection/training-tasks" in paths
        assert (
            "/api/v1/models/classification/conversion-tasks/{task_id}/result" in paths
        )
        assert "/api/v1/models/segmentation/deployment-instances" in paths

        expected_component_names = {
            "backend-service",
            "backend-worker:dataset-import",
            "backend-worker:dataset-export",
            "backend-worker:training",
            "backend-worker:conversion",
            "backend-worker:evaluation",
            "backend-worker:inference",
        }
        state_payload = _wait_for_expected_components(
            state_file,
            expected_component_names=expected_component_names,
            timeout_seconds=120,
        )
        root_process = state_payload.get("root_process")
        assert isinstance(root_process, dict)
        assert root_process.get("pid") != -1
        components = state_payload.get("components")
        assert isinstance(components, list)
        component_names = {
            item.get("name") for item in components if isinstance(item, dict)
        }
        assert expected_component_names.issubset(component_names)
        _assert_component_logs_exist(release_root, components)
        if _resolve_profile_recovery_verification_enabled():
            components = _verify_single_worker_profile_recovery(
                release_root=release_root,
                state_file=state_file,
                components=components,
                target_component_name="backend-worker:dataset-export",
            )
        initial_resources = _collect_process_resources(components)
        workload_process = _start_optional_soak_workload(
            release_root=release_root,
            logs_dir=state_file.parent,
            base_url=base_url,
            port=port,
        )
        component_resource_refs = [
            (int(item["pid"]), float(item["create_time"])) for item in initial_resources
        ]
        resource_samples: list[dict[str, object]] = [
            {
                "elapsed_seconds": 0.0,
                "resources": initial_resources,
                "system_health": _wait_for_http_json(
                    f"{base_url}/api/v1/system/health", timeout_seconds=10
                ),
            }
        ]

        started_at = time.monotonic()
        deadline = time.monotonic() + max(0.0, soak_seconds)
        next_sample_at = started_at + sample_interval_seconds
        while time.monotonic() < deadline:
            assert start_process.poll() is None
            system_health = _wait_for_http_json(
                f"{base_url}/api/v1/system/health", timeout_seconds=10
            )
            _assert_optional_workload_ok(workload_process)
            now = time.monotonic()
            if now >= next_sample_at:
                resource_samples.append(
                    {
                        "elapsed_seconds": round(now - started_at, 3),
                        "resources": _collect_process_resources(components),
                        "system_health": system_health,
                    }
                )
                next_sample_at = now + sample_interval_seconds
            time.sleep(min(2.0, max(0.1, deadline - now)))

        final_resources = _collect_process_resources(components)
        resource_samples.append(
            {
                "elapsed_seconds": round(time.monotonic() - started_at, 3),
                "resources": final_resources,
                "system_health": _wait_for_http_json(
                    f"{base_url}/api/v1/system/health", timeout_seconds=10
                ),
            }
        )
        resource_baseline_file.write_text(
            json.dumps(
                {
                    "soak_seconds": soak_seconds,
                    "sample_interval_seconds": sample_interval_seconds,
                    "initial": initial_resources,
                    "final": final_resources,
                    "samples": resource_samples,
                    "summary": _summarize_resource_drift(
                        initial_resources=initial_resources,
                        final_resources=final_resources,
                    ),
                    "workload": _snapshot_optional_workload(workload_process),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        assert resource_baseline_file.is_file()
    finally:
        _stop_optional_workload(workload_process)
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
    candidate = (
        release_root / "python" / ("python.exe" if os.name == "nt" else "bin/python")
    )
    if not candidate.is_file():
        pytest.skip("release/full/python 不存在，跳过发布目录真实启动验收")
    return candidate


def _wait_for_state_payload(
    state_file: Path, *, timeout_seconds: float
) -> dict[str, object]:
    """等待 full stack 启动器写出运行状态文件。"""

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if not state_file.is_file():
            time.sleep(0.5)
            continue
        try:
            payload = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.5)
            continue
        if isinstance(payload, dict):
            return payload
        last_error = TypeError("runtime-state.json root payload is not an object")
        time.sleep(0.5)
    raise AssertionError(f"等待运行状态文件超时: {state_file}") from last_error


def _wait_for_expected_components(
    state_file: Path,
    *,
    expected_component_names: set[str],
    timeout_seconds: float,
) -> dict[str, object]:
    """等待所有必需组件进入 running，避免把渐进启动误判为缺失。"""

    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        payload = _wait_for_state_payload(state_file, timeout_seconds=5)
        last_payload = payload
        components = payload.get("components")
        if not isinstance(components, list):
            time.sleep(0.2)
            continue
        component_map = _index_components(components)
        if expected_component_names.issubset(component_map) and all(
            component_map[name].get("state") == "running"
            and isinstance(component_map[name].get("process"), dict)
            for name in expected_component_names
        ):
            return payload
        time.sleep(0.2)
    raise AssertionError(
        "等待 full stack 必需组件全部 running 超时: "
        f"expected={sorted(expected_component_names)}, payload={last_payload!r}"
    )


def _assert_component_logs_exist(release_root: Path, components: list[object]) -> None:
    """确认 full stack 中每个组件都写出了独立日志文件。"""

    for component in components:
        assert isinstance(component, dict)
        log_file_raw = component.get("log_file")
        assert isinstance(log_file_raw, str) and log_file_raw.strip()
        log_pattern = component.get("log_pattern")
        assert isinstance(log_pattern, str) and log_pattern.endswith("-YYYYMMDD.log")
        log_file_path = _resolve_runtime_path(release_root, log_file_raw)
        assert log_file_path.is_file(), f"组件日志文件不存在: {log_file_path}"
        assert log_file_path.name != log_pattern
        assert log_file_path.name.endswith(".log")
        date_token = log_file_path.stem.rsplit("-", 1)[-1]
        assert len(date_token) == 8 and date_token.isdigit()


def _resolve_profile_recovery_verification_enabled() -> bool:
    """解析是否在 full stack 验收中执行单 Profile 故障恢复。"""

    configured = os.environ.get(
        "AMVISION_RELEASE_FULL_VERIFY_PROFILE_RECOVERY",
        "true",
    )
    return configured.strip().lower() not in {"0", "false", "no", "off"}


def _verify_single_worker_profile_recovery(
    *,
    release_root: Path,
    state_file: Path,
    components: list[object],
    target_component_name: str,
) -> list[object]:
    """终止一个 Worker Profile，并验证只恢复该 Profile。"""

    component_map = _index_components(components)
    target = component_map[target_component_name]
    target_identity = _require_component_process_identity(target)
    previous_heartbeat = _load_worker_heartbeat(release_root, target)
    assert previous_heartbeat is not None
    previous_worker_instance_id = previous_heartbeat.get("worker_instance_id")
    assert isinstance(previous_worker_instance_id, str)
    stable_identities = {
        name: _require_component_process_identity(component)
        for name, component in component_map.items()
        if name != target_component_name
    }
    _terminate_exact_process_tree(
        pid=int(target_identity["pid"]),
        create_time=float(target_identity["create_time"]),
    )

    deadline = time.monotonic() + 90.0
    last_components: list[object] | None = None
    while time.monotonic() < deadline:
        payload = _wait_for_state_payload(state_file, timeout_seconds=5)
        current_components = payload.get("components")
        if not isinstance(current_components, list):
            time.sleep(0.2)
            continue
        last_components = current_components
        current_map = _index_components(current_components)
        current_target = current_map.get(target_component_name)
        if current_target is None:
            time.sleep(0.2)
            continue
        current_identity = current_target.get("process")
        if not isinstance(current_identity, dict):
            time.sleep(0.2)
            continue
        if (
            current_target.get("state") == "running"
            and _process_identity_changed(target_identity, current_identity)
            and _worker_heartbeat_matches_component(
                release_root=release_root,
                component=current_target,
                launcher_identity=current_identity,
                previous_worker_instance_id=previous_worker_instance_id,
            )
        ):
            for name, expected_identity in stable_identities.items():
                actual_identity = _require_component_process_identity(current_map[name])
                assert not _process_identity_changed(
                    expected_identity,
                    actual_identity,
                ), f"恢复 {target_component_name} 时意外重启了 {name}"
            return current_components
        time.sleep(0.2)
    raise AssertionError(
        f"等待单 Profile 独立恢复超时: {target_component_name}, "
        f"components={last_components!r}"
    )


def _index_components(components: list[object]) -> dict[str, dict[str, object]]:
    """按组件名索引 Supervisor 状态记录。"""

    result: dict[str, dict[str, object]] = {}
    for component in components:
        assert isinstance(component, dict)
        name = component.get("name")
        assert isinstance(name, str) and name
        result[name] = component
    return result


def _require_component_process_identity(
    component: dict[str, object],
) -> dict[str, object]:
    """读取组件当前的严格进程身份。"""

    process_identity = component.get("process")
    assert isinstance(process_identity, dict)
    pid = process_identity.get("pid")
    create_time = process_identity.get("create_time")
    assert isinstance(pid, int) and pid > 0
    assert isinstance(create_time, (int, float)) and float(create_time) > 0
    return process_identity


def _process_identity_changed(
    previous: dict[str, object],
    current: dict[str, object],
) -> bool:
    """判断 pid/create_time 标识的进程身份是否变化。"""

    return (
        int(previous["pid"]),
        float(previous["create_time"]),
    ) != (
        int(current["pid"]),
        float(current["create_time"]),
    )


def _worker_heartbeat_matches_component(
    *,
    release_root: Path,
    component: dict[str, object],
    launcher_identity: dict[str, object],
    previous_worker_instance_id: str,
) -> bool:
    """确认恢复后的 Profile 心跳属于新 launcher 的 Worker 子进程。"""

    heartbeat = _load_worker_heartbeat(release_root, component)
    if heartbeat is None:
        return False
    process_id = heartbeat.get("process_id")
    worker_instance_id = heartbeat.get("worker_instance_id")
    if (
        not isinstance(process_id, int)
        or not isinstance(worker_instance_id, str)
        or worker_instance_id == previous_worker_instance_id
    ):
        return False
    try:
        launcher_process = psutil.Process(int(launcher_identity["pid"]))
        descendant_pids = {
            process.pid for process in launcher_process.children(recursive=True)
        }
    except psutil.Error:
        return False
    return process_id in descendant_pids


def _load_worker_heartbeat(
    release_root: Path,
    component: dict[str, object],
) -> dict[str, object] | None:
    """读取组件所属的当前 Topology 心跳。"""

    profile_id = component.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        return None
    active_path = release_root / "data" / "runtime" / "backend-workers" / "active.json"
    try:
        pointer = json.loads(active_path.read_text(encoding="utf-8"))
        epoch_id = pointer["topology_epoch_id"]
        heartbeat_path = (
            active_path.parent
            / "topologies"
            / str(epoch_id)
            / "profiles"
            / f"{profile_id}.json"
        )
        heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(heartbeat, dict):
        return None
    if not (
        heartbeat.get("status") == "running"
        and heartbeat.get("profile_id") == profile_id
        and heartbeat.get("topology_epoch_id") == epoch_id
    ):
        return None
    return heartbeat


def _terminate_exact_process_tree(*, pid: int, create_time: float) -> None:
    """只终止本次验收记录的精确进程树。"""

    assert _process_ref_is_alive(pid, create_time), "待注入故障的进程身份已失效"
    process = psutil.Process(pid)
    descendants = process.children(recursive=True)
    for child in reversed(descendants):
        with child.oneshot():
            child.terminate()
    _, alive_children = psutil.wait_procs(descendants, timeout=10)
    for child in alive_children:
        child.kill()
    process.terminate()
    try:
        process.wait(timeout=10)
    except psutil.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _start_optional_soak_workload(
    *,
    release_root: Path,
    logs_dir: Path,
    base_url: str,
    port: int,
) -> _SoakWorkloadProcess | None:
    """按环境变量启动 release/full 长稳负载进程。"""

    command_payload = os.environ.get("AMVISION_RELEASE_FULL_SOAK_WORKLOAD_COMMAND_JSON")
    if not command_payload:
        return None
    try:
        command = json.loads(command_payload)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            "AMVISION_RELEASE_FULL_SOAK_WORKLOAD_COMMAND_JSON 必须是 JSON 数组"
        ) from exc
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item.strip() for item in command)
    ):
        raise AssertionError(
            "AMVISION_RELEASE_FULL_SOAK_WORKLOAD_COMMAND_JSON 必须是非空字符串数组"
        )
    cwd = Path(
        os.environ.get("AMVISION_RELEASE_FULL_SOAK_WORKLOAD_CWD", str(release_root))
    ).resolve()
    log_file = logs_dir / "soak-workload.log"
    stdout_handle = log_file.open("w", encoding="utf-8")
    env = os.environ.copy()
    env["AMVISION_RELEASE_FULL_BASE_URL"] = base_url
    env["AMVISION_RELEASE_FULL_PORT"] = str(port)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=stdout_handle,
        stderr=subprocess.STDOUT,
    )
    return _SoakWorkloadProcess(
        process=process,
        log_file=log_file,
        stdout_handle=stdout_handle,
        command=list(command),
    )


def _assert_optional_workload_ok(workload_process: _SoakWorkloadProcess | None) -> None:
    """确认可选负载进程未异常退出。"""

    if workload_process is None:
        return
    return_code = workload_process.process.poll()
    if return_code is None or return_code == 0:
        return
    raise AssertionError(
        "release/full soak workload 进程异常退出: "
        f"returncode={return_code}, log_tail={_read_log_tail(workload_process.log_file)}"
    )


def _snapshot_optional_workload(
    workload_process: _SoakWorkloadProcess | None,
) -> dict[str, object] | None:
    """生成可选负载进程的 baseline 摘要。"""

    if workload_process is None:
        return None
    return {
        "command": workload_process.command,
        "pid": workload_process.process.pid,
        "returncode": workload_process.process.poll(),
        "log_file": str(workload_process.log_file),
    }


def _stop_optional_workload(workload_process: _SoakWorkloadProcess | None) -> None:
    """停止可选负载进程并关闭日志句柄。"""

    if workload_process is None:
        return
    try:
        if workload_process.process.poll() is None:
            workload_process.process.terminate()
            try:
                workload_process.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                workload_process.process.kill()
                workload_process.process.wait(timeout=20)
    finally:
        workload_process.stdout_handle.close()


def _read_log_tail(log_file: Path, *, max_chars: int = 2000) -> str:
    """读取日志末尾，便于失败时定位。"""

    if not log_file.is_file():
        return ""
    content = log_file.read_text(encoding="utf-8", errors="replace")
    return content[-max_chars:]


def _collect_process_resources(components: list[object]) -> list[dict[str, object]]:
    """采集 full stack 组件进程的资源快照。"""

    rows: list[dict[str, object]] = []
    for component in components:
        assert isinstance(component, dict)
        name = component.get("name")
        process_identity = component.get("process")
        assert isinstance(process_identity, dict)
        pid = process_identity.get("pid")
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
            raise AssertionError(
                f"无法读取组件进程资源: name={name}, pid={pid}"
            ) from exc
        assert row["status"] != psutil.STATUS_ZOMBIE
        assert int(row["rss_bytes"]) > 0
        assert int(row["num_threads"]) >= 1
        rows.append(row)
    return rows


def _assert_process_refs_stopped(process_refs: list[tuple[int, float]]) -> None:
    """确认 stop 脚本已经回收启动时记录的组件进程。"""

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if all(
            not _process_ref_is_alive(pid, create_time)
            for pid, create_time in process_refs
        ):
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


def _resolve_resource_sample_interval(soak_seconds: float) -> float:
    """解析 release/full 资源采样间隔。"""

    configured = os.environ.get(
        "AMVISION_RELEASE_FULL_RESOURCE_SAMPLE_INTERVAL_SECONDS"
    )
    if configured:
        interval = float(configured)
    elif soak_seconds >= 120.0:
        interval = 30.0
    elif soak_seconds >= 30.0:
        interval = 10.0
    else:
        interval = max(1.0, soak_seconds)
    return max(1.0, interval)


def _summarize_resource_drift(
    *,
    initial_resources: list[dict[str, object]],
    final_resources: list[dict[str, object]],
) -> list[dict[str, object]]:
    """汇总 release/full 组件资源变化，便于现场比较基线。"""

    initial_by_name = {str(item["name"]): item for item in initial_resources}
    rows: list[dict[str, object]] = []
    for final_item in final_resources:
        name = str(final_item["name"])
        initial_item = initial_by_name.get(name)
        if initial_item is None:
            continue
        initial_rss = int(initial_item["rss_bytes"])
        final_rss = int(final_item["rss_bytes"])
        initial_cpu = float(initial_item["user_cpu_seconds"]) + float(
            initial_item["system_cpu_seconds"]
        )
        final_cpu = float(final_item["user_cpu_seconds"]) + float(
            final_item["system_cpu_seconds"]
        )
        rows.append(
            {
                "name": name,
                "pid": final_item["pid"],
                "initial_rss_bytes": initial_rss,
                "final_rss_bytes": final_rss,
                "rss_delta_bytes": final_rss - initial_rss,
                "initial_cpu_seconds": round(initial_cpu, 6),
                "final_cpu_seconds": round(final_cpu, 6),
                "cpu_delta_seconds": round(final_cpu - initial_cpu, 6),
                "initial_num_threads": initial_item["num_threads"],
                "final_num_threads": final_item["num_threads"],
            }
        )
    return rows


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
