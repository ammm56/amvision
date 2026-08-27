"""LocalMessage 阶段 1 独立 engine 的状态、故障与资源门禁。"""

from __future__ import annotations

from pathlib import Path
from multiprocessing.context import BaseContext
from threading import Event, Thread
from time import monotonic_ns, sleep
from uuid import UUID, uuid4
import hashlib
import json
import os

import pytest

from backend.contracts.ipc.local_message_profiles import (
    EventRingChannelProfile,
    INFERENCE_MAILBOX_PROFILE_V1,
    MailboxChannelProfile,
    TRAINING_TELEMETRY_EVENT_PROFILE_V1,
    WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1,
)
from backend.service.application.message_channels.codec import (
    WireEnvelope,
    decode_raw_json_object_envelope,
    decode_wire_envelope,
    encode_raw_json_object_envelope,
    encode_wire_envelope,
)
from backend.service.application.message_channels.errors import (
    ChannelCancelledError,
    ChannelCapacityExhaustedError,
    ChannelCorruptMessageError,
    ChannelInvalidMessageError,
    ChannelRestartedError,
)
from backend.service.application.message_channels.models import EventPublishResult
from backend.service.infrastructure.ipc.local_message.common_layout import (
    PAGE_STATE_RESERVED,
    MAILBOX_PAGE_HEADER,
    MAILBOX_STATE_WRITING_REQUEST,
    mailbox_layout,
)
from backend.service.infrastructure.ipc.local_message import common_layout as layout_contract
from backend.service.infrastructure.ipc.local_message.event_ring import (
    MmapEventRingPublisher,
    MmapEventRingReader,
)
from backend.service.infrastructure.ipc.local_message.paths import (
    build_local_message_channel_paths,
)
from backend.service.infrastructure.ipc.local_message.mailbox import (
    MmapMailboxClient,
    MmapMailboxServer,
    MailboxTerminalReason,
)
from backend.service.infrastructure.ipc.local_message.registry import (
    LocalMessageChannelRegistry,
)
from backend.service.infrastructure.ipc.multiprocessing_queue_channel import (
    MultiprocessingQueueMailboxClient,
    MultiprocessingQueueMailboxServer,
)
from backend.service.infrastructure.ipc.mmap_primitives import (
    MmapGuardFileError,
    MmapOwnerLockBusyError,
    acquire_mmap_owner_lock,
)


MAILBOX_PROFILE = MailboxChannelProfile(
    profile_id="test-mailbox.v1",
    descriptor_count=4,
    inline_request_capacity_bytes=128,
    inline_response_capacity_bytes=128,
    overflow_page_capacity_bytes=64,
    overflow_page_count=8,
    max_overflow_pages_per_response=4,
    max_request_bytes=128,
    max_response_bytes=256,
    compression_threshold_bytes=64,
    poll_interval_seconds=0.001,
)
EVENT_PROFILE = EventRingChannelProfile(
    profile_id="test-event.v1",
    slot_count=4,
    payload_capacity_bytes=64,
    poll_interval_seconds=0.001,
    scan_interval_seconds=0.002,
)
ROOT = Path(__file__).resolve().parents[1]
LOCAL_MESSAGE_SCHEMA = (
    ROOT / "backend" / "contracts" / "ipc" / "schemas" / "local_message_channel.v1.json"
)
LOCAL_MESSAGE_FIXTURE = ROOT / "tests" / "fixtures" / "local_message_channel.v1.fixture.json"
DOTNET_LOCAL_MESSAGE_FIXTURE = (
    ROOT
    / "sdks"
    / "dotnet"
    / "tests"
    / "Amvar.Vision.ContractTests"
    / "LocalMessageChannelV1Fixture.g.cs"
)


def _paths(tmp_path: Path, name: str, kind: str):
    """返回隔离测试 Channel 路径。"""

    return build_local_message_channel_paths(
        buffers_root=tmp_path / "buffers",
        channel_name=name,
        channel_kind=kind,
    )


def _deadline(seconds: float = 2.0) -> int:
    """返回测试 monotonic deadline。"""

    return monotonic_ns() + int(seconds * 1e9)


def _cross_process_mailbox_server(
    buffers_root: str,
    ready: object,
    consumed: object,
) -> None:
    """spawn 子进程中的独立 Mailbox owner。"""

    paths = build_local_message_channel_paths(
        buffers_root=buffers_root,
        channel_name="mailbox-process",
        channel_kind="mailbox",
    )
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    ready.set()
    try:
        request = server.receive(deadline_ns=_deadline(10))
        if request is None:
            raise RuntimeError("未收到跨进程 Mailbox request")
        server.publish_response(request, wire_bytes=b"process:" + request.wire_bytes)
        consumed.wait(timeout=10)
        server.sweep()
    finally:
        server.close(deadline_ns=_deadline())


def _hold_mailbox_owner(buffers_root: str, ready: object) -> None:
    """spawn 子进程持续持有 Mailbox owner，供强杀恢复测试使用。"""

    paths = build_local_message_channel_paths(
        buffers_root=buffers_root,
        channel_name="mailbox-kill-recovery",
        channel_kind="mailbox",
    )
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    ready.set()
    try:
        while True:
            sleep(1)
    finally:
        server.close(deadline_ns=_deadline())


