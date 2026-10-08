"""真实节点/执行器使用开发资源，区分定位真值注入与实际定位验证。"""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.nodes import ExecutionImageRegistry
from backend.nodes.runtime_support import register_image_matrix
from backend.nodes.core_nodes.logic.rules.check_limits import CORE_NODE_SPEC as LIMITS
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRequest,
    WorkflowNodeRuntimeRegistry,
)
from custom_nodes.connector_nodes.categories.array.backend.nodes.pin_array_locate import (
    handle_node as locate,
)
from custom_nodes.connector_nodes.categories.measurement.backend.nodes.measure import (
    handle_node as measure,
)
from custom_nodes.connector_nodes.shared.runtime import image_identity
from custom_nodes.connector_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_document,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.rigid_locate import (
    handle_node as rigid_locate,
)

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "data/development/connector-inspection/synthetic-v1"


def request(registry, parameters=None, inputs=None):
    """共享同次调用 ID 和图像注册表。"""
    return WorkflowNodeExecutionRequest(
        node_id="connector-test",
        node_definition=object(),
        parameters=parameters or {},
        input_values=inputs or {},
        execution_metadata={
            "execution_image_registry": registry,
            "workflow_run_id": "connector-test-run",
        },
    )


def source(family, condition="reference"):
    """配方只取参考图名义位置；被测图使用独立的缺陷/扰动图片。"""
    if not ASSETS.exists():
        pytest.skip("开发资源尚未生成")
    reference = json.loads(
        (ASSETS / "truth" / f"{family}__reference.json").read_text(encoding="utf-8")
    )
    actual = json.loads(
        (ASSETS / "truth" / f"{family}__{condition}.json").read_text(encoding="utf-8")
    )
    image = cv2.imdecode(
        np.fromfile(ASSETS / "images" / f"{family}__{condition}.png", np.uint8),
        cv2.IMREAD_COLOR,
    )
    layout = dict(
        reference_id=family,
        pins=[
            dict(
                pin_id=p["pin_id"],
                row_id=p["pin_id"].split("P")[0],
                pin_type="normal",
                center=p["nominal_center_image_px"],
            )
            for p in reference["pins"]
        ],
        types=[
            dict(
                type_id="normal",
                gradient_threshold=0.03,
                min_width=12.0,
                max_width=35.0,
            )
        ],
    )
    return image, layout, reference, actual


def dimensions(layout):
    """显式生成宽度、间距和偏移项，范围及单位不由算法猜测。"""
    pins = layout["pins"]
    return [
        dict(
            item_id="width:" + p["pin_id"],
            kind="width",
            pin_a=p["pin_id"],
            section=p["center"][1],
        )
        for p in pins
    ] + [
        dict(
            item_id="pitch",
            kind="pitch",
            pin_a=pins[0]["pin_id"],
            pin_b=pins[1]["pin_id"],
        ),
        dict(item_id="offset", kind="offset", pin_a=pins[4]["pin_id"]),
    ]


def test_diagnostics_use_preview_only_and_keep_original_observations():
    """同一配方在 Runtime 不生成剖面或图片；Preview 借用原图显示，关闭无残留。"""
    image, layout, _, _ = source("single10_front")
    layout["diagnostic_pin_id"] = layout["pins"][0]["pin_id"]
    images = ExecutionImageRegistry()
    payload = register_image_matrix(request(images), image_matrix=image)
    parameters = dict(layout=layout, pose_mode="fixed", debug_image_panel_enabled=True)
    production = locate(request(images, parameters, {"image": payload}))
    assert "debug_preview" not in production
    preview_request = request(images, parameters, {"image": payload})
    captured = []

    def sink(_request, **kwargs):
        captured.append(kwargs)
        return {
            "transport_kind": "preview-memory",
            "width": image.shape[1],
            "height": image.shape[0],
        }

    preview_request.execution_metadata.update(
        debug_image_panels_enabled=True, _editor_preview_image_sink=sink
    )
    inspected = locate(preview_request)
    assert inspected["pins"]["pins"] == production["pins"]["pins"]
    diagnostic = inspected["debug_preview"]["sampling_diagnostic"]
    assert diagnostic["pin_id"] == layout["diagnostic_pin_id"]
    assert diagnostic["image"]["run_id"] == "connector-test-run"
    assert 1 < len(diagnostic["distance_px"]) <= 1024
    assert diagnostic["state"] == "found"
    assert (
        len(captured) == 1
        and captured[0]["image_payload"]["image_handle"] == payload["image_handle"]
    )
    assert captured[0]["save_location"] is None
    parameters["debug_image_panel_enabled"] = False
    assert "debug_preview" not in locate(preview_request)


