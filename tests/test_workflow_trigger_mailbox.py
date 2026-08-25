"""Workflow Trigger mailbox 固定布局、状态机和 overflow page 测试。"""

from __future__ import annotations

from contextlib import contextmanager
import mmap
import os
from pathlib import Path

import pytest

from backend.contracts.ipc import workflow_trigger_mailbox_v1 as contract
from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.ipc.mmap_primitives import MmapOwnerLockBusyError
from backend.service.infrastructure.ipc.workflow_trigger_mailbox import (
    DESCRIPTOR_STRIDE_BYTES,
    MAILBOX_FILE_SIZE_BYTES,
    WorkflowTriggerMailboxClient,
    WorkflowTriggerMailboxServer,
)


def test_inline_request_response_ack_and_reuse(tmp_path: Path) -> None:
    """小请求和小响应只使用 inline 区，ACK 后立即归还 descriptor。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identity = _publish_request(server, client, b'{"value":1}')
            request = server.poll_request()
            assert request is not None
            assert request.payload == b'{"value":1}'
            assert request.route_generation == 7

            server.publish_json_response(
                identity=request.identity,
                payload={"state": "succeeded", "value": 2},
            )
            response = client.read_response(identity=identity)

            assert response is not None
            assert response.json_payload() == {"state": "succeeded", "value": 2}
            assert server.build_status()["used_page_count"] == 0

            client.acknowledge(identity=identity)
            sweep_result = server.sweep()
            assert sweep_result["released_count"] == 1
            assert sweep_result["released_identities"] == (identity,)
            assert server.build_status()["descriptor_state_counts"][0] == 128

            reused = client.claim(
                timeout_ms=5_000,
                route_generation=8,
            )
            assert reused.descriptor_index == identity.descriptor_index
            assert reused.generation != identity.generation


@pytest.mark.parametrize(
    ("size", "expected_pages"),
    [
        (contract.INLINE_RESPONSE_CAPACITY_BYTES, 0),
        (contract.INLINE_RESPONSE_CAPACITY_BYTES + 1, 2),
        (1024 * 1024, 2),
    ],
)
def test_response_boundary_and_page_chain(
    tmp_path: Path,
    size: int,
    expected_pages: int,
) -> None:
    """512 KiB 边界前后均保持字节完全一致。"""

    payload = os.urandom(size)
    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identity = _publish_request(server, client, b"{}")
            request = server.poll_request()
            assert request is not None

            server.publish_response(identity=request.identity, payload=payload)
            response = client.read_response(identity=identity)

            assert response is not None
            assert response.payload == payload
            assert server.build_status()["used_page_count"] == expected_pages
            client.acknowledge(identity=identity)
            server.sweep()
            assert server.build_status()["used_page_count"] == 0


def test_large_compressible_response_uses_lossless_inline_codec(tmp_path: Path) -> None:
    """重复度高的大 JSON 经透明压缩后仍返回完全相同的公开 bytes。"""

    payload = b'{"polygon":[' + b"1234567890," * 100_000 + b"]}"
    assert len(payload) > contract.INLINE_RESPONSE_CAPACITY_BYTES
    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identity = _publish_request(server, client, b"{}")
            request = server.poll_request()
            assert request is not None

            server.publish_response(identity=request.identity, payload=payload)
            response = client.read_response(identity=identity)

            assert response is not None
            assert response.payload == payload
            assert server.build_status()["used_page_count"] == 0


def test_cancel_and_deadline_are_swept_without_page_leak(tmp_path: Path) -> None:
    """取消和超时均由 server 统一归还 descriptor/page。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identity = _publish_request(server, client, b"{}")
            client.cancel(identity=identity)
            assert server.sweep()["released_count"] == 1

            expired = client.claim(
                timeout_ms=1_000,
                route_generation=1,
            )
            accepted = server.poll_prepare()
            assert accepted is not None
            expired = accepted.identity
            result = server.sweep(now_ns=expired.deadline_ns)
            assert result["cancelled_count"] == 1
            assert server.sweep()["released_count"] == 1
            assert server.build_status()["used_page_count"] == 0


def test_targeted_sweep_only_visits_selected_descriptor(tmp_path: Path) -> None:
    """热路径定向 sweep 不得顺带回收其他 descriptor。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            first = _publish_request(server, client, b'{"request":1}')
            second = _publish_request(server, client, b'{"request":2}')
            client.cancel(identity=first)
            client.cancel(identity=second)

            targeted = server.sweep(
                descriptor_indexes=(first.descriptor_index,)
            )

            assert targeted["released_identities"] == (first,)
            assert server.build_status()["descriptor_state_counts"][0] == 127
            assert server.sweep()["released_identities"] == (second,)


def test_prepare_poll_uses_round_robin_fairness(tmp_path: Path) -> None:
    """持续低索引 PREPARE 不能让后续 descriptor 饥饿。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identities = tuple(
                client.claim(
                    timeout_ms=5_000,
                    route_generation=1,
                    prepare_payload=b'{"trigger_source_id":"source-1"}',
                )
                for _ in range(3)
            )

            observed = tuple(server.poll_prepare() for _ in identities)

            assert all(item is not None for item in observed)
            assert tuple(item.identity.descriptor_index for item in observed if item) == (
                identities[0].descriptor_index,
                identities[1].descriptor_index,
                identities[2].descriptor_index,
            )


