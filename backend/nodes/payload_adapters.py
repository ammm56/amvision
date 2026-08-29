"""Workflow payload contract 间的显式转换注册表。"""

from __future__ import annotations

from collections.abc import Callable

from backend.nodes.core_nodes.support.logic import (
    require_boolean_payload,
    require_value_payload,
)
from backend.nodes.core_nodes.support.roi import (
    require_roi_list_payload,
    require_roi_payload,
)
from backend.nodes.core_nodes.support.typed_payload_bridges import (
    require_image_refs_payload,
)
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)


PayloadAdapter = Callable[[object, WorkflowNodeExecutionRequest], object]


class PayloadAdapterRegistry:
    """维护唯一 `(source_contract, target_contract)` 转换函数。"""

    def __init__(self) -> None:
        """初始化空 registry。"""

        self._adapters: dict[tuple[str, str], PayloadAdapter] = {}

    def register(
        self,
        source_contract: str,
        target_contract: str,
        adapter: PayloadAdapter,
    ) -> None:
        """登记显式转换，并拒绝重复键。"""

        key = (_normalize_contract(source_contract), _normalize_contract(target_contract))
        if key in self._adapters:
            raise ServiceConfigurationError(
                "Payload Adapter 重复注册",
                details={
                    "source_contract": key[0],
                    "target_contract": key[1],
                },
            )
        self._adapters[key] = adapter

    def resolve(
        self,
        source_contract: str,
        target_contract: str,
    ) -> PayloadAdapter:
        """返回显式转换函数；禁止链式猜测。"""

        key = (_normalize_contract(source_contract), _normalize_contract(target_contract))
        adapter = self._adapters.get(key)
        if adapter is None:
            raise InvalidRequestError(
                "未注册所需 Payload Adapter",
                details={
                    "source_contract": key[0],
                    "target_contract": key[1],
                },
            )
        return adapter

    def convert(
        self,
        source_contract: str,
        target_contract: str,
        payload: object,
        *,
        request: WorkflowNodeExecutionRequest,
    ) -> object:
        """执行一次显式 payload 转换。"""

        return self.resolve(source_contract, target_contract)(payload, request)

    def list_contract_pairs(self) -> tuple[tuple[str, str], ...]:
        """稳定返回全部已登记转换键。"""

        return tuple(sorted(self._adapters))


def _normalize_contract(value: str) -> str:
    """规范化并校验 contract id。"""

    normalized = value.strip()
    if not normalized:
        raise ValueError("payload contract id 不能为空")
    return normalized


def _convert_value(payload: object, request: WorkflowNodeExecutionRequest) -> object:
    """解包 value.v1。"""

    return require_value_payload(payload, field_name="value")["value"]


def _convert_boolean(payload: object, request: WorkflowNodeExecutionRequest) -> object:
    """解包 boolean.v1。"""

    return require_boolean_payload(payload, field_name="boolean")["value"]


def _convert_roi(payload: object, request: WorkflowNodeExecutionRequest) -> object:
    """校验并返回 roi.v1。"""

    return require_roi_payload(payload, node_id=request.node_id)


def _convert_roi_list(payload: object, request: WorkflowNodeExecutionRequest) -> object:
    """校验 roi-list.v1 并返回 items。"""

    return require_roi_list_payload(payload, node_id=request.node_id)["items"]


def _convert_object(payload: object, request: WorkflowNodeExecutionRequest) -> object:
    """复制结构化对象 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            "Payload Adapter 要求结构化输入必须是对象",
            details={"node_id": request.node_id},
        )
    return dict(payload)


def _convert_image_ref(payload: object, request: WorkflowNodeExecutionRequest) -> object:
    """校验并复制 image-ref.v1。"""

    del request
    return require_image_payload(payload)


def _convert_image_refs(payload: object, request: WorkflowNodeExecutionRequest) -> object:
    """校验并复制 image-refs.v1。"""

    return require_image_refs_payload(payload, request.node_id)


def _build_default_registry() -> PayloadAdapterRegistry:
    """创建平台内建的结构化 payload 到 value.v1 转换表。"""

    registry = PayloadAdapterRegistry()
    registry.register("value.v1", "value.v1", _convert_value)
    registry.register("boolean.v1", "value.v1", _convert_boolean)
    registry.register("roi.v1", "value.v1", _convert_roi)
    registry.register("roi-list.v1", "value.v1", _convert_roi_list)
    registry.register("image-ref.v1", "value.v1", _convert_image_ref)
    registry.register("image-refs.v1", "value.v1", _convert_image_refs)
    object_contracts = (
        "result-record.v1",
        "response-body.v1",
        "prompt-regions.v1",
        "detections.v1",
        "segments.v1",
        "categories.v1",
        "poses.v1",
        "obbs.v1",
        "video-ref.v1",
        "frame-window.v1",
        "tracks.v1",
        "regions.v1",
        "contours.v1",
        "measurements.v1",
        "rotated-rects.v1",
        "lines.v1",
        "circles.v1",
        "ellipses.v1",
        "local-features.v1",
        "feature-matches.v1",
        "planar-transform.v1",
    )
    for source_contract in object_contracts:
        registry.register(source_contract, "value.v1", _convert_object)
    return registry


PAYLOAD_ADAPTER_REGISTRY = _build_default_registry()


__all__ = ["PAYLOAD_ADAPTER_REGISTRY", "PayloadAdapterRegistry"]