@pytest.mark.parametrize("family", ["single10_front", "dual08_top"])
@pytest.mark.parametrize(
    "condition",
    [
        "reference",
        "missing_first",
        "missing_middle",
        "missing_last",
        "no_part",
        "dark",
        "bright",
        "narrow",
        "wide",
        "offset",
        "designed_empty",
        "empty_occupied",
    ],
)
def test_prepared_images_keep_ids_and_measure_observed_geometry(family, condition):
    """读取实际图像，无工件/缺针无有效宽度，不用总数补齐缺失项。"""
    image, layout, reference, actual = source(family, condition)
    if condition in {"designed_empty", "empty_occupied"}:
        layout["pins"][4]["expected_present"] = False
    registry = ExecutionImageRegistry()
    payload = register_image_matrix(request(registry), image_matrix=image)
    output = locate(
        request(registry, dict(layout=layout, pose_mode="fixed"), {"image": payload})
    )
    assert [p["pin_id"] for p in output["pins"]["pins"]] == [
        p["pin_id"] for p in layout["pins"]
    ]
    measured = measure(
        request(
            registry,
            {"items": dimensions(layout)},
            {"pins": output["pins"], "features": output["features"]},
        )
    )
    widths = measured["measurements"]["items"][: len(layout["pins"])]
    for index, pin in enumerate(actual["pins"]):
        if condition == "no_part" or not pin["actual_present"]:
            assert output["pins"]["pins"][index]["state"] != "found"
            assert widths[index]["value"] is None and widths[index]["valid"] is False
        else:
            assert output["pins"]["pins"][index]["state"] == "found", (
                condition,
                pin["pin_id"],
                output["pins"]["pins"][index],
            )
            assert (
                abs(
                    widths[index]["value"]
                    - pin["width_mm"] * reference["camera"]["pixels_per_mm"]
                )
                < 0.7
            )
    if condition in {"designed_empty", "empty_occupied"}:
        assert output["checks"]["items"][4]["value"] == (
            1.0 if condition == "designed_empty" else 0.0
        )


def test_mixed_frame_and_unobserved_length_rejected():
    """错误连线是错误，不伪装成正常缺陷；没有针尖证据不输出长度。"""
    image, layout, _, _ = source("single10_front")
    registry = ExecutionImageRegistry()
    payload = register_image_matrix(request(registry), image_matrix=image)
    output = locate(
        request(registry, dict(layout=layout, pose_mode="fixed"), {"image": payload})
    )
    wrong = output["features"] | {"observation_id": "other-frame"}
    with pytest.raises(InvalidRequestError):
        measure(
            request(
                registry,
                {"items": dimensions(layout)},
                {"pins": output["pins"], "features": wrong},
            )
        )
    result = measure(
        request(
            registry,
            {
                "items": [
                    dict(
                        item_id="length",
                        kind="length",
                        pin_a="R1P01",
                        pin_b="R1P01",
                        feature_a="R1P01:tip",
                        feature_b="R1P01:root",
                    )
                ]
            },
            {"pins": output["pins"], "features": output["features"]},
        )
    )
    assert result["measurements"]["items"][0]["reason"] == "endpoint_not_observed"
    assert result["measurements"]["items"][0]["value"] is None


