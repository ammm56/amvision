"""随平台运行时的同机点云调用工具，复用正式 mailbox 和 LocalBuffer。"""

from collections.abc import Callable
from concurrent.futures import CancelledError
from contextlib import ExitStack
import json
import os
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

from backend.contracts.workflows import (
    WorkflowTriggerAllocationV1,
    WorkflowTriggerRequestV1,
)
from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from backend.contracts.workflows.point_cloud_trigger import (
    WorkflowTriggerCloudPrepareV1,
)
from backend.contracts.workflows.raster3d import RasterBufferDescriptor
from backend.contracts.workflows.raster_trigger import WorkflowTriggerRasterPrepareV1
from backend.contracts.workflows.profile3d import ProfileBufferDescriptor
from backend.contracts.workflows.profile_trigger import WorkflowTriggerProfilePrepareV1
from backend.service.application.errors import InvalidRequestError
from backend.service.application.local_buffers import LocalBufferBrokerSettings
from backend.service.application.local_buffers.direct_mmap_reader import (
    open_direct_mmap_local_buffer_access,
)
from backend.service.infrastructure.ipc.workflow_trigger_mailbox import (
    WorkflowTriggerMailboxClient,
)


class PointCloudCallError(RuntimeError):
    """正式协议拒绝或执行错误；保留服务端错误码及响应，不转换为测量 NG。"""

    def __init__(self, code: int, response: dict) -> None:
        """记录错误码和原始 JSON，供调用方区分忙、超时及执行失败。"""
        super().__init__(f"Point cloud call failed: {code}")
        self.code = code
        self.response = response