def _hold_event_ring_owner(buffers_root: str, ready: object) -> None:
    """spawn 子进程持续持有 EventRing owner，供强杀恢复测试使用。"""

    paths = build_local_message_channel_paths(
        buffers_root=buffers_root,
        channel_name="event-kill-recovery",
        channel_kind="event",
    )
    publisher = MmapEventRingPublisher(paths=paths, profile=EVENT_PROFILE)
    ready.set()
    try:
        while True:
            sleep(1)
    finally:
        publisher.close(deadline_ns=_deadline())


def _round_trip(
    *,
    server: MmapMailboxServer,
    client: MmapMailboxClient,
    request: bytes,
    response: bytes,
):
    """在真实等待线程中完成一次 Mailbox。"""

    failures: list[BaseException] = []

    def serve() -> None:
        try:
            context = server.receive(deadline_ns=_deadline())
            assert context is not None
            assert context.wire_bytes == request
            server.publish_response(context, wire_bytes=response)
        except BaseException as error:  # pragma: no cover - 转交主线程断言
            failures.append(error)

    thread = Thread(target=serve)
    thread.start()
    handle = client.call(
        request_id=uuid4(),
        wire_bytes=request,
        deadline_ns=_deadline(),
    )
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert failures == []
    return handle


def test_wire_envelope_codec_is_compact_and_validated() -> None:
    """Queue 与 mmap 共用的 envelope 只产生不可变 compact bytes。"""

    envelope = WireEnvelope(
        schema_id="test.request.v1",
        payload={"value": 3, "enabled": True},
        correlation_id=uuid4(),
    )
    encoded = encode_wire_envelope(envelope)
    assert isinstance(encoded, bytes)
    assert b" " not in encoded
    assert decode_wire_envelope(encoded) == envelope


def test_raw_json_object_fast_path_is_byte_identical_to_common_codec() -> None:
    """大 JSON 快路径只改变构造方式，不改变 envelope wire contract。"""

    correlation_id = UUID("00112233-4455-6677-8899-aabbccddeeff")
    payload = b'{"value":3,"nested":{"enabled":true}}'
    regular = encode_wire_envelope(
        WireEnvelope(
            schema_id="test.request.v1",
            payload={"value": 3, "nested": {"enabled": True}},
            correlation_id=correlation_id,
        )
    )
    fast = encode_raw_json_object_envelope(
        schema_id="test.request.v1",
        payload=payload,
        correlation_id=correlation_id,
    )
    assert fast == regular
    assert decode_raw_json_object_envelope(
        fast,
        expected_schema_id="test.request.v1",
        correlation_id=correlation_id,
    ) == payload


def test_raw_json_object_fast_path_rejects_wrong_fence_or_non_object() -> None:
    """快路径仍严格校验 schema/correlation fence 和 object 边界。"""

    correlation_id = uuid4()
    with pytest.raises(ChannelInvalidMessageError):
        # 只要不是 object，就不得生成可发布 envelope。
        encode_raw_json_object_envelope(
            schema_id="test.request.v1",
            payload=b"[]",
            correlation_id=correlation_id,
        )
    encoded = encode_raw_json_object_envelope(
        schema_id="test.request.v1",
        payload=b"{}",
        correlation_id=correlation_id,
    )
    with pytest.raises(ChannelInvalidMessageError, match="identity"):
        decode_raw_json_object_envelope(
            encoded,
            expected_schema_id="other.request.v1",
            correlation_id=correlation_id,
        )