def test_failed_pose_does_not_scan_or_reuse_geometry():
    """失败定位产生本次无效观测，不能回退到单位阵进行检测。"""
    image, layout, _, _ = source("single10_front")
    registry = ExecutionImageRegistry()
    payload = register_image_matrix(request(registry), image_matrix=image)
    pose = dict(
        image=image_identity(request(registry), payload, image).model_dump(mode="json"),
        reference_id=layout["reference_id"],
        state="ambiguous",
        reason="multiple_objects",
        image_from_reference=None,
    )
    output = locate(
        request(registry, dict(layout=layout), {"image": payload, "pose": pose})
    )
    assert not output["features"]["features"]
    assert all(not item["valid"] for item in output["checks"]["items"])


def build_chain():
    """构造真实注册表和 PIN→尺寸→规则的隔离测试模板。"""
    image, layout, reference, _ = source("single10_front")
    catalog = build_custom_node_catalog_document()
    manifest = NodePackManifest.model_validate_json(
        (ROOT / "custom_nodes/connector_nodes/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest.dependencies[0].node_pack_id == "opencv.nodes"
    registry = WorkflowNodeRuntimeRegistry()
    for definition, handler in zip(catalog.node_definitions, (locate, measure)):
        registry.register_python_callable(definition, handler)
    LIMITS.register_handler(registry)
    template = WorkflowGraphTemplate.model_validate(
        {
            "template_id": "connector-engineering",
            "template_version": "0.1.8",
            "display_name": "Connector Engineering",
            "nodes": [
                dict(
                    node_id="pins",
                    node_type_id="custom.connector.pin-array-locate",
                    parameters=dict(layout=layout, pose_mode="fixed"),
                ),
                dict(
                    node_id="measure",
                    node_type_id="custom.connector.measure",
                    parameters={"items": dimensions(layout)},
                ),
                dict(
                    node_id="limits",
                    node_type_id="core.rule.check-limits",
                    parameters={
                        "rules": [
                            dict(
                                item_id="width:R1P01",
                                unit="pixel",
                                lower=0.59 * reference["camera"]["pixels_per_mm"],
                                upper=0.69 * reference["camera"]["pixels_per_mm"],
                            )
                        ]
                    },
                ),
            ],
            "edges": [
                dict(
                    edge_id=p,
                    source_node_id="pins",
                    source_port=p,
                    target_node_id="measure",
                    target_port=p,
                )
                for p in ("pins", "features")
            ]
            + [
                dict(
                    edge_id="measurements",
                    source_node_id="measure",
                    source_port="measurements",
                    target_node_id="limits",
                    target_port="table",
                )
            ],
            "template_inputs": [
                dict(
                    input_id="image",
                    display_name="Image",
                    payload_type_id="image-ref.v1",
                    target_node_id="pins",
                    target_port="image",
                )
            ],
            "template_outputs": [
                dict(
                    output_id="result",
                    display_name="Result",
                    payload_type_id="value.v1",
                    source_node_id="limits",
                    source_port="summary",
                )
            ],
        }
    )
    return image, registry, template


def test_actual_executor_chain_and_pack_manifest():
    """真实注册表执行 PIN→尺寸→规则，不改 Runtime/Trigger 执行器。"""
    image, registry, template = build_chain()
    images = ExecutionImageRegistry()
    payload = register_image_matrix(request(images), image_matrix=image)
    result = WorkflowGraphExecutor(registry=registry).execute(
        template=template,
        input_values={"image": payload},
        execution_metadata={
            "execution_image_registry": images,
            "workflow_run_id": "connector-test-run",
        },
    )
    assert result.outputs["result"]["value"]["passed"] is True


@pytest.mark.parametrize("physical", [False, True])
def test_preview_memory_and_runtime_snapshot_same_result(tmp_path, physical):
    """真实 Preview/Snapshot 服务同图同结果，不创建生产数据或临时预览图片。"""
    from types import SimpleNamespace
    from backend.contracts.workflows.workflow_graph import (
        FlowApplication,
        WorkflowPayloadContract,
    )
    from backend.nodes.node_catalog_registry import NodeCatalogRegistry
    from backend.nodes.node_pack_loader import NodeCatalogSnapshot
    from backend.service.application.workflows.preview.execution import (
        PreviewMemoryExecutionRequest,
        PreviewMemoryExecutionService,
    )
    from backend.service.application.workflows.snapshot_execution import (
        SnapshotExecutionService,
        WorkflowSnapshotExecutionRequest,
    )
    from backend.service.application.workflows.service_runtime.context import (
        WorkflowServiceNodeRuntimeContext,
    )
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        DatasetStorageSettings,
        LocalDatasetStorage,
    )
    from custom_nodes.opencv_nodes.shared.workflow.payload_contracts import (
        load_shared_opencv_payload_contracts_payload,
    )

    image, registry, template = build_chain()
    catalog = build_custom_node_catalog_document()
    snapshot = NodeCatalogSnapshot(
        node_definitions=catalog.node_definitions,
        payload_contracts=tuple(
            WorkflowPayloadContract.model_validate(p)
            for p in load_shared_opencv_payload_contracts_payload()
        )
        + catalog.payload_contracts,
    )
    node_catalog = NodeCatalogRegistry(
        node_pack_loader=SimpleNamespace(get_catalog_snapshot=lambda: snapshot)
    )
    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "store"))
    )
    if physical:
        from backend.contracts.workflows.measurement_resources import (
            MeasurementResourceContent,
        )
        from backend.service.application.workflows.documents.measurement_resources import (
            MeasurementResourceService,
        )
        from tests.test_measurement_resources import calibration

        _, _, truth, _ = source("single10_front")
        scale = 1 / truth["camera"]["pixels_per_mm"]
        baseline = calibration().calibration
        calibrated = baseline.model_copy(
            update={
                "world_from_image": (
                    (scale, 0.0, 0.0),
                    (0.0, scale, 0.0),
                    (0.0, 0.0, 1.0),
                )
            }
        )
        saved = MeasurementResourceService(storage).save(
            project_id="connector-test",
            name="Engineering scale",
            content=MeasurementResourceContent(
                kind="planar-calibration", calibration=calibrated
            ),
        )
        nodes = list(template.nodes)
        nodes[1] = nodes[1].model_copy(
            update={
                "parameters": nodes[1].parameters
                | {
                    "unit": "millimeter",
                    "calibration_resource": saved.reference.model_dump(mode="json"),
                }
            }
        )
        nodes[2] = nodes[2].model_copy(
            update={
                "parameters": {
                    "rules": [
                        dict(
                            item_id="width:R1P01",
                            unit="millimeter",
                            lower=0.59,
                            upper=0.69,
                        )
                    ]
                }
            }
        )
        template = template.model_copy(update={"nodes": tuple(nodes)})
    context = WorkflowServiceNodeRuntimeContext(
        session_factory=None, dataset_storage=storage
    )
    application = FlowApplication.model_validate(
        dict(
            application_id="connector-engineering-app",
            display_name="Connector Engineering",
            template_ref=dict(
                template_id=template.template_id,
                template_version=template.template_version,
                source_kind="embedded",
            ),
            bindings=[
                dict(
                    binding_id="image",
                    direction="input",
                    template_port_id="image",
                    binding_kind="workflow-execute-input",
                    config={"payload_type_id": "image-ref.v1"},
                ),
                dict(
                    binding_id="result",
                    direction="output",
                    template_port_id="result",
                    binding_kind="workflow-execute-output",
                    config={"payload_type_id": "value.v1"},
                ),
            ],
        )
    )
    service_args = dict(
        dataset_storage=storage,
        node_catalog_registry=node_catalog,
        runtime_registry=registry,
        runtime_context=context,
    )
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    stored = storage.write_immutable_object(
        object_prefix="projects/connector-test/workflow-inputs/reference",
        content=encoded.tobytes(),
        media_type="image/png",
        extension=".png",
    )
    payload = {
        "transport_kind": "storage",
        "object_key": stored.metadata.object_key,
        "media_type": "image/png",
    }
    input_files = set((tmp_path / "store").rglob("*.png"))
    outputs = []
    for mode in ("preview", "runtime"):
        images = ExecutionImageRegistry()
        common = dict(
            project_id="connector-test",
            application_id=application.application_id,
            input_bindings={"image": payload},
            execution_metadata={"execution_image_registry": images},
        )
        if mode == "preview":
            result = PreviewMemoryExecutionService(**service_args).execute(
                PreviewMemoryExecutionRequest(
                    **common,
                    application=application,
                    template=template,
                    session_id="connector-session",
                )
            )
            assert set((tmp_path / "store").rglob("*.png")) == input_files
            assert not list((tmp_path / "store").rglob("*.jpg"))
        else:
            storage.write_json(
                "connector/application.json", application.model_dump(mode="json")
            )
            storage.write_json(
                "connector/template.json", template.model_dump(mode="json")
            )
            result = SnapshotExecutionService(**service_args).execute(
                WorkflowSnapshotExecutionRequest(
                    **common,
                    application_snapshot_object_key="connector/application.json",
                    template_snapshot_object_key="connector/template.json",
                )
            )
        outputs.append(result.outputs["result"]["value"])
        images.clear()
    assert outputs[0]["passed"] is True
    assert outputs[0]["items"] == outputs[1]["items"]
    if physical:
        assert abs(outputs[0]["items"][0]["value"] - 0.64) < 0.021
        assert outputs[0]["items"][0]["unit"] == "millimeter"
    context.close()


