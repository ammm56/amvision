"""Workflow Trigger mailbox 固定布局、状态机和 overflow page 测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import mmap
import os
from pathlib import Path
from time import sleep

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


def test_page_reservation_is_serialized_across_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不同 descriptor 并发选择 page 时不得得到重叠 reservation。"""

    import backend.service.infrastructure.ipc.workflow_trigger_mailbox as mailbox_module

    original_select = mailbox_module.select_page_indices

    def slow_select(*, free_page_indices: tuple[int, ...], page_count: int):
        # 放大“扫描 FREE 后、发布 RESERVED 前”的旧竞态窗口。allocator lock
        # 正确时第二个线程不能在第一个 reservation 发布前重新扫描 page pool。
        sleep(0.02)
        return original_select(
            free_page_indices=free_page_indices,
            page_count=page_count,
        )

    monkeypatch.setattr(mailbox_module, "select_page_indices", slow_select)
    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identities = tuple(
                _publish_request(server, client, b"{}") for _ in range(2)
            )
            requests = tuple(server.poll_request() for _ in identities)
            assert all(request is not None for request in requests)
            resolved = tuple(request for request in requests if request is not None)

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = tuple(
                    executor.submit(
                        server._reserve_pages,
                        page_count=4,
                        identity=request.identity,
                    )
                    for request in resolved
                )
                reservations = tuple(future.result() for future in futures)

            assert len(set(reservations[0]) & set(reservations[1])) == 0
            assert server.build_status()["used_page_count"] == 8
            for request, page_indices in zip(resolved, reservations, strict=True):
                server._release_reserved_pages(
                    identity=request.identity,
                    page_indices=page_indices,
                )
                server.publish_json_response(
                    identity=request.identity,
                    payload={"state": "succeeded"},
                )
                client.acknowledge(identity=request.identity)
            server.sweep()
            assert server.build_status()["used_page_count"] == 0


def test_concurrent_page_chain_responses_keep_payload_and_identity(
    tmp_path: Path,
) -> None:
    """16 个并发 page-chain 响应不得串页、泄漏或破坏 owner identity。"""

    payloads = tuple(
        index.to_bytes(4, "little") + os.urandom(1024 * 1024)
        for index in range(16)
    )
    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identities = tuple(
                _publish_request(server, client, b"{}") for _ in payloads
            )
            requests = tuple(server.poll_request() for _ in payloads)
            assert all(request is not None for request in requests)
            resolved = tuple(request for request in requests if request is not None)

            with ThreadPoolExecutor(max_workers=16) as executor:
                futures = tuple(
                    executor.submit(
                        server.publish_response,
                        identity=request.identity,
                        payload=payload,
                    )
                    for request, payload in zip(resolved, payloads, strict=True)
                )
                for future in futures:
                    future.result()

            assert server.build_status()["used_page_count"] == 48
            for identity, payload in zip(identities, payloads, strict=True):
                response = client.read_response(identity=identity)
                assert response is not None
                assert response.payload == payload
                client.acknowledge(identity=identity)
            assert server.sweep()["released_count"] == 16
            assert server.build_status()["used_page_count"] == 0


def test_page_pool_full_keeps_inline_and_capacity_error_available(
    tmp_path: Path,
) -> None:
    """overflow page 满载时 inline success/error 仍可发布且不抢占 page。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identities = tuple(
                _publish_request(server, client, b"{}") for _ in range(6)
            )
            requests = tuple(server.poll_request() for _ in identities)
            assert all(request is not None for request in requests)
            resolved = tuple(request for request in requests if request is not None)
            reservations = tuple(
                server._reserve_pages(
                    page_count=contract.MAX_OVERFLOW_PAGES_PER_RESPONSE,
                    identity=request.identity,
                )
                for request in resolved[:4]
            )
            assert server.build_status()["free_page_count"] == 0

            server.publish_response(
                identity=resolved[4].identity,
                payload=os.urandom(contract.INLINE_RESPONSE_CAPACITY_BYTES + 1),
            )
            capacity_response = client.read_response(identity=identities[4])
            assert capacity_response is not None
            assert (
                capacity_response.error_code
                == contract.ERROR_CODE_TRIGGER_RESPONSE_CAPACITY_EXHAUSTED
            )
            server.publish_json_response(
                identity=resolved[5].identity,
                payload={"state": "succeeded"},
            )
            inline_response = client.read_response(identity=identities[5])
            assert inline_response is not None
            assert inline_response.json_payload() == {"state": "succeeded"}
            assert server.build_status()["free_page_count"] == 0

            for request, page_indices in zip(
                resolved[:4], reservations, strict=True
            ):
                server._release_reserved_pages(
                    identity=request.identity,
                    page_indices=page_indices,
                )
                server.publish_json_response(
                    identity=request.identity,
                    payload={"state": "succeeded"},
                )
            for identity in identities:
                client.acknowledge(identity=identity)
            assert server.sweep()["released_count"] == 6
            assert server.build_status()["used_page_count"] == 0


def test_fragmented_page_pool_builds_non_contiguous_chain(tmp_path: Path) -> None:
    """连续空间耗尽后仍按 page identity 构造非连续 response chain。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identities = tuple(
                _publish_request(server, client, b"{}") for _ in range(5)
            )
            requests = tuple(server.poll_request() for _ in identities)
            assert all(request is not None for request in requests)
            resolved = tuple(request for request in requests if request is not None)
            reservations = tuple(
                server._reserve_pages(
                    page_count=contract.MAX_OVERFLOW_PAGES_PER_RESPONSE,
                    identity=request.identity,
                )
                for request in resolved[:4]
            )
            for request, page_indices in zip(
                resolved[:4], reservations, strict=True
            ):
                server._release_reserved_pages(
                    identity=request.identity,
                    page_indices=tuple(index for index in page_indices if index % 2 == 0),
                )

            fragmented = server._reserve_pages(
                page_count=4,
                identity=resolved[4].identity,
            )
            assert fragmented == (0, 2, 4, 6)
            server._release_reserved_pages(
                identity=resolved[4].identity,
                page_indices=fragmented,
            )
            for request, page_indices in zip(
                resolved[:4], reservations, strict=True
            ):
                server._release_reserved_pages(
                    identity=request.identity,
                    page_indices=tuple(index for index in page_indices if index % 2 == 1),
                )
            for request in resolved:
                server.publish_json_response(
                    identity=request.identity,
                    payload={"state": "succeeded"},
                )
                client.acknowledge(identity=request.identity)
            assert server.sweep()["released_count"] == 5
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
            assert result["deadline_exceeded_count"] == 1
            response = client.read_response(identity=expired)
            assert response.error_code == contract.ERROR_CODE_DEADLINE_EXCEEDED
            assert response.response_ack_deadline_ns > expired.deadline_ns
            client.acknowledge(identity=expired)
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