class PointCloudClient:
    """每次调用独立持有 mailbox/writer，立即准入，不自动排队或重试。"""

    def __init__(
        self, *, buffers_root: Path | str, broker_settings: LocalBufferBrokerSettings
    ) -> None:
        """显式使用目标服务的 mmap 根目录和布局，禁止猜测 arena 配置。"""
        self.buffers_root = Path(buffers_root)
        self.broker_settings = broker_settings

    def invoke(
        self,
        *,
        source_id: str,
        generation: int,
        cloud: CloudBufferDescriptor,
        content: bytes | bytearray | memoryview | Path,
        timeout_ms: int,
        payload_key: str = "cloud",
        payload: dict | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict:
        """提交完整紧密数组或数组文件；响应 ACK 后返回，不返回悬空共享内存。"""
        prepare = WorkflowTriggerCloudPrepareV1(
            trigger_source_id=source_id,
            event_id=uuid4().hex,
            event_payload_key=payload_key,
            cloud=CloudBufferDescriptor.model_validate(cloud.model_dump(mode="json")),
        )
        return self._invoke(
            prepare,
            cloud.content_length,
            generation,
            content,
            timeout_ms,
            payload,
            cancelled,
        )

    def invoke_raster(
        self,
        *,
        source_id: str,
        generation: int,
        raster: RasterBufferDescriptor,
        content: bytes | bytearray | memoryview | Path,
        timeout_ms: int,
        payload_key: str = "raster",
        payload: dict | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict:
        """提交完整标量及可选掩码；标定随 PREPARE 固定，不允许 REQUEST 覆盖。"""
        prepare = WorkflowTriggerRasterPrepareV1(
            trigger_source_id=source_id,
            event_id=uuid4().hex,
            event_payload_key=payload_key,
            raster=RasterBufferDescriptor.model_validate(
                raster.model_dump(mode="json")
            ),
        )
        return self._invoke(
            prepare,
            raster.content_length,
            generation,
            content,
            timeout_ms,
            payload,
            cancelled,
        )

    def invoke_profiles(
        self,
        *,
        source_id: str,
        generation: int,
        profiles: ProfileBufferDescriptor,
        content: bytes | bytearray | memoryview | Path,
        timeout_ms: int,
        payload_key: str = "profiles",
        payload: dict | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict:
        """提交完整轮廓和行表，复用固定 PREPARE 与同一次 ACK 生命周期。"""
        prepare = WorkflowTriggerProfilePrepareV1(
            trigger_source_id=source_id,
            event_id=uuid4().hex,
            event_payload_key=payload_key,
            profiles=ProfileBufferDescriptor.model_validate(
                profiles.model_dump(mode="json")
            ),
        )
        return self._invoke(
            prepare,
            prepare.profiles.content_length,
            generation,
            content,
            timeout_ms,
            payload,
            cancelled,
        )

    def _invoke(
        self,
        prepared,
        content_length,
        generation,
        content,
        timeout_ms,
        payload,
        cancelled,
    ):
        """所有数组共用同一个 writer、总时限、ACK 与取消路径。"""
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("timeout_ms 必须是正整数")
        if payload and prepared.event_payload_key in payload:
            raise ValueError("payload 不能覆盖数组绑定")
        prepare = prepared.model_dump_json().encode()
        request = (
            WorkflowTriggerRequestV1(
                trigger_source_id=prepared.trigger_source_id,
                event_id=prepared.event_id,
                payload=payload or {},
            )
            .model_dump_json()
            .encode()
        )
        deadline = monotonic() + timeout_ms / 1000

        def check() -> None:
            """同一总时限覆盖分配、写入及响应，取消不等待当前阶段结束。"""
            if cancelled is not None and cancelled():
                raise CancelledError("Point cloud call cancelled")
            if monotonic() >= deadline:
                raise TimeoutError("Point cloud call timed out")

        def wait(read):
            """只轮询当前已持有的槽位，不重发请求或等待服务端空闲。"""
            while True:
                check()
                result = read()
                if result is not None:
                    return result
                sleep(min(0.005, max(0, deadline - monotonic())))

        with ExitStack() as stack:
            if isinstance(content, Path):
                source = stack.enter_context(content.open("rb"))
                size = os.fstat(source.fileno()).st_size
            else:
                source = stack.enter_context(memoryview(content))
                if not source.c_contiguous:
                    raise ValueError("点云数组必须是 C-contiguous")
                source = stack.enter_context(source.cast("B"))
                size = source.nbytes
            if size != content_length:
                raise ValueError("点云载荷长度与 descriptor 不一致")
            check()
            with WorkflowTriggerMailboxClient(buffers_root=self.buffers_root) as client:
                claim = (
                    client.claim_profiles
                    if isinstance(prepared, WorkflowTriggerProfilePrepareV1)
                    else client.claim_raster
                    if isinstance(prepared, WorkflowTriggerRasterPrepareV1)
                    else client.claim_cloud
                )
                identity = claim(
                    timeout_ms=timeout_ms,
                    route_generation=generation,
                    prepare_payload=prepare,
                )
                acknowledged = False
                try:
                    outcome = wait(
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
                            self.broker_settings, root_dir=self.buffers_root
                        )
                        try:
                            with access.acquire_writer_view(allocation) as target:
                                if len(target) != content_length:
                                    raise ValueError("writer 容量与点云长度不一致")
                                for offset in range(0, size, 4 * 1024 * 1024):
                                    check()
                                    length = min(size - offset, 4 * 1024 * 1024)
                                    if isinstance(content, Path):
                                        block = source.read(length)
                                        if len(block) != length:
                                            raise ValueError("数组文件在提交期间截断")
                                        target[offset : offset + length] = block
                                    else:
                                        target[offset : offset + length] = source[
                                            offset : offset + length
                                        ]
                                if isinstance(content, Path) and source.read(1):
                                    raise ValueError("数组文件在提交期间增长")
                        finally:
                            access.close()
                        check()
                        client.publish_request(identity=identity, payload=request)
                        response = wait(lambda: client.read_response(identity=identity))
                    try:
                        result = json.loads(response.payload)
                        if not isinstance(result, dict):
                            raise ValueError("服务端响应必须是 JSON 对象")
                        if response.error_code:
                            raise PointCloudCallError(response.error_code, result)
                        return result
                    finally:
                        client.acknowledge(identity=identity)
                        acknowledged = True
                finally:
                    if not acknowledged:
                        try:
                            client.cancel(identity=identity)
                        except InvalidRequestError:
                            # 过期或服务端撤销后 identity 已失效，不重试或复用。
                            pass
