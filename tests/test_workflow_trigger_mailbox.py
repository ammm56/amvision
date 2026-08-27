"""Workflow Trigger Mailbox extension 的两阶段、page-chain 与终态门禁。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import base64
import json
import os
from pathlib import Path
from time import sleep

import pytest

from backend.contracts.ipc import workflow_trigger_mailbox_v1 as contract
from backend.contracts.ipc.local_message_profiles import (
    MAILBOX_PUBLIC_RESPONSE_CAPACITY_BYTES,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.ipc.mmap_primitives import MmapOwnerLockBusyError
from backend.service.infrastructure.ipc.workflow_trigger_mailbox import (
    MAILBOX_FILE_SIZE_BYTES,
    WorkflowTriggerMailboxClient,
    WorkflowTriggerMailboxServer,
)
from backend.service.application.message_channels.errors import (
    ChannelLegacyLayoutError,
)


def test_inline_round_trip_reuses_descriptor_and_ack_recovers_capacity(
    tmp_path: Path,
) -> None:
    """PREPARE/WRITING/REQUEST/RESPONSE 共用 identity，ACK 后容量归还。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identity = _publish_request(server, client, {"value": 1})
            request = server.poll_request()
            assert request is not None
            assert request.identity == identity
            server.publish_json_response(
                identity=request.identity,
                payload={"state": "succeeded", "value": 2},
            )
            response = client.read_response(identity=identity)
            assert response is not None
            assert response.json_payload() == {"state": "succeeded", "value": 2}
            client.acknowledge(identity=identity)
            sweep = server.sweep()
            assert sweep["released_identities"] == (identity,)
            assert server.build_status()["descriptor_state_counts"][0] == 128


@pytest.mark.parametrize("public_payload_bytes", (256 * 1024, 1024 * 1024))
def test_structured_response_uses_common_page_chain_without_data_loss(
    tmp_path: Path,
    public_payload_bytes: int,
) -> None:
    """不可压缩结构化结果跨多个 common page 后仍逐字节一致。"""

    encoded = base64.b64encode(os.urandom(public_payload_bytes))
    payload = json.dumps(
        {"state": "succeeded", "data": encoded.decode("ascii")},
        separators=(",", ":"),
    ).encode("utf-8")
    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identity = _publish_request(server, client, {})
            request = server.poll_request()
            assert request is not None
            server.publish_response(identity=request.identity, payload=payload)
            response = client.read_response(identity=identity)
            assert response is not None
            assert response.payload == payload
            assert server.build_status()["used_page_count"] > 0
            client.acknowledge(identity=identity)
            server.sweep()
            assert server.build_status()["used_page_count"] == 0


def test_compressible_large_json_remains_inline_after_common_compression(
    tmp_path: Path,
) -> None:
    """通用 Mailbox 压缩有收益时不占用 overflow page。"""

    payload = json.dumps(
        {"state": "succeeded", "mask": "A" * (1024 * 1024)},
        separators=(",", ":"),
    ).encode("utf-8")
    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identity = _publish_request(server, client, {})
            request = server.poll_request()
            assert request is not None
            server.publish_response(identity=request.identity, payload=payload)
            response = client.read_response(identity=identity)
            assert response is not None
            assert response.payload == payload
            assert server.build_status()["used_page_count"] == 0
            client.acknowledge(identity=identity)
            server.sweep()


def test_public_response_keeps_exact_32_mib_boundary_after_envelope(
    tmp_path: Path,
) -> None:
    """版本化 envelope 不能使旧链路的 32 MiB 公开 JSON 边界回退。"""

    prefix = b'{"state":"succeeded","data":"'
    suffix = b'"}'
    payload = prefix + b"A" * (
        MAILBOX_PUBLIC_RESPONSE_CAPACITY_BYTES - len(prefix) - len(suffix)
    ) + suffix
    assert len(payload) == MAILBOX_PUBLIC_RESPONSE_CAPACITY_BYTES
    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identity = _publish_request(server, client, {})
            request = server.poll_request()
            assert request is not None
            assert (
                server.publish_response(identity=request.identity, payload=payload)
                == contract.ERROR_CODE_NONE
            )
            response = client.read_response(identity=identity)
            assert response is not None
            assert response.payload == payload
            client.acknowledge(identity=identity)
            assert server.sweep()["released_count"] == 1


