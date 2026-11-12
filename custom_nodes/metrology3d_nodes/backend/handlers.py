"""M1 六节点，算法分别留在 shared 模块，不复制处理路径。"""

from backend.contracts.workflows.point_cloud_runtime import (
    NormalizeCloudUnits,
    FilterCloudValid,
)
from backend.contracts.workflows.point_cloud_preview import CloudPreviewOptions
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.parameters import (
    ReadCloudParameters,
    SaveCloudParameters,
    ExportCloudParameters,
)
from custom_nodes.metrology3d_nodes.shared.node_runtime import (
    require_node_runtime,
    cloud_input,
    write_identity,
)
from custom_nodes.metrology3d_nodes.shared.io.read_file import read_file_reference
from custom_nodes.metrology3d_nodes.shared.cloud_assets import read_asset, save_cloud
from custom_nodes.metrology3d_nodes.shared.normalize_units import normalize_units
from custom_nodes.metrology3d_nodes.shared.filter_valid import filter_valid
from custom_nodes.metrology3d_nodes.shared.preview import build_cloud_preview


def denoise(request):
    """显式去噪输出互补子集，不在读取或测量节点中偷偷改变输入。"""
    from backend.contracts.workflows.cloud_preprocess import DenoiseCloudParameters
    from custom_nodes.metrology3d_nodes.shared.denoise import denoise_cloud

    p = DenoiseCloudParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    kept, removed, summary = denoise_cloud(
        env.runtime, cloud_input(request, env.runtime), p, cancel=env.cancel
    )
    return {
        "cloud": kept.model_dump(mode="json"),
        "removed": removed.model_dump(mode="json"),
        "summary": build_value_payload(summary),
    }


def resample(request):
    """显式重采样沿现有运行输入、错误分类及结果封装执行。"""
    from backend.contracts.workflows.cloud_preprocess import ResampleCloudParameters
    from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud

    p = ResampleCloudParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    cloud, summary = resample_cloud(
        env.runtime, cloud_input(request, env.runtime), p, cancel=env.cancel
    )
    return {
        "cloud": cloud.model_dump(mode="json"),
        "summary": build_value_payload(summary),
    }


def normals(request):
    """计算法向沿同一 Runtime/取消/错误边界执行，不改变输入点和原属性。"""
    from backend.contracts.workflows.cloud_normals import EstimateNormalsNodeParameters
    from custom_nodes.metrology3d_nodes.shared.estimate_normals import estimate_normals

    p = EstimateNormalsNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    cloud, summary = estimate_normals(
        env.runtime, cloud_input(request, env.runtime), p.settings, cancel=env.cancel
    )
    return {
        "cloud": cloud.model_dump(mode="json"),
        "summary": build_value_payload(summary),
    }


