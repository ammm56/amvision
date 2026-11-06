"""扫描轮廓节点：显式入口复用已验证的全精度转换与行表所有权。"""

from backend.contracts.workflows.profile3d import ProfilesToCloudParameters
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.point_cloud.trigger_input import (
    require_profile_handoff,
)
from custom_nodes.metrology3d_nodes.shared.io.read_profiles import (
    read_profile_local,
    read_profile_reference,
)
from custom_nodes.metrology3d_nodes.shared.node_runtime import require_node_runtime


def profiles_to_cloud(request):
    """文件使用节点标定，同机数组仅使用本次可信载荷的标定。"""
    settings = ProfilesToCloudParameters.model_validate(request.parameters).settings
    env = require_node_runtime(request)
    env.cancel()
    file, profiles = (
        request.input_values.get("file"),
        request.input_values.get("profiles"),
    )
    if settings.kind == "file":
        if file is None or profiles is not None:
            raise InvalidRequestError("文件模式需要 file，且不能同时传入 profiles")
        cloud, counts = read_profile_reference(
            runtime=env.runtime,
            object_store=env.service.storage,
            project_id=env.project_id,
            file=file,
            spec=settings.profiles,
            has_validity=settings.has_validity,
            cancel=env.cancel,
        )
    else:
        if profiles is None or file is not None:
            raise InvalidRequestError("同机数组模式需要 profiles，且不能同时传入 file")
        payload = require_profile_handoff(request.execution_metadata, profiles)
        reader = request.runtime_context.local_buffer_reader
        if reader is None:
            raise ServiceConfigurationError("同机轮廓输入缺少 LocalBuffer reader")
        cloud, counts = read_profile_local(
            runtime=env.runtime,
            descriptor=payload.descriptor,
            expected_descriptor_sha256=payload.descriptor_sha256,
            acquire_view=lambda: reader.acquire_buffer_ref_view(payload.buffer_ref),
            cancel=env.cancel,
        )
    spec = cloud.source.profiles
    return {
        "cloud": cloud.model_dump(mode="json"),
        "summary": build_value_payload(
            dict(
                source_point_count=spec.point_count,
                profile_count=spec.profile_count,
                calibration_id=spec.calibration_id,
                calibration_revision=spec.calibration_revision,
                displacement=spec.displacement.kind,
                status_counts=dict(counts),
            )
        ),
    }