def test_oversized_public_response_returns_readable_business_error(
    tmp_path: Path,
) -> None:
    """超过 32 MiB 时发布稳定紧凑终态，不伪装成 server failure。"""

    payload = b'{"data":"' + b"A" * MAILBOX_PUBLIC_RESPONSE_CAPACITY_BYTES + b'"}'
    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identity = _publish_request(server, client, {})
            request = server.poll_request()
            assert request is not None
            assert (
                server.publish_response(identity=request.identity, payload=payload)
                == contract.ERROR_CODE_TRIGGER_RESPONSE_TOO_LARGE
            )
            response = client.read_response(identity=identity)
            assert response is not None
            assert response.error_code == contract.ERROR_CODE_TRIGGER_RESPONSE_TOO_LARGE
            assert response.json_payload()["error_code"] == (
                contract.ERROR_CODE_TRIGGER_RESPONSE_TOO_LARGE
            )
            client.acknowledge(identity=identity)
            assert server.sweep()["released_count"] == 1


def test_server_authoritative_deadline_returns_readable_terminal(
    tmp_path: Path,
) -> None:
    """client 只提交相对 timeout，server 到期后发布可 ACK 的稳定错误。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            claimed = client.claim(timeout_ms=1, route_generation=7)
            prepare = server.poll_prepare()
            assert prepare is not None
            assert claimed.deadline_ns == 0
            assert prepare.identity.deadline_ns > 0
            result = server.sweep(now_ns=prepare.identity.deadline_ns + 1)
            assert result["deadline_exceeded_identities"] == (prepare.identity,)
            response = client.read_response(identity=claimed)
            assert response is not None
            assert response.error_code == contract.ERROR_CODE_DEADLINE_EXCEEDED
            client.acknowledge(identity=claimed)
            assert server.sweep()["released_count"] == 1


def test_writing_cancel_reclaims_without_runtime_request(tmp_path: Path) -> None:
    """图片写入阶段取消会传播并回收 descriptor，不产生最终 REQUEST。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            claimed = client.claim(timeout_ms=5_000, route_generation=1)
            prepare = server.poll_prepare()
            assert prepare is not None
            server.publish_writing(
                identity=prepare.identity,
                allocation_payload=b'{"input_attachment":null}',
            )
            allocation = client.read_writing_allocation(identity=claimed)
            assert allocation is not None
            client.cancel(identity=allocation.identity)
            sweep = server.sweep()
            assert sweep["cancelled_identities"] == (prepare.identity,)
            assert server.poll_request() is None
            assert server.build_status()["descriptor_state_counts"][0] == 128


def test_response_ack_timeout_is_distinct_and_reclaims_pages(tmp_path: Path) -> None:
    """结果消费超时独立于 request deadline，并回收 common page-chain。"""

    payload = json.dumps(
        {"state": "succeeded", "data": base64.b64encode(b"X" * 400_000).decode()},
        separators=(",", ":"),
    ).encode()
    with WorkflowTriggerMailboxServer(
        buffers_root=tmp_path,
        response_ack_timeout_ms=5,
    ) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identity = _publish_request(server, client, {})
            request = server.poll_request()
            assert request is not None
            server.publish_response(identity=request.identity, payload=payload)
            sleep(0.02)
            result = server.sweep()
            assert result["response_ack_timeout_identities"] == (identity,)
            assert server.build_status()["used_page_count"] == 0
            with pytest.raises(InvalidRequestError):
                client.read_response(identity=identity)