def read(request):
    """文件与资产使用相同运行引用，禁止两种来源同时输入。"""
    p = ReadCloudParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    env.cancel()
    evidence = None
    document = None
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
        document = env.service.read(p.source.reference, project_id=env.project_id)
        evidence = document.content.point_cloud.boundary
    result = {"cloud": cloud.model_dump(mode="json")}
    if p.source.kind != "file":
        from custom_nodes.metrology3d_nodes.shared.height_map_assets import (
            read_height_map,
        )
        from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
            publish_height_map,
        )

        saved = read_height_map(
            env.runtime,
            cloud,
            document=document,
            service=env.service,
            project_id=env.project_id,
            policy=env.policy.assets(),
            cancel=env.cancel,
        )
        height_ref = (
            publish_height_map(env.runtime, saved) if saved is not None else None
        )
        if height_ref is not None:
            result["height_map"] = height_ref.model_dump(mode="json")
        from custom_nodes.metrology3d_nodes.shared.edge_assets import read_edge
        from custom_nodes.metrology3d_nodes.shared.edge_sampling_assets import (
            read_sampling,
        )
        from custom_nodes.metrology3d_nodes.shared.edge_reference import (
            publish_edge_diagnostic,
        )

        arguments = dict(
            document=document,
            service=env.service,
            project_id=env.project_id,
            policy=env.policy.assets(),
            cancel=env.cancel,
        )
        edge = read_edge(env.runtime, cloud, **arguments)
        sampling = read_sampling(env.runtime, cloud, **arguments)
        if edge is not None or sampling is not None:
            result["diagnostics"] = publish_edge_diagnostic(
                env.runtime,
                cloud,
                edge,
                sampling_result=sampling,
                height_map=height_ref
                if document.content.point_cloud.edge is not None
                and document.content.point_cloud.edge.method.kind == "height-jump"
                else None,
            ).model_dump(mode="json")
    # 未确认物理空间的原件只能输出 cloud，不伪造 Features3d 的单位或坐标。
    if cloud.spatial.frame_id is not None and cloud.spatial.length_unit is not None:
        from custom_nodes.metrology3d_nodes.shared.boundary_assets import (
            restore_boundary,
        )

        result["features"] = restore_boundary(cloud, evidence).model_dump(mode="json")
        if document is not None and document.content.point_cloud.edge is not None:
            parameters = document.content.point_cloud.edge.extraction
            if parameters is not None:
                from custom_nodes.metrology3d_nodes.shared.edge_extraction import (
                    edge_features,
                )

                result["features"] = edge_features(
                    env.runtime,
                    cloud,
                    parameters,
                    edge,
                    height_map=height_ref
                    if parameters.method.kind == "height-jump"
                    else None,
                    cancel=env.cancel,
                ).model_dump(mode="json")
    return result


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
    from custom_nodes.metrology3d_nodes.shared.geometry_preview import attach_geometry
    from custom_nodes.metrology3d_nodes.shared.boundary_debug import (
        attach_debug,
        preview_base_policy,
    )
    from custom_nodes.metrology3d_nodes.shared.measurement_preview import (
        attach_measurements,
    )

    cloud = cloud_input(request, env.runtime)
    detail = None
    if p.prepare_details:
        from backend.service.application.workflows.point_cloud.detail_index import (
            prepare_index,
        )

        detail = prepare_index(
            env.runtime,
            cloud,
            service=env.service,
            project_id=env.project_id,
            policy=env.policy,
            cancel=env.cancel,
        )
    base_policy = preview_base_policy(
        env.runtime, request.input_values, env.policy.preview, cancel=env.cancel
    )
    from custom_nodes.metrology3d_nodes.shared.edge_preview import (
        edge_base_policy,
        attach_edge_diagnostic,
    )

    diagnostic_policy = base_policy
    base_policy = edge_base_policy(
        env.runtime, cloud, request.input_values.get("diagnostics"), base_policy
    )
    from custom_nodes.metrology3d_nodes.shared.height_map_preview import (
        attach_height_map,
        height_map_base_policy,
    )

    cloud_policy = height_map_base_policy(
        env.runtime, cloud, request.input_values.get("height_map"), base_policy
    )
    body = attach_measurements(
        cloud,
        attach_geometry(
            env.runtime,
            cloud,
            build_cloud_preview(
                env.runtime,
                cloud,
                p,
                policy=cloud_policy,
                cancel=env.cancel,
            ),
            request.input_values,
            policy=cloud_policy,
            cancel=env.cancel,
        ),
        request.input_values,
        policy=cloud_policy,
        cancel=env.cancel,
    )
    if detail is not None:
        body["asset_details"] = {"source": detail.source.model_dump(mode="json")}
    body = attach_height_map(
        env.runtime,
        cloud,
        body,
        request.input_values.get("height_map"),
        policy=base_policy,
        cancel=env.cancel,
    )
    body = attach_edge_diagnostic(
        env.runtime,
        cloud,
        body,
        request.input_values.get("diagnostics"),
        policy=diagnostic_policy,
        cancel=env.cancel,
    )
    return {
        "body": attach_debug(
            env.runtime,
            cloud,
            body,
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
    from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
        resolve_height_map,
    )

    value = request.input_values.get("height_map")
    height_map = (
        resolve_height_map(env.runtime, value, cloud=cloud)
        if value is not None
        else None
    )
    from custom_nodes.metrology3d_nodes.shared.edge_reference import (
        resolve_edge_diagnostic,
    )

    edge = sampling = None
    diagnostic_value = request.input_values.get("diagnostics")
    if diagnostic_value is not None:
        ref, edge, sampling = resolve_edge_diagnostic(
            env.runtime, diagnostic_value, cloud=cloud
        )
        if ref.height_map is not None:
            if value is not None and ref.height_map.model_dump(mode="json") != value:
                raise InvalidRequestError("保存输入的高度图与边诊断不属于同次计算")
            height_map = resolve_height_map(env.runtime, ref.height_map, cloud=cloud)
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
        features=request.input_values.get("features"),
        height_map=height_map,
        edge=edge,
        sampling=sampling,
    )
    return {"resource": reference.model_dump(mode="json")}


def export(request):
    """临时编码流关闭后才发布不可变文件引用。"""
    from custom_nodes.metrology3d_nodes.shared.export_output import publish_export

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
