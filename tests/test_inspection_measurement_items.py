"""逐 ROI 测量链的数值、标识、未知状态与证据绘图边界。"""

from copy import deepcopy
from dataclasses import replace

import cv2
import numpy as np
import pytest

from backend.nodes import ExecutionImageRegistry
from backend.nodes.runtime_support import register_typed_image_matrix
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes import (
    roi_mask_extract,
    mask_items_properties,
    mask_items_difference,
    pose_items_difference,
    measurement_items_check,
    inspection_items_merge,
    draw_inspection_items,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.inspection_items import (
    binary_matrix,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from tests.test_roi_foreground_compare_and_barcode_crops import roi


@pytest.fixture
def req():
    """图像使用真实 Run 注册表，结束后释放，不写入永久文件。"""
    registry = ExecutionImageRegistry()
    request = WorkflowNodeExecutionRequest(
        node_id="measure",
        node_definition=object(),
        parameters={},
        input_values={},
        execution_metadata={"execution_image_registry": registry},
    )
    yield request
    registry.clear()


def call(module, req, values, parameters=None):
    """直接执行正式节点处理器。"""
    return module.handle_node(
        replace(req, input_values=values, parameters=parameters or {})
    )


def extract(req, matrix, rois=None, margin=0):
    """在偏移的观察框内提取前景以验证全图坐标。"""
    image = register_typed_image_matrix(req, image_matrix=matrix)
    return call(
        roi_mask_extract,
        req,
        {"mask": image, "rois": rois or [roi("a", [10, 10, 90, 90])]},
        {"search_margin_pixels": margin},
    )


def metrics(req, masks):
    """测量真实掩膜。"""
    return call(mask_items_properties, req, {"masks": masks})["metrics"]


def check(req, values, name="area", metric="area", **limits):
    """创建独立阈值判定记录。"""
    return call(
        measurement_items_check,
        req,
        {"metrics": values},
        {"check_id": name, "metric": metric, **limits},
    )["checks"]


def test_pixel_moments_include_holes_global_center_and_single_pixel(req):
    matrix = np.zeros((100, 100), np.uint8)
    matrix[20:60, 30:40] = 255
    matrix[30:40, 32:36] = 0
    extracted = extract(req, matrix)
    result = metrics(req, extracted["masks"])["value"]["items"][0]["result"]
    ys, xs = np.nonzero(matrix)
    assert result["area"] == len(xs)
    np.testing.assert_allclose(result["center_xy"], [xs.mean(), ys.mean()])
    assert abs(abs(result["axis_angle_degrees"]) - 90) < 1
    matrix[:] = 0
    matrix[25, 35] = 255
    result = metrics(req, extract(req, matrix)["masks"])["value"]["items"][0]["result"]
    assert result["center_xy"] == [35, 25] and result["axis_angle_degrees"] is None


def test_directed_difference_denominators_and_tolerance(req):
    a = np.zeros((100, 100), np.uint8)
    a[30:40, 30:40] = 255
    b = a.copy()
    b[30:40, 40:42] = 255
    am, bm = extract(req, a)["masks"], extract(req, b)["masks"]
    diff = call(mask_items_difference, req, {"masks_a": bm, "masks_b": am})
    result = diff["metrics"]["value"]["items"][0]["result"]
    assert result["difference_area"] == 20
    assert result["ratio_to_a"] == pytest.approx(20 / 120)
    assert result["ratio_to_b"] == 0.2
    assert np.count_nonzero(binary_matrix(req, diff["masks"]["items"][0])) == 20
    tolerant = call(
        mask_items_difference,
        req,
        {"masks_a": bm, "masks_b": am},
        {"tolerance_pixels": 3},
    )
    assert tolerant["metrics"]["value"]["items"][0]["result"]["difference_area"] == 0


def test_id_pairing_is_independent_of_order_and_missing_ids_reject(req):
    image = np.zeros((100, 100), np.uint8)
    image[20:80, 20:80] = 255
    rois = [roi("a", [10, 10, 50, 90]), roi("b", [50, 10, 90, 90])]
    a = extract(req, image, rois)["masks"]
    b = deepcopy(a)
    b["items"].reverse()
    diff = call(mask_items_difference, req, {"masks_a": a, "masks_b": b})
    assert [i["item_id"] for i in diff["metrics"]["value"]["items"]] == ["a", "b"]
    assert all(
        i["result"]["difference_area"] == 0 for i in diff["metrics"]["value"]["items"]
    )
    b["items"].pop()
    with pytest.raises(InvalidRequestError):
        call(mask_items_difference, req, {"masks_a": a, "masks_b": b})


@pytest.mark.parametrize(
    "mutation", ["duplicate", "space", "shape", "missing_source", "not_binary"]
)
def test_mask_contract_rejects_invalid_pairs(req, mutation):
    image = np.zeros((100, 100), np.uint8)
    a = extract(req, image)["masks"]
    b = deepcopy(a)
    item = b["items"][0]
    if mutation == "duplicate":
        b["items"].append(deepcopy(item))
    elif mutation == "space":
        item["measurement_source"]["coordinate_space"] = "different"
    elif mutation == "shape":
        item["measurement_source"]["observation_bbox_xyxy"][2] = 91
    elif mutation == "missing_source":
        del item["measurement_source"]["image_size"]
    else:
        altered = register_typed_image_matrix(
            req, image_matrix=np.full((80, 80), 10, np.uint8)
        )
        b["items"][0] = altered | {k: item[k] for k in ("roi_id", "measurement_source")}
    with pytest.raises(InvalidRequestError):
        call(mask_items_difference, req, {"masks_a": a, "masks_b": b})


def test_empty_and_round_shapes_do_not_silently_pass_angle(req):
    image = np.zeros((100, 100), np.uint8)
    empty = metrics(req, extract(req, image)["masks"])
    cv2.circle(image, (50, 50), 15, 255, -1)
    round_metrics = metrics(req, extract(req, image)["masks"])
    for current in (empty, round_metrics):
        pose = call(
            pose_items_difference, req, {"current": current, "reference": round_metrics}
        )["metrics"]
        decision = check(req, pose, "angle", "axis_angle_difference_degrees", maximum=3)
        result = decision["value"]["items"][0]["result"]
        assert (
            result["value"] is None
            and result["state"] == "unavailable"
            and result["passed"] is False
        )


def test_centroid_and_undirected_axis_difference(req):
    a = np.zeros((100, 100), np.uint8)
    a[20:60, 25:35] = 255
    b = np.zeros_like(a)
    b[24:64, 28:38] = 255
    pa, pb = (
        metrics(req, extract(req, a)["masks"]),
        metrics(req, extract(req, b)["masks"]),
    )
    result = call(pose_items_difference, req, {"current": pb, "reference": pa})[
        "metrics"
    ]
    r = result["value"]["items"][0]["result"]
    assert (r["dx"], r["dy"], r["centroid_shift_pixels"]) == (3, 4, 5)
    assert r["axis_angle_difference_degrees"] == 0
    assert check(req, result, "shift", "centroid_shift_pixels", minimum=0, maximum=5)[
        "value"
    ]["items"][0]["result"]["passed"]
    assert not check(req, result, "shift", "centroid_shift_pixels", maximum=4.99)[
        "value"
    ]["items"][0]["result"]["passed"]


def test_merge_and_drawing_use_original_checks(req):
    image = np.zeros((100, 100), np.uint8)
    image[25:65, 30:40] = 255
    masks = extract(req, image)["masks"]
    area = metrics(req, masks)
    good = check(req, area, minimum=400, maximum=400)
    bad = check(req, area, "too_small", minimum=401)
    original = deepcopy(good)
    ref = register_typed_image_matrix(
        req, image_matrix=cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    )
    merged = call(
        inspection_items_merge,
        req,
        {
            "image": ref,
            "checks": {"value": {"area": good["value"], "too_small": bad["value"]}},
        },
    )
    result = merged["summary"]["value"]["items"][0]["result"]
    assert result["passed"] is False and result["reasons"] == ["too_small"]
    drawings = call(
        draw_inspection_items, req, {"image": ref, "checks": good, "masks": masks}
    )
    assert good == original
    output = drawings["images"]["items"][0]
    assert output["roi_id"] == "a" and output["visualization_only"]
    _, _, canvas = load_image_matrix(replace(req, input_values={"image": output}))
    assert canvas.shape[0] == 146
    with pytest.raises(InvalidRequestError):
        call(
            inspection_items_merge,
            req,
            {"image": ref, "checks": {"value": {"wrong_name": good["value"]}}},
        )
    with pytest.raises(InvalidRequestError):
        call(inspection_items_merge, req, {"image": ref, "checks": {"value": {}}})


@pytest.mark.parametrize(
    "bad", [{}, {"maximum": float("nan")}, {"minimum": 2, "maximum": 1}]
)
def test_invalid_check_configuration_rejects(req, bad):
    m = metrics(req, extract(req, np.zeros((100, 100), np.uint8))["masks"])
    with pytest.raises(InvalidRequestError):
        check(req, m, **bad)


def test_unknown_measurement_field_rejects_and_no_implicit_grayscale(req):
    m = metrics(req, extract(req, np.zeros((100, 100), np.uint8))["masks"])
    with pytest.raises(InvalidRequestError):
        check(req, m, metric="wrong", maximum=1)
    with pytest.raises(InvalidRequestError):
        extract(req, np.zeros((100, 100, 3), np.uint8))


def test_schema_and_handlers_registered():
    from custom_nodes.opencv_nodes.categories.defect.backend.nodes import NODE_HANDLERS
    from custom_nodes.opencv_nodes.workflow.catalog_builder import (
        build_custom_node_catalog_document,
    )

    catalog = build_custom_node_catalog_document()
    ids = {n.node_type_id for n in catalog.node_definitions}
    handlers = dict(NODE_HANDLERS)
    for module in (
        roi_mask_extract,
        mask_items_properties,
        mask_items_difference,
        pose_items_difference,
        measurement_items_check,
        inspection_items_merge,
        draw_inspection_items,
    ):
        assert (
            module.NODE_TYPE_ID in ids
            and handlers[module.NODE_TYPE_ID] is module.handle_node
        )


def test_drawing_rejects_unchecked_measurement_records(req):
    """绘图只能消费判定记录，不能把未检查的测量冒充通过或失败。"""
    image = np.zeros((100, 100), np.uint8)
    measured = metrics(req, extract(req, image)["masks"])
    ref = register_typed_image_matrix(req, image_matrix=image)
    with pytest.raises(InvalidRequestError):
        call(draw_inspection_items, req, {"image": ref, "checks": measured})


def test_value_preview_projects_explicit_nested_columns_without_changing_input(req):
    """表格列显式读取嵌套测量字段，缺失路径显示空值，不修改业务数据。"""
    from backend.nodes.core_nodes.io.preview.value_preview import _value_preview_handler

    payload = {
        "value": {
            "items": [{"item_id": "slot-a", "result": {"value": 5, "passed": False}}]
        }
    }
    before = deepcopy(payload)
    result = _value_preview_handler(
        replace(
            req,
            input_values={"value": payload},
            parameters={
                "display_mode": "table",
                "path": "items",
                "columns": [
                    {"key": "slot", "label": "槽位", "path": "item_id"},
                    {"key": "measurement", "label": "数值", "path": "result.value"},
                    {"key": "absent", "label": "缺失", "path": "result.missing"},
                ],
            },
        )
    )
    assert result["body"]["rows"] == [
        {
            "item_id": "slot-a",
            "result": {"value": 5, "passed": False},
            "slot": "slot-a",
            "measurement": 5,
            "absent": None,
        }
    ]
    assert payload == before
    with pytest.raises(InvalidRequestError):
        _value_preview_handler(
            replace(
                req,
                input_values={"value": payload},
                parameters={
                    "display_mode": "table",
                    "path": "items",
                    "columns": [{"key": "value", "label": "数值", "path": ""}],
                },
            )
        )