def test_concurrent_mixed_responses_keep_identity_and_recover_all_pages(
    tmp_path: Path,
) -> None:
    """16 个并发结果不串页、不串 identity，释放后资源守恒。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            identities = tuple(
                _publish_request(server, client, {"index": index})
                for index in range(16)
            )
            requests = tuple(server.poll_request() for _ in identities)
            assert all(request is not None for request in requests)
            payloads = tuple(
                json.dumps(
                    {
                        "state": "succeeded",
                        "index": index,
                        "data": base64.b64encode(
                            bytes([index + 1]) * (70_000 + index * 1_003)
                        ).decode(),
                    },
                    separators=(",", ":"),
                ).encode()
                for index in range(16)
            )
            with ThreadPoolExecutor(max_workers=16) as executor:
                futures = tuple(
                    executor.submit(
                        server.publish_response,
                        identity=request.identity,
                        payload=payload,
                    )
                    for request, payload in zip(requests, payloads, strict=True)
                    if request is not None
                )
                for future in futures:
                    assert future.result() == contract.ERROR_CODE_NONE
            for identity, payload in zip(identities, payloads, strict=True):
                response = client.read_response(identity=identity)
                assert response is not None
                assert response.payload == payload
                client.acknowledge(identity=identity)
            assert server.sweep()["released_count"] == 16
            assert server.build_status()["used_page_count"] == 0


def test_invalid_or_oversized_structured_request_is_rejected_before_claim(
    tmp_path: Path,
) -> None:
    """非 JSON 与超过 64 KiB wire envelope 的请求不能占用 descriptor。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
            with pytest.raises(InvalidRequestError):
                client.claim(
                    timeout_ms=5_000,
                    route_generation=1,
                    prepare_payload=b"not-json",
                )
            with pytest.raises(InvalidRequestError, match="64 KiB"):
                client.claim(
                    timeout_ms=5_000,
                    route_generation=1,
                    prepare_payload=json.dumps({"data": "X" * 70_000}).encode(),
                )
            assert server.build_status()["descriptor_state_counts"][0] == 128


def test_restart_fences_old_client_and_single_owner_is_enforced(tmp_path: Path) -> None:
    """owner epoch 重启 fence 旧 identity，且同一 Channel 只允许单 owner。"""

    server = WorkflowTriggerMailboxServer(buffers_root=tmp_path)
    client = WorkflowTriggerMailboxClient(buffers_root=tmp_path)
    identity = client.claim(timeout_ms=5_000, route_generation=1)
    old_epoch = server.server_epoch
    with pytest.raises(MmapOwnerLockBusyError):
        WorkflowTriggerMailboxServer(buffers_root=tmp_path)
    server.close()
    try:
        with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as restarted:
            assert restarted.server_epoch != old_epoch
            with pytest.raises(InvalidRequestError):
                client.cancel(identity=identity)
    finally:
        client.close()


def test_frozen_path_and_file_size_use_neutral_local_message_root(
    tmp_path: Path,
) -> None:
    """正式 Trigger 文件不再依赖旧 workflow-trigger 私有目录。"""

    with WorkflowTriggerMailboxServer(buffers_root=tmp_path) as server:
        assert server.path == (
            tmp_path / "local-message" / "workflow-trigger" / "mailbox.mmap"
        ).resolve()
        assert server.path.stat().st_size == MAILBOX_FILE_SIZE_BYTES
        with server.path.open("rb") as handle:
            assert handle.read(8) == b"AMVLMSG\0"


def test_workflow_trigger_owner_rejects_legacy_layout(tmp_path: Path) -> None:
    """旧 Trigger 私有 mailbox 存在时不能静默启动第二套协议。"""

    legacy_path = tmp_path / "workflow-trigger" / "workflow-trigger-main.mmap"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(b"legacy")
    with pytest.raises(ChannelLegacyLayoutError, match="旧 LocalMessage layout"):
        WorkflowTriggerMailboxServer(buffers_root=tmp_path)
    assert not (
        tmp_path / "local-message" / "workflow-trigger" / "mailbox.mmap"
    ).exists()


def _publish_request(
    server: WorkflowTriggerMailboxServer,
    client: WorkflowTriggerMailboxClient,
    payload: dict[str, object],
):
    """完成两阶段握手并返回 authoritative identity。"""

    claimed = client.claim(
        timeout_ms=5_000,
        route_generation=7,
        prepare_payload=b'{"trigger_source_id":"source-1"}',
    )
    prepare = server.poll_prepare()
    assert prepare is not None
    server.publish_writing(
        identity=prepare.identity,
        allocation_payload=b'{"input_attachment":null}',
    )
    allocation = client.read_writing_allocation(identity=claimed)
    assert allocation is not None
    client.publish_request(
        identity=allocation.identity,
        payload=json.dumps(payload, separators=(",", ":")).encode(),
    )
    return allocation.identity