def test_binary_schema_python_fixture_and_dotnet_fixture_are_identical() -> None:
    """common/Mailbox/Event little-endian bytes 与 .NET Trigger fixture 必须逐字节稳定。"""

    fixture = json.loads(LOCAL_MESSAGE_FIXTURE.read_text(encoding="utf-8"))
    schema = json.loads(LOCAL_MESSAGE_SCHEMA.read_text(encoding="utf-8"))
    assert fixture["contract_id"] == schema["contract_id"]
    assert fixture["schema_sha256"] == hashlib.sha256(
        LOCAL_MESSAGE_SCHEMA.read_bytes()
    ).hexdigest()

    workflow_profile = WORKFLOW_TRIGGER_MAILBOX_PROFILE_V1
    workflow = layout_contract.mailbox_layout(workflow_profile)
    inference = layout_contract.mailbox_layout(INFERENCE_MAILBOX_PROFILE_V1)
    telemetry_profile = TRAINING_TELEMETRY_EVENT_PROFILE_V1
    telemetry = layout_contract.event_layout(telemetry_profile)
    common = layout_contract.COMMON_HEADER.pack(
        layout_contract.FILE_MAGIC,
        layout_contract.FILE_VERSION,
        layout_contract.CHANNEL_KIND_MAILBOX,
        layout_contract.ENDIAN_MARKER,
        workflow.fingerprint,
        0x0011223344556677,
        0x8899AABBCCDDEEFF,
        0x0102030405060708,
        0x1112131415161718,
        0x11223344,
        0,
    )
    assert common.hex() == fixture["packed_hex"]["common_header"]
    assert len(common) == schema["layouts"]["common_header"]["size"]
    assert workflow.fingerprint.hex() == fixture["layout_fingerprints"]["workflow_trigger_mailbox_v1"]
    assert inference.fingerprint.hex() == fixture["layout_fingerprints"]["inference_mailbox_v1"]
    assert telemetry.fingerprint.hex() == fixture["layout_fingerprints"]["training_telemetry_event_v1"]
    assert workflow.file_size_bytes == fixture["file_sizes"]["workflow_trigger_mailbox_v1"]
    assert inference.file_size_bytes == fixture["file_sizes"]["inference_mailbox_v1"]
    assert telemetry.file_size_bytes == fixture["file_sizes"]["training_telemetry_event_v1"]

    mailbox_profile_header = layout_contract.MAILBOX_HEADER.pack(
        workflow_profile.descriptor_count,
        layout_contract.MAILBOX_DESCRIPTOR_HEADER_SIZE,
        workflow.descriptor_stride_bytes,
        workflow_profile.inline_request_capacity_bytes,
        workflow_profile.inline_response_capacity_bytes,
        layout_contract.MAILBOX_PAGE_HEADER_SIZE,
        workflow_profile.overflow_page_capacity_bytes,
        workflow_profile.overflow_page_count,
        workflow_profile.max_overflow_pages_per_response,
        workflow_profile.max_request_bytes,
        workflow_profile.max_response_bytes,
        workflow_profile.compression_threshold_bytes,
        workflow.descriptor_region_offset,
        workflow.page_region_offset,
        workflow.file_size_bytes,
        int(workflow_profile.poll_interval_seconds * 1e9),
        layout_contract.encode_profile_id(workflow_profile.profile_id),
    )
    descriptor = layout_contract.MAILBOX_DESCRIPTOR_HEADER.pack(
        layout_contract.MAILBOX_STATE_REQUEST,
        0,
        0x0102030405060708,
        0x1112131415161718,
        UUID("00112233-4455-6677-8899-aabbccddeeff").bytes,
        0x2122232425262728,
        0x3132333435363738,
        3,
        0x352441C2,
        0,
        0,
        layout_contract.NO_PAGE_INDEX,
        0,
        0,
        0,
        0,
        0x4142434445464748,
    )
    page = layout_contract.MAILBOX_PAGE_HEADER.pack(
        layout_contract.PAGE_STATE_PUBLISHED,
        0,
        3,
        2,
        0x0102030405060708,
        layout_contract.NO_PAGE_INDEX,
        4,
        0xDB1720A5,
        0x5152535455565758,
        0x1112131415161718,
    )
    event_profile_header = layout_contract.EVENT_HEADER.pack(
        telemetry_profile.slot_count,
        layout_contract.EVENT_SLOT_HEADER_SIZE,
        telemetry_profile.payload_capacity_bytes,
        telemetry.slot_stride_bytes,
        0,
        0,
        7,
        2,
        int(telemetry_profile.poll_interval_seconds * 1e9),
        int(telemetry_profile.scan_interval_seconds * 1e9),
        UUID("00112233-4455-6677-8899-aabbccddeeff").bytes,
        telemetry.slot_region_offset,
        telemetry.file_size_bytes,
        layout_contract.encode_profile_id(telemetry_profile.profile_id),
    )
    event_slot = layout_contract.EVENT_SLOT_HEADER.pack(
        2,
        7,
        4,
        0xDB1720A5,
        0x1112131415161718,
        0,
    )
    packed = fixture["packed_hex"]
    assert mailbox_profile_header.hex() == packed["mailbox_profile_header"]
    assert descriptor.hex() == packed["mailbox_descriptor_header"]
    assert page.hex() == packed["mailbox_page_header"]
    assert hashlib.sha256(event_profile_header).hexdigest() == fixture["packed_sha256"]["event_profile_header"]
    assert event_slot.hex() == packed["event_slot_header"]

    dotnet = DOTNET_LOCAL_MESSAGE_FIXTURE.read_text(encoding="utf-8")
    assert common[:88].hex() in dotnet
    assert mailbox_profile_header[:144].hex() in dotnet
    for fixture_name in ("mailbox_descriptor_header", "mailbox_page_header"):
        assert fixture["packed_hex"][fixture_name] in dotnet


def test_mailbox_inline_page_compression_ack_and_resource_recovery(tmp_path: Path) -> None:
    """inline、不可压缩 page-chain、压缩、ACK 后均恢复全部资源。"""

    paths = _paths(tmp_path, "mailbox-main", "mailbox")
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    client = MmapMailboxClient(paths=paths, profile=MAILBOX_PROFILE)
    try:
        inline = _round_trip(
            server=server,
            client=client,
            request=b"request",
            response=b"inline-response",
        )
        assert inline.wire_bytes == b"inline-response"
        inline.close()
        server.sweep()

        page_payload = os.urandom(220)
        page = _round_trip(
            server=server,
            client=client,
            request=b"page",
            response=page_payload,
        )
        assert page.wire_bytes == page_payload
        assert server.health().free_pages < MAILBOX_PROFILE.overflow_page_count
        page.ack()
        server.sweep()

        compressed_payload = b"A" * 240
        compressed = _round_trip(
            server=server,
            client=client,
            request=b"compressed",
            response=compressed_payload,
        )
        assert compressed.wire_bytes == compressed_payload
        compressed.close()
        server.sweep()

        health = server.health()
        assert health.free_descriptors == MAILBOX_PROFILE.descriptor_count
        assert health.free_pages == MAILBOX_PROFILE.overflow_page_count
        assert health.requests_total == 3
        assert health.responses_total == 3
        assert health.acknowledgements_total == 3
    finally:
        client.close(deadline_ns=_deadline())
        server.close(deadline_ns=_deadline())


