"""独立 inference daemon 命令入口测试。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.inference_daemon import main as inference_daemon_main


class _FakeMmapClient:
    """记录 probe 请求与关闭动作。"""

    instances: list["_FakeMmapClient"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.requests: list[dict[str, object]] = []
        self.closed = False
        self.instances.append(self)

    def request(self, payload: dict[str, object]) -> dict[str, object]:
        """返回可用的 mmap ping 响应。"""

        self.requests.append(payload)
        return {"ok": True, "result": {"ready": True}}

    def close(self) -> None:
        """记录 client 已关闭。"""

        self.closed = True


def _settings(*, mmap_enabled: bool) -> SimpleNamespace:
    """构造 probe 使用的最小配置。"""

    return SimpleNamespace(
        local_buffer_broker=SimpleNamespace(root_dir="./data/buffers"),
        inference_daemon=SimpleNamespace(
            service_id="inference-daemon-main",
            mmap_mailbox=SimpleNamespace(
                enabled=mmap_enabled,
                poll_interval_seconds=0.001,
            ),
        ),
    )


def test_probe_uses_mmap_ping_without_legacy_control_queue(monkeypatch) -> None:
    """验证 probe 只走当前 mmap v1 只读热路径。"""

    _FakeMmapClient.instances.clear()
    monkeypatch.setattr(
        inference_daemon_main,
        "get_backend_service_settings",
        lambda: _settings(mmap_enabled=True),
    )
    monkeypatch.setattr(
        inference_daemon_main,
        "InferenceLocalMmapClient",
        _FakeMmapClient,
    )
    monkeypatch.setattr(
        inference_daemon_main,
        "build_inference_local_mmap_path",
        lambda **_kwargs: "mailbox.mmap",
    )

    assert inference_daemon_main.main(["--probe"]) == 0
    assert len(_FakeMmapClient.instances) == 1
    client = _FakeMmapClient.instances[0]
    assert client.requests == [{"action": "ping"}]
    assert client.closed is True


def test_probe_rejects_disabled_mmap_hot_path(monkeypatch, capsys) -> None:
    """验证 daemon 模式不会把禁用 mmap 误报为可用。"""

    monkeypatch.setattr(
        inference_daemon_main,
        "get_backend_service_settings",
        lambda: _settings(mmap_enabled=False),
    )

    assert inference_daemon_main.main(["--probe"]) == 1
    assert "mmap v1 热路径未启用" in capsys.readouterr().err
