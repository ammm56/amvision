"""M1 六节点，算法分别留在 shared 模块，不复制处理路径。"""

from backend.contracts.workflows.point_cloud_runtime import (
    NormalizeCloudUnits,
    FilterCloudValid,
)
from backend.contracts.workflows.point_cloud_preview import CloudPreviewOptions
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.parameters import (
    ReadCloudParameters,
    SaveCloudParameters,
    ExportCloudParameters,
)
from custom_nodes._metrology3d_nodes.shared.node_runtime import (
    require_node_runtime,
    cloud_input,
    write_identity,
)
from custom_nodes._metrology3d_nodes.shared.io.read_file import read_file_reference
from custom_nodes._metrology3d_nodes.shared.cloud_assets import read_asset, save_cloud
from custom_nodes._metrology3d_nodes.shared.normalize_units import normalize_units
from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid
from custom_nodes._metrology3d_nodes.shared.preview import build_cloud_preview


def read(request):
    """文件与资产使用相同运行引用，禁止两种来源同时输入。"""
    p = ReadCloudParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    env.cancel()
    if p.source.kind == "file":
        cloud = read_file_reference(
            runtime=env.runtime,
            object_store=env.service.storage,
            project_id=env.project_id,
            file=request.input_values.get("file"),
            options=p.file_options,
            cancel=env.cancel,
        )
    else:
        if request.input_values.get("file") is not None:
            raise InvalidRequestError("资产来源不能同时传入 file")
        cloud = read_asset(
            env.runtime,
            p.source.reference,
            service=env.service,
            project_id=env.project_id,
            policy=env.policy.assets(),
            cancel=env.cancel,
        )
    return {"cloud": cloud.model_dump(mode="json")}


def normalize(request):
    """沿既有全精度单位算法处理，并透传不可用原因。"""
    p = NormalizeCloudUnits.model_validate(request.parameters)
    env = require_node_runtime(request)
    cloud = normalize_units(
        env.runtime, cloud_input(request, env.runtime), p, cancel=env.cancel
    )
    return {"cloud": cloud.model_dump(mode="json")}


def filter_points(request):
    """有效点过滤保留原始行号，摘要仍为 value.v1。"""
    p = FilterCloudValid.model_validate(request.parameters)
    env = require_node_runtime(request)
    cloud, summary = filter_valid(
        env.runtime, cloud_input(request, env.runtime), p, cancel=env.cancel
    )
    return {
        "cloud": cloud.model_dump(mode="json"),
        "summary": build_value_payload(summary),
    }


def preview(request):
    """生成独立显示正文，现有观察层负责显示交接。"""
    p = CloudPreviewOptions.model_validate(request.parameters)
    env = require_node_runtime(request)
    from custom_nodes._metrology3d_nodes.shared.geometry_preview import attach_geometry

    cloud = cloud_input(request, env.runtime)
    return {
        "body": attach_geometry(
            env.runtime,
            cloud,
            build_cloud_preview(
                env.runtime,
                cloud,
                p,
                policy=env.policy.preview,
                cancel=env.cancel,
            ),
            request.input_values,
            policy=env.policy.preview,
            cancel=env.cancel,
        )
    }


def save(request):
    """只有成功提交的不可变资源身份能出现在输出端口。"""
    p = SaveCloudParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    cloud = cloud_input(request, env.runtime)
    if cloud.state != "ready":
        raise InvalidRequestError("不可用点云不能保存")
    reference = save_cloud(
        env.runtime,
        cloud,
        service=env.service,
        project_id=env.project_id,
        mode=p.mode,
        name=p.target.name,
        write_identity=write_identity(request, env.project_id),
        expected_base=p.target.reference if p.target.kind == "new-version" else None,
        policy=env.policy.assets(),
        cancel=env.cancel,
    )
    return {"resource": reference.model_dump(mode="json")}


def export(request):
    """临时编码流关闭后才发布不可变文件引用。"""
    from custom_nodes._metrology3d_nodes.shared.export_output import publish_export

    p = ExportCloudParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    if p.source.kind == "asset":
        if request.input_values.get("cloud") is not None:
            raise InvalidRequestError("资产来源不能同时传入 cloud")
        cloud = read_asset(
            env.runtime,
            p.source.reference,
            service=env.service,
            project_id=env.project_id,
            policy=env.policy.assets(),
            cancel=env.cancel,
        )
    else:
        cloud = cloud_input(request, env.runtime)
    if cloud.state != "ready":
        raise InvalidRequestError("不可用点云不能导出")
    return publish_export(request, env, cloud, p)
