"""R4 复用正式发布/Trigger 生命周期，以完整工件输入检查有限基准延伸。"""

import json

import pytest

from backend.contracts.workflows.geometry3d import FitPlaneParameters
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.test_measurement_nodes import measurement_graph
from tests.integration.metrology3d.test_published_runtime import (
    published_full_sample_lifecycle,
)
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import spatial, options
from tests.test_metrology3d_measurement_contracts import (
    height_parameters,
    measurement_policy,
)
from tests.test_metrology3d_plane import plane_parameters


def sample_height_parameters():
    """显式测试配方：手工报告 A_top_L 中心；门槛沿用完整样本局部面测试。"""
    fit = plane_parameters(feature_id="target").model_dump(mode="json")
    for rule in fit["quality_policy"]["rules"]:
        if rule["item_id"] == "rms":
            rule["upper"] = 0.05
        if rule["item_id"] == "max_residual":
            rule["upper"] = 0.1
    return height_parameters(
        query=dict(
            kind="configured",
            query_position=(-33.0880012936612, -18.59026520051255, -15),
            direction=(0, 0, 1),
        ),
        search_radius=0.3,
        search_interval=(-1, 1),
        support_radius=0.3,
        reference_policy=dict(kind="plane-extension", max_extension_distance=10),
        plane_fit=FitPlaneParameters.model_validate(fit),
        quality_policy=measurement_policy(
            reference_nearest_distance={"upper": 0.1},
            target_nearest_distance={"upper": 0.1},
            reference_triangle_edge={"upper": 0.15},
            target_triangle_edge={"upper": 0.15},
            reference_max_residual={"upper": 0.1},
            target_max_residual={"upper": 0.1},
        ),
    )


def extension_documents(*, file=False):
    """只组合既有节点和发布文档，不替代 Catalog 或运行准入。"""
    height = sample_height_parameters()
    # 手工报告大窗口包含离群点；本测试单独评价其中心的局部基准。
    # 不修改原拟合器或 0.05/0.1 mm 门槛，不等同手工报告的全窗测量。
    roi = dict(
        roi_id="body-reference",
        kind="box",
        frame_id="fixture",
        length_unit="mm",
        geometry=dict(
            center=[-29, -26.5, -16],
            size=[2, 1, 2],
            rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        ),
    )
    measurement = measurement_graph(
        height=height, reference_roi=roi, read=False
    ).model_dump(mode="json")
    template, app = cloud_documents(options().model_dump(mode="json") if file else None)
    graph = template.model_dump(mode="json")
    graph["nodes"].extend(n for n in measurement["nodes"] if n["node_id"] != "preview")
    graph["edges"].extend(measurement["edges"])
    for name in ("reference", "height"):
        graph["edges"].append(
            dict(
                edge_id=f"filter-{name}",
                source_node_id="filter",
                source_port="cloud",
                target_node_id=name,
                target_port="cloud",
            )
        )
    return WorkflowGraphTemplate.model_validate(graph), app


def check_extension_body(body):
    """持久显示重读须与节点证据一致；相同拟面应给出相同量值。"""
    evidence = MeasurementEvidence3d.model_validate(body["measurements"])
    assert len(evidence.items) == 2
    for item in evidence.items:
        assert item.valid, item.model_dump_json()
        assert item.support[0].extension.state == "used"
        assert 6 < item.support[0].extension.distance < 10
        assert item.support[1].coverage.covered
        assert item.support[1].extension is None
        assert item.support[0].source_point_count == 14745099
    assert evidence.items[0].value == pytest.approx(evidence.items[1].value, abs=1e-10)
    # 此处核对节点自一致性，不将不同拟合窗口的人工报告当作标定真值。
    print(
        json.dumps(
            {"measurements": [i.model_dump(mode="json") for i in evidence.items]}
        ),
        flush=True,
    )


def test_reference_extension_complete_published_lifecycle(tmp_path, request):
    """完整原文件解析后通过同机完整数组，覆盖正式发布、切版、停止和回收。"""
    published_full_sample_lifecycle(
        tmp_path,
        request,
        prepare=lambda cloud, path: (
            cloud.model_copy(update={"spatial": spatial()}),
            extension_documents(),
        ),
        check_body=check_extension_body,
        report_name="r4-",
    )