def test_sweep_skips_descriptor_guard_for_active_request_before_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常请求不得在毫秒级 sweep 中重复打开 descriptor guard 文件。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            guard_calls: list[int] = []
            original_guard = server._try_descriptor_guard

            @contextmanager
            def recording_guard(descriptor_index: int):
                guard_calls.append(descriptor_index)
                with original_guard(descriptor_index) as acquired:
                    yield acquired

            monkeypatch.setattr(server, "_try_descriptor_guard", recording_guard)

            identity = client.claim(
                timeout_ms=5_000,
                route_generation=1,
                prepare_payload=b'{"trigger_source_id":"source-1"}',
            )
            server.sweep(descriptor_indexes=(identity.descriptor_index,))
            assert guard_calls == []

            prepare = server.poll_prepare()
            assert prepare is not None
            identity = prepare.identity
            server.publish_writing(
                identity=identity,
                allocation_payload=b'{"input_attachment":null}',
            )
            guard_calls.clear()
            server.sweep(descriptor_indexes=(identity.descriptor_index,))
            assert guard_calls == []

            allocation = client.read_writing_allocation(identity=identity)
            assert allocation is not None
            client.publish_request(identity=allocation.identity, payload=b"{}")
            guard_calls.clear()
            server.sweep(descriptor_indexes=(identity.descriptor_index,))
            assert guard_calls == []

            request = server.poll_request()
            assert request is not None
            guard_calls.clear()
            server.sweep(descriptor_indexes=(identity.descriptor_index,))
            assert guard_calls == []

            server.publish_json_response(
                identity=request.identity,
                payload={"state": "succeeded"},
            )
            guard_calls.clear()
            server.sweep(descriptor_indexes=(identity.descriptor_index,))
            assert guard_calls == []

            client.acknowledge(identity=identity)
            guard_calls.clear()
            result = server.sweep(
                descriptor_indexes=(identity.descriptor_index,)
            )
            assert guard_calls == [identity.descriptor_index]
            assert result["released_identities"] == (identity,)


def test_server_restart_fences_old_client_identity(tmp_path: Path) -> None:
    """新 server epoch 清空旧状态，旧 client identity 不得操作新请求。"""

    server = WorkflowTriggerMailboxServer(buffers_root=tmp_path)
    client = WorkflowTriggerMailboxClient(buffers_root=tmp_path)
    old_identity = _publish_request(server, client, b"{}")
    old_epoch = server.server_epoch
    server.close()

    try:
        with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as restarted:
            assert restarted.server_epoch != old_epoch
            with pytest.raises(InvalidRequestError, match="identity"):
                client.cancel(identity=old_identity)
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as current:
                identity = _publish_request(
                    restarted,
                    current,
                    b'{"new":true}',
                )
                request = restarted.poll_request()
                assert request is not None
                assert request.identity == identity
    finally:
        client.close()


def test_only_one_mailbox_server_can_hold_owner_lock(tmp_path: Path) -> None:
    """单机只允许一个正式 mailbox server owner。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path):
        with pytest.raises(MmapOwnerLockBusyError):
            WorkflowTriggerMailboxServer(buffers_root=tmp_path)


def test_mailbox_file_has_fixed_predictable_size(tmp_path: Path) -> None:
    """启动时一次性固定文件大小，运行期不扩容。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        assert server.path.stat().st_size == MAILBOX_FILE_SIZE_BYTES
        with server.path.open("r+b") as handle:
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as view:
                assert view[:8] == contract.MAGIC


def test_corrupt_prepare_isolated_as_inline_error(tmp_path: Path) -> None:
    """损坏的 PREPARE 不得让 server poller 异常退出或占住 descriptor。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identity = client.claim(
                timeout_ms=5_000,
                route_generation=1,
                prepare_payload=b'{"trigger_source_id":"source-1"}',
            )
            request_offset = (
                contract.FILE_HEADER_SIZE
                + identity.descriptor_index * DESCRIPTOR_STRIDE_BYTES
                + contract.DESCRIPTOR_HEADER_SIZE
            )
            with server.path.open("r+b") as handle:
                with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_WRITE) as view:
                    view[request_offset] ^= 0x01

            assert server.poll_prepare() is None
            response = client.read_response(identity=identity)
            assert response is not None
            assert response.error_code == contract.ERROR_CODE_CHECKSUM_MISMATCH
            client.acknowledge(identity=identity)
            assert server.sweep()["released_count"] == 1


def _publish_request(
    server: WorkflowTriggerMailboxServer,
    client: WorkflowTriggerMailboxClient,
    payload: bytes,
):
    """认领并发布一个测试请求。"""

    identity = client.claim(
        timeout_ms=5_000,
        route_generation=7,
        prepare_payload=b'{"trigger_source_id":"source-1"}',
    )
    prepare = server.poll_prepare()
    assert prepare is not None
    assert prepare.identity.deadline_ns > 0
    server.publish_writing(
        identity=prepare.identity,
        allocation_payload=b'{"input_attachment":null}',
    )
    allocation = client.read_writing_allocation(identity=identity)
    assert allocation is not None
    assert allocation.payload == b'{"input_attachment":null}'
    client.publish_request(identity=allocation.identity, payload=payload)
    return allocation.identity
