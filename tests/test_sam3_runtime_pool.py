"""SAM3 runtime pool 生命周期测试。"""

from __future__ import annotations

from pathlib import Path

from custom_nodes.sam3_segment_nodes.backend.runtime import access


class _FakeRuntimeSession:
    """记录构造参数和关闭状态的轻量 session。"""

    def __init__(self, **parameters: object) -> None:
        self.parameters = parameters
        self.closed = False

    def close(self) -> None:
        """记录 session 已被释放。"""

        self.closed = True


def test_interactive_runtime_pool_reuses_same_cache_key(monkeypatch) -> None:
    """验证同一资产、设备和精度只构造一个 interactive session。"""

    access.clear_sam3_runtime_caches()
    monkeypatch.setattr(access, "Sam3InteractiveRuntimeSession", _FakeRuntimeSession)

    first_session = access.get_or_create_interactive_runtime_session(
        checkpoint_path=Path("sam3-a.pt"),
        model_asset_id="sam3/a",
        architecture_id="sam3.test.v1",
        device_name="cpu",
        precision="fp32",
    )
    second_session = access.get_or_create_interactive_runtime_session(
        checkpoint_path=Path("sam3-a.pt"),
        model_asset_id="sam3/a",
        architecture_id="sam3.test.v1",
        device_name="cpu",
        precision="fp32",
    )

    assert second_session is first_session
    assert first_session.closed is False
    access.clear_sam3_runtime_caches()
    assert first_session.closed is True


def test_semantic_runtime_pool_closes_lru_session_on_replacement(monkeypatch) -> None:
    """验证新 cache key 会关闭容量外的 semantic session。"""

    access.clear_sam3_runtime_caches()
    monkeypatch.setattr(access, "Sam3SemanticRuntimeSession", _FakeRuntimeSession)

    first_session = access.get_or_create_semantic_runtime_session(
        checkpoint_path=Path("sam3-a.pt"),
        model_asset_id="sam3/a",
        architecture_id="sam3.test.v1",
        device_name="cpu",
        precision="fp32",
    )
    second_session = access.get_or_create_semantic_runtime_session(
        checkpoint_path=Path("sam3-b.pt"),
        model_asset_id="sam3/b",
        architecture_id="sam3.test.v1",
        device_name="cpu",
        precision="fp32",
    )

    assert first_session.closed is True
    assert second_session.closed is False
    access.clear_sam3_runtime_caches()
    assert second_session.closed is True
