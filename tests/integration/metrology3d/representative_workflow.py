"""R5 代表配方的正式图配置；完整输入与显式测试容量，不包含替代 handler。"""

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.representative_recipe import (
    supports,
    plane,
    frame,
    step,
    contour,
    circle,
    hole,
)
from tests.integration.metrology3d.test_transport_full_sample import full_policy
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import options
from tests.test_metrology3d_dimension_contracts import extent_parameters


def representative_policy():
    """复用 D2 的 4 GiB 工作容量；显示预算只适用于隔离测试。"""
    original = full_policy()
    return type(original).model_validate(
        {
            **original.model_dump(),
            "io": {
                **original.io.model_dump(),
                "max_working_bytes": 4 * 1024**3,
                "max_live_array_bytes": 1024**3,
            },
            "preview": {
                **original.preview.model_dump(),
                "max_points": 1000000,
                "max_data_bytes": 32 * 1024**2,
                "max_body_bytes": 64 * 1024**2,
                "max_working_bytes": 128 * 1024**2,
            },
            "renderer": {
                **original.renderer.model_dump(),
                "max_points": 1000000,
                "max_data_bytes": 32 * 1024**2,
                "max_cpu_bytes": 128 * 1024**2,
                "max_gpu_bytes": 64 * 1024**2,
            },
        }
    )


def representative_documents(*, file=False):
    """同一图同时保留有效量与合法无效量，不使用报告值或旧运行特征。"""
    template, app = cloud_documents(options().model_dump(mode="json") if file else None)
    graph = template.model_dump(mode="json")
    graph["display_name"] = "R5 representative measurements"

    def node(name, kind, settings=None, **parameters):
        if settings is not None:
            parameters["settings"] = settings.model_dump(mode="json")
        graph["nodes"].append(
            dict(
                node_id=name,
                node_type_id="custom.metrology3d." + kind,
                parameters=parameters,
            )
        )

    def link(a, port, b, target):
        graph["edges"].append(
            dict(
                edge_id=f"r5-{len(graph['edges'])}",
                source_node_id=a,
                source_port=port,
                target_node_id=b,
                target_port=target,
            )
        )

    for name, region in supports().items():
        rois = {r.roi_id: r.model_dump(mode="json") for r in region.rois}
        node(
            name + "-crop",
            "crop-roi",
            source=dict(
                kind="parameters",
                roi=rois.pop(region.roi_id),
                bounds=list(rois.values()),
            ),
        )
        node(name, "fit-plane", plane(name))
        link("filter", "cloud", name + "-crop", "cloud")
        link(name + "-crop", "cloud", name, "cloud")
        link(name, "features", "preview", "features")
    node("frame", "build-frame", frame())
    link("D", "features", "frame", "features")
    for item, reference in (("H", "B"), ("Z", "D")):
        node(item, "measure-step", step(item, reference))
        for feature in (reference, "T"):
            link(feature, "features", item, "features")
        link("frame", "pose", item, "pose")
        link(item, "evidence", "preview", "evidence")
    for item in ("A_top_L", "S1"):
        node(item, "extract-boundary", contour(item))
        link("filter", "cloud", item, "cloud")
        link("frame", "pose", item, "pose")
        for feature in ("D", "B", "T") if item == "A_top_L" else ("D",):
            link(feature, "features", item, "features")
        link(item, "features", "preview", "features")
    link("H", "evidence", "A_top_L", "evidence")
    node(
        "extents",
        "measure-extents",
        extent_parameters(
            evaluation=dict(kind="feature", frame_id="fixture", length_unit="mm"),
            source=dict(
                kind="boundary",
                selection=dict(feature_id="A_top_L-boundary", segment_ids=["A_top_L"]),
            ),
            outputs=[
                dict(component="u", item_id="W"),
                dict(component="v", item_id="L"),
            ],
        ),
    )
    link("A_top_L", "features", "extents", "features")
    node("circle", "fit-circle", circle())
    link("S1", "features", "circle", "features")
    node("diameter", "measure-hole", hole())
    link("circle", "features", "diameter", "features")
    link("circle", "features", "preview", "features")
    for name in ("extents", "diameter"):
        link(name, "evidence", "preview", "evidence")
    return WorkflowGraphTemplate.model_validate(graph), app


def check_representative_body(body):
    """在实际返回体上检查身份、量值和缺测；不把 null 当零或旧值。"""
    import pytest

    assert body["source_point_count"] == 14745099
    assert body["measurements"]["length_unit"] == "mm"
    items = {item["item_id"]: item for item in body["measurements"]["items"]}
    assert set(items) == {"H", "Z", "W", "L", "S1.D"}
    for key, value in (
        ("H", 1.128335845558628),
        ("Z", 1.5776995404900624),
        ("S1.D", 20.14782366565865),
    ):
        assert items[key]["valid"]
        assert items[key]["value"] == pytest.approx(value, abs=1e-7)
    for key in ("W", "L"):
        assert not items[key]["valid"] and items[key]["value"] is None
        assert items[key]["reason"] == "target_not_found"
    assert body["measurements"]["observation_id"] == body["observation_id"]
