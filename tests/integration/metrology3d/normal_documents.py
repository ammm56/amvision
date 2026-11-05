"""法向节点的真实发布配方，复用文件入口和显示接线。"""

from backend.contracts.workflows.cloud_normals import EstimateNormalsNodeParameters
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import options
from tests.test_metrology3d_normal_estimation import parameters


def normal_documents(kind, *, settings=None):
    """参数只属于验收；不为生产节点填写物理尺度和质量默认值。"""
    template, app = cloud_documents(options().model_dump(mode="json"))
    graph = template.model_dump(mode="json")
    config = settings or parameters(kind, frame_id=options().spatial.frame_id)
    graph["nodes"].append(
        dict(
            node_id="normals",
            node_type_id="custom.metrology3d.estimate-normals",
            parameters=EstimateNormalsNodeParameters(settings=config).model_dump(
                mode="json"
            ),
        )
    )
    for edge in graph["edges"]:
        if edge["target_node_id"] == "preview" and edge["target_port"] == "cloud":
            edge["source_node_id"] = "normals"
    graph["edges"].append(
        dict(
            edge_id="normal-input",
            source_node_id="filter",
            source_port="cloud",
            target_node_id="normals",
            target_port="cloud",
        )
    )
    return WorkflowGraphTemplate.model_validate(graph), app