def test_mailbox_prepared_descriptor_reuses_identity_and_preserves_extension(
    tmp_path: Path,
) -> None:
    """PREPARE response 可在同一 descriptor 上转回 REQUEST，且只建立一次 deadline。"""

    paths = _paths(tmp_path, "mailbox-prepared", "mailbox")
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    client = MmapMailboxClient(paths=paths, profile=MAILBOX_PROFILE)
    prepare_extension = b"prepare.v1"
    writing_extension = b"writing.v1"
    request_extension = b"request.v1"
    response_extension = b"response.v1"
    try:
        identity = client.claim_prepared(
            request_id=uuid4(),
            wire_bytes=b"prepare",
            claim_deadline_ns=_deadline(),
            descriptor_extension=prepare_extension,
        )
        prepare = server.receive(deadline_ns=_deadline())
        assert prepare is not None
        assert prepare.deadline_ns == (1 << 64) - 1
        assert server.read_processing_extension(
            prepare, size=len(prepare_extension)
        ) == prepare_extension

        accepted_deadline_ns = _deadline(1)
        prepare = server.update_processing_deadline(
            prepare,
            deadline_ns=accepted_deadline_ns,
        )
        server.write_processing_extension(
            prepare,
            extension=writing_extension,
        )
        server.publish_response(prepare, wire_bytes=b"allocation")

        allocation = client.try_read_response_snapshot(identity)
        assert allocation is not None
        assert allocation.wire_bytes == b"allocation"
        assert allocation.deadline_ns == accepted_deadline_ns
        assert allocation.extension.startswith(writing_extension)
        client.reopen_response_for_request(
            identity,
            descriptor_extension=writing_extension,
        )
        client.publish_reopened_request(
            identity,
            wire_bytes=b"request",
            descriptor_extension=request_extension,
        )

        request = server.receive(deadline_ns=_deadline())
        assert request is not None
        assert request.request_id == prepare.request_id
        assert request.deadline_ns == accepted_deadline_ns
        assert server.transport_identity(request) == identity
        assert server.read_processing_extension(
            request, size=len(request_extension)
        ) == request_extension
        server.write_processing_extension(
            request,
            extension=response_extension,
        )
        server.publish_response(request, wire_bytes=b"result")

        result = client.try_read_response_snapshot(identity)
        assert result is not None
        assert result.wire_bytes == b"result"
        assert result.extension.startswith(response_extension)
        client.acknowledge(identity)
        events = server.sweep()
        assert len(events) == 1
        assert events[0].identity == identity
        assert events[0].reason == MailboxTerminalReason.ACKNOWLEDGED
        assert server.drain_terminal_events() == events
        assert server.health().free_descriptors == MAILBOX_PROFILE.descriptor_count
    finally:
        client.close(deadline_ns=_deadline())
        server.close(deadline_ns=_deadline())


def test_mailbox_prepared_writing_cancel_is_terminal_and_reclaimed(tmp_path: Path) -> None:
    """两阶段调用在 WRITING 取消时不遗留 descriptor 或业务终态事件。"""

    paths = _paths(tmp_path, "mailbox-prepared-cancel", "mailbox")
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    client = MmapMailboxClient(paths=paths, profile=MAILBOX_PROFILE)
    try:
        identity = client.claim_prepared(
            request_id=uuid4(),
            wire_bytes=b"prepare",
            claim_deadline_ns=_deadline(),
            descriptor_extension=b"prepare",
        )
        prepare = server.receive(deadline_ns=_deadline())
        assert prepare is not None
        prepare = server.update_processing_deadline(
            prepare,
            deadline_ns=_deadline(1),
        )
        server.publish_response(prepare, wire_bytes=b"allocation")
        assert client.try_read_response_snapshot(identity) is not None
        client.reopen_response_for_request(identity, descriptor_extension=b"writing")
        client.request_cancel(identity)

        events = server.sweep()
        assert len(events) == 1
        assert events[0].reason == MailboxTerminalReason.CANCELLED
        assert server.health().free_descriptors == MAILBOX_PROFILE.descriptor_count
    finally:
        client.close(deadline_ns=_deadline())
        server.close(deadline_ns=_deadline())


