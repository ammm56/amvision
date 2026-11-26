"""系统诊断服务状态测试。"""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.service.api.rest.v1.routes.system import diagnostics


def test_bundled_python_detection_accepts_release_python_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证发行目录同级 Python 被识别为 bundled Python。"""

    monkeypatch.chdir(tmp_path)
    executable = tmp_path / "python" / "python.exe"

    assert diagnostics._is_bundled_python(str(executable)) is True


def test_bundled_python_detection_rejects_external_conda_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证外部 conda 解释器不会被误判为发行包运行时。"""

    monkeypatch.chdir(tmp_path)
    executable = tmp_path.parent / "conda" / "envs" / "amvision" / "python.exe"

    assert diagnostics._is_bundled_python(str(executable)) is False


@pytest.mark.parametrize(
    ("dependency_installed", "adapter_configured", "expected_status"),
    (
        (False, False, "missing"),
        (False, True, "missing"),
        (True, False, "not_configured"),
        (True, True, "available"),
    ),
)
def test_zeromq_service_status_requires_dependency_and_adapter(
    monkeypatch: pytest.MonkeyPatch,
    dependency_installed: bool,
    adapter_configured: bool,
    expected_status: str,
) -> None:
    """验证 ZeroMQ 只有在依赖和协议 adapter 同时就绪时才标记为可用。"""

    monkeypatch.setattr(
        diagnostics,
        "_build_dependency_status",
        lambda _distribution, _import_name: {"installed": dependency_installed},
    )
    adapters = {"zeromq-topic": object()} if adapter_configured else {}

    summary = diagnostics._build_zeromq_service_summary(
        SimpleNamespace(adapters=adapters)
    )

    assert summary["status"] == expected_status
    assert summary["available"] is (
        dependency_installed and adapter_configured
    )
    assert summary["adapter_configured"] is adapter_configured


def test_inference_daemon_diagnostics_reports_real_ping_result() -> None:
    """验证 daemon 模式不会把控制客户端存在误报为 daemon 可用。"""

    class _Client:
        def ping(self, *, timeout_seconds: float):
            assert timeout_seconds == 1.0
            return {"ready": True}

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                detection_sync_deployment_process_supervisor=_Client()
            )
        )
    )
    settings = SimpleNamespace(
        inference_daemon=SimpleNamespace(
            runtime_owner="daemon",
            service_id="inference-daemon-main",
        )
    )

    summary = diagnostics._build_inference_daemon_summary(
        request=request,
        settings=settings,
    )

    assert summary == {
        "runtime_owner": "daemon",
        "service_id": "inference-daemon-main",
        "independent_process": True,
        "status": "ok",
        "reachable": True,
    }


def test_inference_daemon_diagnostics_degrades_when_ping_fails() -> None:
    """验证 daemon 不可达时诊断仍返回结构化降级状态。"""

    class _Client:
        def ping(self, *, timeout_seconds: float):
            raise TimeoutError(str(timeout_seconds))

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                detection_sync_deployment_process_supervisor=_Client()
            )
        )
    )
    settings = SimpleNamespace(
        inference_daemon=SimpleNamespace(
            runtime_owner="daemon",
            service_id="inference-daemon-main",
        )
    )

    summary = diagnostics._build_inference_daemon_summary(
        request=request,
        settings=settings,
    )

    assert summary["status"] == "unavailable"
    assert summary["reachable"] is False
    assert summary["error_type"] == "TimeoutError"


def test_local_message_diagnostics_separates_mailbox_event_and_retained_queue(
    tmp_path: Path,
) -> None:
    """诊断只暴露类型化健康摘要，不暴露 descriptor/page 几何配置。"""

    channel_id = uuid4()
    session_id = uuid4()
    event_health = SimpleNamespace(
        channel_id=channel_id,
        owner_epoch=7,
        session_id=session_id,
        closed=False,
        published_sequence=11,
        dropped_total=2,
        reader_gap_total=1,
    )
    trigger = SimpleNamespace(
        build_status=lambda: {
            "running": True,
            "pending_request_count": 0,
            "mailbox": {"free_descriptor_count": 128},
        }
    )
    telemetry = SimpleNamespace(
        is_running=True,
        snapshot_health=lambda: (event_health,),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                workflow_trigger_mailbox_supervisor=trigger,
                training_telemetry_receiver=telemetry,
            )
        )
    )
    settings = SimpleNamespace(
        local_memory=SimpleNamespace(root_dir=str(tmp_path / "buffers")),
        inference_daemon=SimpleNamespace(
            mmap_mailbox=SimpleNamespace(enabled=True)
        ),
    )

    summary = diagnostics._build_local_message_summary(
        request=request,
        settings=settings,
    )

    assert summary["workflow_trigger_mailbox"]["running"] is True
    assert summary["training_telemetry_event"] == {
        "configured": True,
        "running": True,
        "channel_count": 1,
        "channels": [
            {
                "channel_id": str(channel_id),
                "owner_epoch": 7,
                "session_id": str(session_id),
                "closed": False,
                "published_sequence": 11,
                "dropped_total": 2,
                "reader_gap_total": 1,
            }
        ],
    }
    assert summary["inference_mailbox"]["enabled"] is True
    assert summary["retained_queue_channels"] == [
        "workflow-runtime",
        "published-inference-gateway",
        "local-buffer-broker-control",
    ]


