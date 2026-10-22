"""独立 Python 协议验收客户端，Ubuntu 不冒充 net472 SDK 验收。"""

import json
from pathlib import Path
import sys
from time import monotonic, sleep

from backend.contracts.workflows import (
    WorkflowTriggerAllocationV1,
    WorkflowTriggerRequestV1,
)
from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from backend.contracts.workflows.point_cloud_trigger import (
    WorkflowTriggerCloudPrepareV1,
)
from backend.service.application.local_buffers import LocalBufferBrokerSettings
from backend.service.application.local_buffers.direct_mmap_reader import (
    open_direct_mmap_local_buffer_access,
)
from backend.service.infrastructure.ipc.workflow_trigger_mailbox import (
    WorkflowTriggerMailboxClient,
)


def broker_settings():
    """服务端和 Python 验收客户端共用的显式测试 arena 布局。"""
    return LocalBufferBrokerSettings(
        arena_size_bytes=536870912,
        max_allocation_bytes=268435456,
        reader_guard_slots=8,
        startup_timeout_seconds=30,
        expire_interval_seconds=0.1,
        revocation_grace_seconds=1,
    )


def wait_for(read, *, timeout=30):
    """等待真实协议或进程状态，不改变服务端状态。"""
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        result = read()
        if result:
            return result
        sleep(0.01)
    raise AssertionError("真实状态在显式测试超时内未就绪")


def invoke_cloud(
    root,
    source,
    generation,
    cloud,
    content,
    *,
    timeout_ms=120000,
    hold_writer=None,
    expect_error=False,
):
    """经 PREPARE、WRITING、REQUEST、RESPONSE 和 ACK 完成真实调用。"""
    with WorkflowTriggerMailboxClient(buffers_root=root) as client:
        identity = client.claim_cloud(
            timeout_ms=timeout_ms,
            route_generation=generation,
            prepare_payload=WorkflowTriggerCloudPrepareV1(
                trigger_source_id=source,
                event_id="published-cloud",
                event_payload_key="cloud",
                cloud=cloud,
            )
            .model_dump_json()
            .encode(),
        )
        try:
            outcome = wait_for(
                lambda: (
                    client.read_writing_allocation(identity=identity)
                    or client.read_response(identity=identity)
                )
            )
            if hasattr(outcome, "error_code"):
                response = outcome
            else:
                identity = outcome.identity
                allocation = WorkflowTriggerAllocationV1.model_validate_json(
                    outcome.payload
                )
                access = open_direct_mmap_local_buffer_access(
                    broker_settings(), root_dir=root
                )
                try:
                    with access.acquire_writer_view(allocation) as view:
                        if hold_writer:
                            Path(hold_writer).write_text(
                                "writer-acquired", encoding="utf-8"
                            )
                            while True:
                                sleep(1)
                        if isinstance(content, Path):
                            with content.open("rb") as stream:
                                offset = 0
                                while block := stream.read(4194304):
                                    view[offset : offset + len(block)] = block
                                    offset += len(block)
                                assert offset == len(view)
                        else:
                            view[:] = content
                finally:
                    access.close()
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id=source, event_id="published-cloud", payload={}
                    )
                    .model_dump_json()
                    .encode(),
                )
                response = wait_for(
                    lambda: client.read_response(identity=identity),
                    timeout=timeout_ms / 1000 + 5,
                )
            try:
                assert (response.error_code != 0) == expect_error, response
                return json.loads(response.payload)
            finally:
                client.acknowledge(identity=identity)
        except BaseException:
            # 异常路径通知服务端；已 ACK 或已过期的 identity 不再需要取消。
            from backend.service.application.errors import InvalidRequestError

            try:
                client.cancel(identity=identity)
            except InvalidRequestError:
                pass
            raise


if __name__ == "__main__":
    root, source, generation, descriptor, content, mode, timeout, *ready = sys.argv[1:]
    print(
        json.dumps(
            invoke_cloud(
                root,
                source,
                int(generation),
                CloudBufferDescriptor.model_validate_json(
                    Path(descriptor).read_text("utf-8")
                ),
                Path(content),
                timeout_ms=int(timeout),
                hold_writer=ready[0] if mode == "hold-writer" else None,
            )
        )
    )