@pytest.mark.parametrize("family", ["single10_front", "dual08_top"])
@pytest.mark.parametrize("condition", ["translate", "rotate_pos", "rotate_neg"])
def test_real_pose_to_pin_to_measurement(family, condition, tmp_path):
    """实际定位节点的姿态连入行业节点，量测配方保持参考坐标定义。"""
    image, layout, ref_truth, _ = source(family, condition)
    reference, _, _, _ = source(family)
    resource = json.loads(
        (ASSETS / "references" / f"{family}.json").read_text(encoding="utf-8")
    )
    polygon = np.asarray(resource["template_roi_polygon_px"])
    low, high = (
        np.floor(polygon.min(axis=0) - 5).astype(int),
        np.ceil(polygon.max(axis=0) + 5).astype(int),
    )
    registry = ExecutionImageRegistry()
    payload = register_image_matrix(request(registry), image_matrix=image)
    import hashlib
    from backend.contracts.workflows.measurement_resources import (
        MeasurementResourceContent,
    )
    from backend.service.application.workflows.documents.measurement_resources import (
        MeasurementResourceService,
        PreparedMeasurementResources,
    )
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        DatasetStorageSettings,
        LocalDatasetStorage,
    )

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "store"))
    )
    _, encoded = cv2.imencode(".png", reference)
    encoded = encoded.tobytes()
    content = MeasurementResourceContent(
        kind="localization-template",
        template=dict(
            reference_id=family,
            image_width=reference.shape[1],
            image_height=reference.shape[0],
            template_roi=(*low.tolist(), *(high - low).tolist()),
            anchor=resource["template_anchor_image_px"],
            image_sha256=hashlib.sha256(encoded).hexdigest(),
        ),
    )
    saved = MeasurementResourceService(storage).save(
        project_id="test", name=family, content=content, image_bytes=encoded
    )
    layout["reference_sha256"] = saved.reference.sha256
    locate_request = request(
        registry,
        {"template_resource": saved.reference.model_dump(mode="json")},
        {"image": payload},
    )
    locate_request.execution_metadata.update(
        project_id="test",
        prepared_measurement_resources=PreparedMeasurementResources(storage).prepare(
            (saved.reference,), project_id="test"
        ),
    )
    pose = rigid_locate(locate_request)["pose"]
    output = locate(
        request(registry, dict(layout=layout), {"image": payload, "pose": pose})
    )
    measured = measure(
        request(
            registry,
            {"items": dimensions(layout)},
            {"pins": output["pins"], "features": output["features"]},
        )
    )
    for item in measured["measurements"]["items"][: len(layout["pins"])]:
        assert item["valid"], item
        assert abs(item["value"] - 0.64 * ref_truth["camera"]["pixels_per_mm"]) < 0.7