def test_mailbox_page_pool_exhaustion_is_explicit_and_inline_stays_available(
    tmp_path: Path,
) -> None:
    """page pool 满载必须返回 capacity，且不能阻塞无需 page 的响应。"""

    paths = _paths(tmp_path, "mailbox-capacity", "mailbox")
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    client = MmapMailboxClient(paths=paths, profile=MAILBOX_PROFILE)
    first = second = inline = None
    try:
        first = _round_trip(
            server=server,
            client=client,
            request=b"first",
            response=os.urandom(220),
        )
        second = _round_trip(
            server=server,
            client=client,
            request=b"second",
            response=os.urandom(220),
        )
        assert server.health().free_pages == 0

        publication_errors: list[BaseException] = []

        def publish_when_full() -> None:
            request = server.receive(deadline_ns=_deadline())
            assert request is not None
            try:
                server.publish_response(request, wire_bytes=os.urandom(220))
            except BaseException as error:  # noqa: BLE001 - 转交主线程断言
                publication_errors.append(error)

        publisher = Thread(target=publish_when_full)
        publisher.start()
        with pytest.raises(ChannelCapacityExhaustedError):
            client.call(
                request_id=uuid4(),
                wire_bytes=b"full",
                deadline_ns=_deadline(),
            )
        publisher.join(timeout=3)
        assert not publisher.is_alive()
        assert len(publication_errors) == 1
        assert isinstance(publication_errors[0], ChannelCapacityExhaustedError)
        server.sweep()

        inline = _round_trip(
            server=server,
            client=client,
            request=b"inline",
            response=b"available",
        )
        assert inline.wire_bytes == b"available"
        assert server.health().capacity_rejections_total == 1
    finally:
        for handle in (first, second, inline):
            if handle is not None:
                handle.close()
        server.sweep()
        client.close(deadline_ns=_deadline())
        server.close(deadline_ns=_deadline())


def test_mailbox_page_chain_crc_corruption_is_rejected(tmp_path: Path) -> None:
    """page publication 后正文损坏必须在 ACK 前被 client 拒绝。"""

    paths = _paths(tmp_path, "mailbox-corrupt", "mailbox")
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    client = MmapMailboxClient(paths=paths, profile=MAILBOX_PROFILE)
    try:
        identity = client._claim_descriptor(
            request_id=uuid4(), payload=b"x", deadline_ns=_deadline()
        )
        context = server.receive(deadline_ns=_deadline())
        assert context is not None
        server.publish_response(context, wire_bytes=os.urandom(220))
        layout = mailbox_layout(MAILBOX_PROFILE)
        header = server._read_descriptor(identity.descriptor_index)
        first_page = int(header[11])
        page_offset = layout.page_region_offset + first_page * layout.page_stride_bytes
        server._require_view()[page_offset + MAILBOX_PAGE_HEADER.size] ^= 0xFF
        with pytest.raises(ChannelCorruptMessageError, match="CRC"):
            client._read_response(identity, client._read_descriptor(identity.descriptor_index))
    finally:
        client.close(deadline_ns=_deadline())
        server.close(deadline_ns=monotonic_ns())


class _Cancellation:
    """测试 CancellationSource。"""

    def __init__(self) -> None:
        self.event = Event()

    def is_cancelled(self) -> bool:
        """返回测试事件。"""

        return self.event.is_set()


def test_mailbox_processing_observes_cancel_and_sweep_reclaims(tmp_path: Path) -> None:
    """PROCESSING 能观察取消，终态经 ACK/sweep 回收。"""

    paths = _paths(tmp_path, "mailbox-cancel", "mailbox")
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    client = MmapMailboxClient(paths=paths, profile=MAILBOX_PROFILE)
    cancellation = _Cancellation()
    claimed = Event()
    observed: list[bool] = []

    def serve() -> None:
        context = server.receive(deadline_ns=_deadline())
        assert context is not None
        claimed.set()
        cancellation.event.wait(timeout=2)
        # client 先发布 cancel flag，然后 call 才抛错。
        for _ in range(100):
            if context.cancelled:
                break
            Event().wait(0.001)
        observed.append(context.cancelled)
        server.sweep()

    thread = Thread(target=serve)
    thread.start()
    try:
        def cancel_after_claim() -> None:
            claimed.wait(timeout=2)
            cancellation.event.set()

        canceller = Thread(target=cancel_after_claim)
        canceller.start()
        with pytest.raises(ChannelCancelledError):
            client.call(
                request_id=uuid4(),
                wire_bytes=b"cancel",
                deadline_ns=_deadline(),
                cancellation=cancellation,
            )
        canceller.join(timeout=2)
        thread.join(timeout=3)
        assert observed == [True]
        server.sweep()
    finally:
        client.close(deadline_ns=_deadline())
        server.close(deadline_ns=monotonic_ns())


def test_independent_mailbox_channels_do_not_share_page_capacity(tmp_path: Path) -> None:
    """一个 Channel 的 page pool 使用量不影响另一个 Channel。"""

    first_paths = _paths(tmp_path, "mailbox-first", "mailbox")
    second_paths = _paths(tmp_path, "mailbox-second", "mailbox")
    first_server = MmapMailboxServer(paths=first_paths, profile=MAILBOX_PROFILE)
    second_server = MmapMailboxServer(paths=second_paths, profile=MAILBOX_PROFILE)
    first_client = MmapMailboxClient(paths=first_paths, profile=MAILBOX_PROFILE)
    second_client = MmapMailboxClient(paths=second_paths, profile=MAILBOX_PROFILE)
    first_handle = second_handle = None
    try:
        first_handle = _round_trip(
            server=first_server,
            client=first_client,
            request=b"first",
            response=os.urandom(220),
        )
        assert first_server.health().free_pages < MAILBOX_PROFILE.overflow_page_count
        assert second_server.health().free_pages == MAILBOX_PROFILE.overflow_page_count
        second_handle = _round_trip(
            server=second_server,
            client=second_client,
            request=b"second",
            response=os.urandom(220),
        )
        assert second_handle.wire_bytes
    finally:
        if first_handle is not None:
            first_handle.close()
        if second_handle is not None:
            second_handle.close()
        first_server.sweep()
        second_server.sweep()
        first_client.close(deadline_ns=_deadline())
        second_client.close(deadline_ns=_deadline())
        first_server.close(deadline_ns=_deadline())
        second_server.close(deadline_ns=_deadline())


