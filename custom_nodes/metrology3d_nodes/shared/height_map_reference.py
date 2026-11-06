"""复用当前 ResourceScope 登记结果；不创建跨运行缓存或独立资源服务。"""

from uuid import uuid4

from backend.contracts.workflows.height_map_reference import HeightMapReference
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.height_map_assets import result_evidence


def publish_height_map(runtime, result):
    """引用快照和实际结果同批登记，数组仍由原有 owner 负责释放。"""
    cloud = CloudReference.model_validate_json(result.input_json)
    with runtime.producing():
        ref = HeightMapReference(
            run_id=runtime.run_id,
            height_map_id=uuid4().hex,
            cloud=cloud,
            evidence=result_evidence(result, cloud) if result.reason is None else None,
            reason=result.reason,
        )
        runtime.storage_scope.register(
            ("height-map-result", ref.height_map_id),
            (ref.model_dump_json(), result),
            lambda value: None,
        )
        return ref


def resolve_height_map(runtime, value, *, cloud=None):
    """只能解析同一 Scope 中的原快照，未知 ID 不创建资源。"""
    ref = HeightMapReference.model_validate(value)
    if ref.run_id != runtime.run_id or (cloud is not None and ref.cloud != cloud):
        raise InvalidRequestError("高度图不属于当前运行或点云")

    def missing():
        raise InvalidRequestError("高度图引用失效")

    with runtime.producing():
        encoded, result = runtime.storage_scope.get_or_create(
            ("height-map-result", ref.height_map_id), missing, lambda value: None
        )
        if encoded != ref.model_dump_json():
            raise InvalidRequestError("高度图引用内容被修改")
        if ref.evidence is not None:
            with result.borrow(runtime):
                pass
        return result