def test_build_device_diagnostics_includes_host_and_cpu_summary() -> None:
    """验证设备摘要包含 host 与 cpu 字段，且在当前平台下返回可读信息。"""

    devices = diagnostics.build_device_diagnostics()

    assert "host" in devices
    assert "cpu" in devices
    host = devices["host"]
    assert isinstance(host, dict)
    assert host["system"]
    assert host["os_platform"]
    assert host["os_name"]
    assert host["os_name"] != "Win32"
    assert host["hostname"]
    assert host["machine"]

    cpu = devices["cpu"]
    assert cpu["available"] is True
    assert cpu["logical_cores"] is None or cpu["logical_cores"] >= 1
    assert cpu["physical_cores"] is None or cpu["physical_cores"] >= 1


def test_host_summary_normalizes_windows_11_linux_and_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 Windows 11 build 归一、Linux PRETTY_NAME 与 macOS 版本格式化。"""

    import builtins
    import sys

    class _FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_values = {
        "ProductName": ("Windows 10 Pro", 1),
        "DisplayVersion": ("24H2", 1),
        "CurrentBuildNumber": ("26100", 1),
    }

    fake_winreg = SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=lambda _root, _path: _FakeKey(),
        QueryValueEx=lambda _key, name: (
            fake_values[name]
            if name in fake_values
            else (_ for _ in ()).throw(OSError("missing"))
        ),
    )

    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(diagnostics.platform_module, "system", lambda: "Windows")
    monkeypatch.setattr(diagnostics.platform_module, "machine", lambda: "AMD64")
    monkeypatch.setattr(diagnostics.socket, "gethostname", lambda: "win-box")
    win_host = diagnostics._build_host_summary()
    assert win_host == {
        "system": "Windows",
        "os_platform": "Windows x64",
        "os_name": "Windows 11 Pro 24H2 (Build 26100)",
        "hostname": "win-box",
        "machine": "AMD64",
    }

    fake_values["CurrentBuildNumber"] = ("19045", 1)
    assert (
        diagnostics._build_host_summary()["os_name"]
        == "Windows 10 Pro 24H2 (Build 19045)"
    )

    monkeypatch.setattr(diagnostics.platform_module, "system", lambda: "Linux")
    monkeypatch.setattr(diagnostics.platform_module, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        diagnostics.platform_module,
        "freedesktop_os_release",
        lambda: {"PRETTY_NAME": "Ubuntu 24.04 LTS"},
        raising=False,
    )
    linux_host = diagnostics._build_host_summary()
    assert linux_host["os_platform"] == "Linux x64"
    assert linux_host["os_name"] == "Ubuntu 24.04 LTS"

    monkeypatch.setattr(
        diagnostics.platform_module,
        "freedesktop_os_release",
        lambda: (_ for _ in ()).throw(OSError("no os-release")),
        raising=False,
    )
    monkeypatch.setattr(
        diagnostics.platform_module,
        "platform",
        lambda: "Linux-6.8.0-x86_64",
    )
    assert diagnostics._build_host_summary()["os_name"] == "Linux-6.8.0-x86_64"

    monkeypatch.setattr(diagnostics.platform_module, "system", lambda: "Darwin")
    monkeypatch.setattr(diagnostics.platform_module, "machine", lambda: "arm64")
    monkeypatch.setattr(
        diagnostics.platform_module,
        "mac_ver",
        lambda: ("15.1", ("", "", ""), "arm64"),
    )
    mac_host = diagnostics._build_host_summary()
    assert mac_host["os_platform"] == "macOS arm64"
    assert mac_host["os_name"] == "macOS 15.1"

    real_import = builtins.__import__
    monkeypatch.setattr(diagnostics.util, "find_spec", lambda _name: None)
    cpu = diagnostics._build_cpu_summary()
    assert cpu["available"] is True
    assert cpu["physical_cores"] is None
    assert callable(real_import)