@pytest.mark.parametrize(
    "fault_stage",
    ("writing_request", "processing", "page_reserved", "response", "ack"),
)
def test_mailbox_owner_restart_recovers_every_publication_stage(
    tmp_path: Path,
    fault_stage: str,
) -> None:
    """owner 在 request/page/response/ACK 任一点退出后，新 epoch 不复用脏状态。"""

    paths = _paths(tmp_path, f"mailbox-crash-{fault_stage.replace('_', '-')}", "mailbox")
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    client = MmapMailboxClient(paths=paths, profile=MAILBOX_PROFILE)
    identity = client._claim_descriptor(
        request_id=uuid4(), payload=b"crash", deadline_ns=_deadline(10)
    )
    if fault_stage == "writing_request":
        server._require_view()[server._descriptor_offset(identity.descriptor_index) : server._descriptor_offset(identity.descriptor_index) + 4] = MAILBOX_STATE_WRITING_REQUEST.to_bytes(4, "little")
    else:
        request = server.receive(deadline_ns=_deadline())
        assert request is not None
        if fault_stage == "page_reserved":
            first_page, _ = server._require_page_pool().reserve_write_publish(
                descriptor_index=identity.descriptor_index,
                descriptor_generation=identity.generation,
                payload=os.urandom(220),
            )
            page_offset = (
                mailbox_layout(MAILBOX_PROFILE).page_region_offset
                + first_page * mailbox_layout(MAILBOX_PROFILE).page_stride_bytes
            )
            server._require_view()[page_offset : page_offset + 4] = PAGE_STATE_RESERVED.to_bytes(4, "little")
        elif fault_stage in {"response", "ack"}:
            server.publish_response(request, wire_bytes=os.urandom(220))
            if fault_stage == "ack":
                client._ack(identity)

    old_epoch = server.owner_epoch
    old_channel_id = server.channel_id
    client._close_handles()
    server._close_handles()
    server._closed = True

    restarted = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    try:
        assert restarted.owner_epoch != old_epoch
        assert restarted.channel_id == old_channel_id
        health = restarted.health()
        assert health.free_descriptors == MAILBOX_PROFILE.descriptor_count
        assert health.free_pages == MAILBOX_PROFILE.overflow_page_count
    finally:
        restarted.close(deadline_ns=_deadline())


def test_mailbox_cross_process_owner_client_and_os_guards(tmp_path: Path) -> None:
    """真实 spawn 进程通过同一 mmap/guard 完成 request、response 与 ACK。"""

    import multiprocessing

    context: BaseContext = multiprocessing.get_context("spawn")
    ready = context.Event()
    consumed = context.Event()
    process = context.Process(
        target=_cross_process_mailbox_server,
        args=(str(tmp_path / "buffers"), ready, consumed),
    )
    process.start()
    assert ready.wait(timeout=10)
    paths = _paths(tmp_path, "mailbox-process", "mailbox")
    client = MmapMailboxClient(paths=paths, profile=MAILBOX_PROFILE)
    try:
        handle = client.call(
            request_id=uuid4(),
            wire_bytes=b"hello",
            deadline_ns=_deadline(10),
        )
        assert handle.wire_bytes == b"process:hello"
        handle.close()
        consumed.set()
    finally:
        client.close(deadline_ns=_deadline())
    process.join(timeout=15)
    assert process.exitcode == 0


def test_mailbox_forced_owner_exit_releases_os_lock(tmp_path: Path) -> None:
    """Mailbox server 被强杀后，遗留 owner.lock 文件不阻塞新 owner。"""

    import multiprocessing

    context: BaseContext = multiprocessing.get_context("spawn")
    ready = context.Event()
    buffers_root = tmp_path / "buffers"
    process = context.Process(
        target=_hold_mailbox_owner,
        args=(str(buffers_root), ready),
    )
    process.start()
    paths = build_local_message_channel_paths(
        buffers_root=buffers_root,
        channel_name="mailbox-kill-recovery",
        channel_kind="mailbox",
    )
    try:
        assert ready.wait(timeout=10)
        with pytest.raises(MmapOwnerLockBusyError):
            MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()

        restarted = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
        restarted.close(deadline_ns=_deadline())
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=10)


def test_mailbox_close_keeps_owner_until_exported_view_is_released(
    tmp_path: Path,
) -> None:
    """mmap close 被 view 阻止时保留 owner，释放 view 后可重试关闭。"""

    paths = _paths(tmp_path, "mailbox-close-retry", "mailbox")
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    exported = memoryview(server._require_view())
    with pytest.raises(BufferError):
        server.close(deadline_ns=_deadline())
    with pytest.raises(MmapOwnerLockBusyError):
        MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)

    exported.release()
    server.close(deadline_ns=_deadline())
    restarted = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    restarted.close(deadline_ns=_deadline())


