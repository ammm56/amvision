"""重采样页面和真实发布共用配方，不绕过 Catalog 或发布准入。"""

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.contracts.workflows.cloud_preprocess import ResampleCloudParameters
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import options


def resample_documents(kind, *, file=True):
    """仅测试配方的显式格距/精度；不修改完整工件正式图。"""
    template, app = cloud_documents(options().model_dump(mode="json") if file else None)
    graph = template.model_dump(mode="json")
    p = ResampleCloudParameters(
        settings=(
            dict(kind=kind, every_k_points=3, offset=1)
            if kind == "stride"
            else dict(
                kind=kind,
                voxel_size=1.0,
                grid_origin=(0.0, 0.0, 0.0),
                frame_id=options().spatial.frame_id if file else "sample-source",
                length_unit="mm",
                **(
                    dict(max_position_error=0.0001, attributes="positions-only")
                    if kind == "voxel-centroid"
                    else {}
                ),
            )
        )
    )
    graph["nodes"].append(
        dict(
            node_id="resample",
            node_type_id="custom.metrology3d.resample-cloud",
            parameters=p.model_dump(mode="json"),
        )
    )
    for edge in graph["edges"]:
        if edge["target_node_id"] == "preview" and edge["target_port"] == "cloud":
            edge["source_node_id"] = "resample"
    graph["edges"].append(
        dict(
            edge_id="resample-input",
            source_node_id="filter",
            source_port="cloud",
            target_node_id="resample",
            target_port="cloud",
        )
    )
    return WorkflowGraphTemplate.model_validate(graph), app