def test_existing_mailbox_missing_guard_fails_closed_and_releases_owner(
    tmp_path: Path,
) -> None:
    """已发布 Mailbox 不允许 client/server 重建 guard，初始化失败也不遗留 owner。"""

    paths = _paths(tmp_path, "mailbox-missing-guard", "mailbox")
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    server.close(deadline_ns=_deadline())
    paths.guard_path.unlink()

    with pytest.raises(MmapGuardFileError, match="guard 文件不存在"):
        MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    assert not paths.guard_path.exists()
    owner = acquire_mmap_owner_lock(paths.owner_lock_path)
    owner.release()


def test_unpublished_mailbox_repairs_partial_guard(tmp_path: Path) -> None:
    """Mailbox 数据文件尚未发布时可收敛首次启动留下的短 guard。"""

    paths = _paths(tmp_path, "mailbox-partial-guard", "mailbox")
    paths.guard_path.parent.mkdir(parents=True)
    paths.guard_path.write_bytes(b"x")

    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    try:
        assert paths.guard_path.stat().st_size == MAILBOX_PROFILE.descriptor_count
    finally:
        server.close(deadline_ns=_deadline())


def test_mailbox_stale_open_client_is_fenced_by_new_owner_epoch(tmp_path: Path) -> None:
    """旧 client mapping 保持打开时，新 owner 仍能接管并使旧调用返回 restarted。"""

    paths = _paths(tmp_path, "mailbox-live-restart", "mailbox")
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    stale_client = MmapMailboxClient(paths=paths, profile=MAILBOX_PROFILE)
    old_epoch = stale_client.owner_epoch
    old_channel_id = stale_client.channel_id
    server._close_handles()
    server._closed = True
    restarted = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    current_client = MmapMailboxClient(paths=paths, profile=MAILBOX_PROFILE)
    try:
        assert restarted.owner_epoch != old_epoch
        assert restarted.channel_id == old_channel_id
        with pytest.raises(ChannelRestartedError):
            stale_client.call(
                request_id=uuid4(), wire_bytes=b"stale", deadline_ns=_deadline()
            )
        handle = _round_trip(
            server=restarted,
            client=current_client,
            request=b"current",
            response=b"ok",
        )
        assert handle.wire_bytes == b"ok"
        handle.close()
        restarted.sweep()
    finally:
        stale_client.close(deadline_ns=_deadline())
        current_client.close(deadline_ns=_deadline())
        restarted.close(deadline_ns=_deadline())


def test_event_ring_gap_drop_close_and_owner_restart(tmp_path: Path) -> None:
    """EventRing 覆盖产生 gap，超长 payload 计 drop，close 与重启可区分。"""

    paths = _paths(tmp_path, "event-main", "event")
    publisher = MmapEventRingPublisher(paths=paths, profile=EVENT_PROFILE)
    reader = MmapEventRingReader(paths=paths, profile=EVENT_PROFILE)
    try:
        assert reader.owner_alive() is True
        for index in range(6):
            assert publisher.try_publish(f"event-{index}".encode()) == EventPublishResult.PUBLISHED
        assert publisher.try_publish(b"x" * 65) == EventPublishResult.FULL
        batch = reader.read(cursor=None, deadline_ns=_deadline(), limit=4)
        assert batch.events == (b"event-2", b"event-3", b"event-4", b"event-5")
        assert batch.gap_detected is False
        old_cursor = batch.next_cursor
        old_channel_id = publisher.channel_id
        assert publisher.health().dropped_total == 1
        publisher.close(deadline_ns=_deadline())
        closed_batch = reader.read(
            cursor=old_cursor, deadline_ns=_deadline(), limit=4
        )
        assert closed_batch.producer_closed is True
        assert reader.owner_alive() is False
    finally:
        publisher.close(deadline_ns=_deadline())
        reader.close(deadline_ns=_deadline())

    restarted = MmapEventRingPublisher(paths=paths, profile=EVENT_PROFILE)
    restarted_reader = MmapEventRingReader(paths=paths, profile=EVENT_PROFILE)
    try:
        assert restarted.channel_id == old_channel_id
        with pytest.raises(ChannelRestartedError):
            restarted_reader.read(cursor=old_cursor, deadline_ns=_deadline(), limit=4)
    finally:
        restarted_reader.close(deadline_ns=_deadline())
        restarted.close(deadline_ns=_deadline())


def test_event_ring_forced_owner_exit_releases_os_lock(tmp_path: Path) -> None:
    """producer 被强杀后遗留 lock 文件不阻塞新 owner 与新 epoch。"""

    import multiprocessing

    context: BaseContext = multiprocessing.get_context("spawn")
    ready = context.Event()
    buffers_root = tmp_path / "buffers"
    process = context.Process(
        target=_hold_event_ring_owner,
        args=(str(buffers_root), ready),
    )
    process.start()
    paths = build_local_message_channel_paths(
        buffers_root=buffers_root,
        channel_name="event-kill-recovery",
        channel_kind="event",
    )
    reader: MmapEventRingReader | None = None
    try:
        assert ready.wait(timeout=10)
        reader = MmapEventRingReader(paths=paths, profile=EVENT_PROFILE)
        old_epoch = reader.owner_epoch
        assert reader.owner_alive() is True
        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()
        assert reader.owner_alive() is False

        restarted = MmapEventRingPublisher(paths=paths, profile=EVENT_PROFILE)
        try:
            assert restarted.owner_epoch != old_epoch
        finally:
            restarted.close(deadline_ns=_deadline())
    finally:
        if reader is not None:
            reader.close(deadline_ns=_deadline())
        if process.is_alive():
            process.terminate()
        process.join(timeout=10)


def test_event_ring_reports_gap_for_stale_cursor(tmp_path: Path) -> None:
    """超过 ring 容量的旧 cursor 返回 gap，不伪装为连续事件。"""

    paths = _paths(tmp_path, "event-gap", "event")
    publisher = MmapEventRingPublisher(paths=paths, profile=EVENT_PROFILE)
    reader = MmapEventRingReader(paths=paths, profile=EVENT_PROFILE)
    try:
        publisher.try_publish(b"zero")
        initial = reader.read(cursor=None, deadline_ns=_deadline(), limit=4)
        for index in range(6):
            publisher.try_publish(f"next-{index}".encode())
        batch = reader.read(cursor=initial.next_cursor, deadline_ns=_deadline(), limit=4)
        assert batch.gap_detected is True
        assert batch.events == (b"next-2", b"next-3", b"next-4", b"next-5")
        assert reader.health().reader_gap_total == 1
    finally:
        reader.close(deadline_ns=_deadline())
        publisher.close(deadline_ns=_deadline())


def test_registry_keeps_mailbox_and_event_health_metrics_separate(tmp_path: Path) -> None:
    """common envelope 不把 descriptor/page 字段强加给 EventRing。"""

    mailbox_paths = _paths(tmp_path, "registry-mailbox", "mailbox")
    event_paths = _paths(tmp_path, "registry-event", "event")
    mailbox = MmapMailboxServer(paths=mailbox_paths, profile=MAILBOX_PROFILE)
    event = MmapEventRingPublisher(paths=event_paths, profile=EVENT_PROFILE)
    registry = LocalMessageChannelRegistry()
    registry.register(
        channel_name="mailbox",
        channel_kind="mailbox",
        profile_id=MAILBOX_PROFILE.profile_id,
        health_provider=mailbox.health,
    )
    registry.register(
        channel_name="event",
        channel_kind="event",
        profile_id=EVENT_PROFILE.profile_id,
        health_provider=event.health,
    )
    try:
        snapshot = registry.snapshot()
        assert [item.channel_name for item in snapshot] == ["event", "mailbox"]
        assert snapshot[0].event is not None and snapshot[0].mailbox is None
        assert snapshot[1].mailbox is not None and snapshot[1].event is None
    finally:
        event.close(deadline_ns=_deadline())
        mailbox.close(deadline_ns=_deadline())


def test_paths_and_profile_fingerprint_reject_escape_or_mismatch(tmp_path: Path) -> None:
    """路径逃逸和不同 profile 打开同一文件都必须失败。"""

    with pytest.raises(ValueError):
        build_local_message_channel_paths(
            buffers_root=tmp_path, channel_name="../escape", channel_kind="mailbox"
        )
    paths = _paths(tmp_path, "profile", "mailbox")
    server = MmapMailboxServer(paths=paths, profile=MAILBOX_PROFILE)
    different = MailboxChannelProfile(
        profile_id="different.v1",
        descriptor_count=4,
        inline_request_capacity_bytes=128,
        inline_response_capacity_bytes=128,
        overflow_page_capacity_bytes=128,
        overflow_page_count=4,
        max_overflow_pages_per_response=2,
        max_request_bytes=128,
        max_response_bytes=256,
        compression_threshold_bytes=64,
        poll_interval_seconds=0.001,
    )
    try:
        with pytest.raises(ChannelCorruptMessageError):
            MmapMailboxClient(paths=paths, profile=different)
    finally:
        server.close(deadline_ns=_deadline())


def test_queue_adapter_uses_same_bytes_port_and_noop_ack() -> None:
    """Queue adapter 不传 Python dict，并保持 deadline/response handle 契约。"""

    from queue import Queue

    requests: Queue[object] = Queue()
    responses: Queue[object] = Queue()
    epoch = 123
    server = MultiprocessingQueueMailboxServer(
        request_queue=requests,
        response_queue=responses,
        owner_epoch=epoch,
    )
    client = MultiprocessingQueueMailboxClient(
        request_queue=requests,
        response_queue=responses,
        owner_epoch=epoch,
    )
    failures: list[BaseException] = []

    def serve() -> None:
        try:
            request = server.receive(deadline_ns=_deadline())
            assert request is not None
            assert request.wire_bytes == b"queue-request"
            server.publish_response(request, wire_bytes=b"queue-response")
        except BaseException as error:  # pragma: no cover - 转交主线程断言
            failures.append(error)

    thread = Thread(target=serve)
    thread.start()
    try:
        handle = client.call(
            request_id=uuid4(),
            wire_bytes=b"queue-request",
            deadline_ns=_deadline(),
        )
        assert handle.wire_bytes == b"queue-response"
        handle.ack()
        handle.close()
        thread.join(timeout=3)
        assert failures == []
    finally:
        client.close(deadline_ns=_deadline())
        server.close(deadline_ns=_deadline())
