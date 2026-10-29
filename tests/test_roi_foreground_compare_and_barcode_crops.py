"""验证通用前景比较及裁剪读码的空值、标识、坐标与真实解析边界。"""

from dataclasses import replace
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import NodeDefinition
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.roi_foreground_compare import (
    handle_node as compare,
)
from custom_nodes.barcode_nodes.categories.compose.backend.nodes.crop_decode import (
    handle_node as decode,
)


def image_ref(tmp_path, name, matrix):
    """将测试矩阵保存到测试专用目录，避免依赖系统路径和对象存储。"""
    path = tmp_path / name
    path.write_bytes(cv2.imencode(".png", matrix)[1].tobytes())
    return {
        "transport_kind": "local-path",
        "local_path": str(path),
        "media_type": "image/png",
        "width": matrix.shape[1],
        "height": matrix.shape[0],
    }


def request(kind, values, parameters=None):
    """使用真实目录定义构造节点请求。"""
    path = (
        "custom_nodes/opencv_nodes/categories/defect/workflow/catalog_sources/nodes/roi_foreground_compare.json"
        if kind == "compare"
        else "custom_nodes/barcode_nodes/categories/compose/workflow/nodes/crop_decode.json"
    )
    definition = NodeDefinition.model_validate(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )
    return WorkflowNodeExecutionRequest(
        node_id="test",
        node_definition=definition,
        parameters=parameters or {},
        input_values=values,
    )


def roi(identifier="region-a", bbox=None):
    """构造带稳定标识的矩形 ROI。"""
    x1, y1, x2, y2 = bbox or [0, 0, 160, 120]
    return {
        "roi_id": identifier,
        "roi_kind": "bbox",
        "bbox_xyxy": [x1, y1, x2, y2],
        "polygon_xy": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        "area": (x2 - x1) * (y2 - y1),
    }


@pytest.mark.parametrize("case", ["same", "empty", "shift", "rotate"])
def test_comparison_detects_geometric_change_without_alignment(tmp_path, case):
    """参考自检通过，缺件、偏移与旋转不能被自动配准隐藏。"""
    normal = np.full((120, 160), 255, np.uint8)
    normal[20:100, 30:65] = 0
    normal[65:100, 30:125] = 0
    current = normal.copy()
    if case == "empty":
        current[:] = 255
    elif case == "shift":
        current = cv2.warpAffine(
            normal, np.float32([[1, 0, 15], [0, 1, 0]]), (160, 120), borderValue=255
        )
    elif case == "rotate":
        current = cv2.warpAffine(
            normal,
            cv2.getRotationMatrix2D((80, 60), 12, 1),
            (160, 120),
            borderValue=255,
        )
    result = compare(
        request(
            "compare",
            {
                "image": image_ref(tmp_path, "a.png", current),
                "reference_image": image_ref(tmp_path, "b.png", normal),
                "rois": [roi()],
            },
        )
    )
    item = result["summary"]["value"]["items"][0]
    assert item["item_id"] == "region-a"
    assert item["result"]["passed"] is (case == "same")
    if case == "empty":
        assert item["result"]["missing_ratio"] == 1
    assert result["regions"]["items"][0]["region_id"] == item["item_id"]


def test_invalid_reference_duplicate_outside_and_order(tmp_path):
    """无前景参考不能通过，越界/重复拒绝，交换顺序不交换标识。"""
    blank = image_ref(tmp_path, "blank.png", np.full((120, 160), 255, np.uint8))
    req = request(
        "compare", {"image": blank, "reference_image": blank, "rois": [roi()]}
    )
    item = compare(req)["summary"]["value"]["items"][0]["result"]
    assert (
        item["state"] == "invalid_reference"
        and item["passed"] is False
        and item["missing_ratio"] is None
    )
    for rois in ([roi(), roi()], [roi(bbox=[-1, 0, 160, 120])], []):
        with pytest.raises(InvalidRequestError):
            compare(replace(req, input_values=req.input_values | {"rois": rois}))
    a, b = roi("a", [0, 0, 80, 120]), roi("b", [80, 0, 160, 120])
    output = compare(replace(req, input_values=req.input_values | {"rois": [b, a]}))
    assert [i["item_id"] for i in output["summary"]["value"]["items"]] == ["b", "a"]


def test_polygon_domain_excludes_neighbor_but_detects_owned_piece(tmp_path):
    """同一外接矩形内的邻件变化不影响当前多边形，域内缺件仍失败。"""
    normal = np.full((120, 160), 255, np.uint8)
    normal[20:60, 20:60] = 0
    normal[70:110, 90:140] = 0
    domain = roi()
    domain.update(
        roi_kind="polygon",
        polygon_xy=[[0, 0], [80, 0], [80, 65], [160, 65], [160, 120], [0, 120]],
    )
    current = normal.copy()
    current[10:50, 100:140] = 0
    reference = image_ref(tmp_path, "reference.png", normal)
    req = request(
        "compare",
        {
            "image": image_ref(tmp_path, "neighbor.png", current),
            "reference_image": reference,
            "rois": [domain],
        },
    )
    assert compare(req)["summary"]["value"]["passed"] is True
    current[20:60, 20:60] = 255
    req = replace(
        req,
        input_values=req.input_values
        | {"image": image_ref(tmp_path, "missing.png", current)},
    )
    assert compare(req)["summary"]["value"]["passed"] is False


def test_barcode_empty_and_unreadable_retained(tmp_path):
    """没有检测候选和有候选但未读出是不同状态。"""
    blank = image_ref(tmp_path, "blank.png", np.full((100, 100), 255, np.uint8))
    crop = blank | {"crop_index": 1, "roi_id": "target", "bbox_xyxy": [0, 0, 100, 100]}
    base = {"source_image": blank, "items": []}
    assert (
        decode(request("decode", {"crops": base}))["summary"]["value"]["state"]
        == "no_candidates"
    )
    req = request(
        "decode", {"crops": base | {"items": [crop]}}, {"format": "data-matrix"}
    )
    output = decode(req)["summary"]["value"]
    assert output["count"] == 1 and output["items"][0]["item_id"] == "target"
    assert output["items"][0]["result"]["state"] == "unreadable"
    for scale in [0, 5, True, 1.5]:
        with pytest.raises(InvalidRequestError):
            decode(replace(req, parameters={"decode_scale": scale}))
    for invalid in (
        [crop, crop],
        [crop | {"bbox_xyxy": [0, 0, 90, 100]}],
        [crop | {"crop_index": True}],
    ):
        with pytest.raises(InvalidRequestError):
            decode(replace(req, input_values={"crops": base | {"items": invalid}}))


@pytest.mark.parametrize("decode_scale", [1, 2, 4])
def test_real_data_matrix_decode_and_parent_coordinates(tmp_path, decode_scale):
    """使用已知内容的真实编码器验证解析与父坐标平移，不依赖生成图条码。"""
    import zxingcpp

    matrix = np.asarray(
        zxingcpp.write_barcode_to_image(
            zxingcpp.create_barcode(
                "reference-code-3913", zxingcpp.BarcodeFormat.DataMatrix
            ),
            scale=6,
            add_quiet_zones=True,
        )
    )
    h, w = matrix.shape[:2]
    parent = image_ref(tmp_path, "parent.png", np.full((h + 50, w + 60), 255, np.uint8))
    crop = image_ref(tmp_path, "code.png", matrix) | {
        "crop_index": 7,
        "roi_id": "code-a",
        "bbox_xyxy": [20, 30, w + 20, h + 30],
    }
    output = decode(
        request(
            "decode",
            {"crops": {"source_image": parent, "items": [crop]}},
            {"format": "data-matrix", "decode_scale": decode_scale},
        )
    )
    assert output["summary"]["value"]["items"][0]["result"]["state"] == "decoded"
    item = output["results"]["items"][0]
    assert item["text"] == "reference-code-3913"
    assert (
        item["position"]["bounds_xyxy"][0] >= 20
        and item["position"]["bounds_xyxy"][1] >= 30
    )
    assert item["extra"]["item_id"] == "code-a"
    assert item["position"]["bounds_xyxy"][2] <= w + 20
    assert item["position"]["bounds_xyxy"][3] <= h + 30
    assert output["summary"]["value"]["decode_scale"] == decode_scale


def test_crop_sources_preserve_identity_and_allow_empty(tmp_path):
    """ROI 值列表及规范化 regions 都可裁剪，空列表跳过，冲突来源拒绝。"""
    from custom_nodes.opencv_nodes.categories.basic.backend.nodes.crop_export import (
        _resolve_crop_specs,
    )

    base = request("decode", {})
    items = [roi("slot-b"), roi("slot-a")]
    specs = _resolve_crop_specs(
        replace(base, input_values={"roi_items": {"value": items}})
    )
    assert [s["roi_id"] for s in specs] == ["slot-b", "slot-a"]
    assert (
        _resolve_crop_specs(replace(base, input_values={"roi_items": {"value": []}}))
        == []
    )
    source = image_ref(tmp_path, "source.png", np.full((120, 160), 255, np.uint8))
    regions = {
        "source_image": source,
        "items": [
            {
                "region_id": "code-a",
                "bbox_xyxy": [10, 20, 80, 90],
                "score": 0.9,
                "class_name": "dmcode",
                "class_id": 1,
                "polygon_xy": [],
                "area": 4900,
            }
        ],
    }
    specs = _resolve_crop_specs(replace(base, input_values={"regions": regions}))
    assert specs[0]["region_id"] == "code-a" and specs[0]["bbox_xyxy"] == (
        10,
        20,
        80,
        90,
    )
    assert (
        _resolve_crop_specs(
            replace(base, input_values={"regions": regions | {"items": []}})
        )
        == []
    )
    with pytest.raises(InvalidRequestError):
        _resolve_crop_specs(
            replace(base, input_values={"regions": regions, "roi_items": {"value": []}})
        )


def test_foreground_pose_measures_rotation_shift_and_ambiguous_axis(tmp_path):
    """形状差异之外，显式位姿检查应报告偏移/旋转并拒绝不可测主轴。"""
    from custom_nodes.opencv_nodes.categories.defect.backend.nodes.roi_foreground_compare import (
        compare_foreground,
    )

    normal = np.full((200, 240), 255, np.uint8)
    normal[35:165, 90:150] = 0
    for angle, dx in [(0, 12), (9, 0), (0, 0)]:
        matrix = cv2.getRotationMatrix2D((119.5, 99.5), angle, 1)
        matrix[0, 2] += dx
        current = cv2.warpAffine(normal, matrix, (240, 200), borderValue=255)
        result = compare_foreground(
            current, normal, threshold=80, polarity="dark", tolerance_pixels=2
        )
        assert result["centroid_shift_pixels"] == pytest.approx(dx, abs=0.1)
        assert result["axis_angle_difference_degrees"] == pytest.approx(angle, abs=0.2)
    circular = np.full_like(normal, 255)
    cv2.circle(circular, (120, 100), 25, 0, -1)
    assert (
        compare_foreground(
            circular, circular, threshold=80, polarity="dark", tolerance_pixels=2
        )["axis_angle_difference_degrees"]
        is None
    )


def test_comparison_images_are_optional_and_keep_roi_ids(tmp_path):
    """只有显式开启才分配逐槽差异图；图片和判定按同一 ROI ID 关联。"""
    from backend.nodes import ExecutionImageRegistry

    registry = ExecutionImageRegistry()
    normal = np.full((120, 160), 255, np.uint8)
    normal[20:100, 40:80] = 0
    current = np.full_like(normal, 255)
    current[20:100, 55:95] = 0
    req = request(
        "compare",
        {
            "image": image_ref(tmp_path, "current.png", current),
            "reference_image": image_ref(tmp_path, "reference.png", normal),
            "rois": [roi()],
        },
        {"check_pose": True, "max_centroid_shift_pixels": 5},
    )
    req = replace(req, execution_metadata={"execution_image_registry": registry})
    try:
        assert compare(req)["comparison_images"]["count"] == 0
        output = compare(
            replace(req, parameters=req.parameters | {"emit_comparison_images": True})
        )
        row = output["summary"]["value"]["items"][0]
        assert "centroid_displaced" in row["result"]["reasons"]
        crop = output["comparison_images"]["items"][0]
        assert crop["roi_id"] == row["item_id"]
        visual = registry.read_matrix(crop["image_handle"])
        assert np.any(np.all(visual == (68, 68, 224), axis=2))
        assert np.any(np.all(visual == (0, 139, 217), axis=2))
    finally:
        registry.clear()


def test_boundary_observes_outside_without_changing_crop_source(tmp_path):
    """越界部分必须在搜索余量内参与判定，后续工件裁图仍使用原槽位坐标。"""
    normal = np.full((120, 160), 255, np.uint8)
    normal[35:85, 50:85] = 0
    current = normal.copy()
    current[40:80, 101:108] = 0
    region = roi(bbox=[30, 25, 100, 95])
    req = request(
        "compare",
        {
            "image": image_ref(tmp_path, "current.png", current),
            "reference_image": image_ref(tmp_path, "reference.png", normal),
            "rois": [region],
        },
        {
            "check_boundary": True,
            "search_margin_pixels": 12,
            "tolerance_pixels": 0,
            "max_outside_ratio": 0.01,
            "max_excess_ratio": 1,
        },
    )
    output = compare(req)
    item = output["summary"]["value"]["items"][0]
    assert output["regions"]["items"][0]["bbox_xyxy"] == region["bbox_xyxy"]
    assert output["regions"]["items"][0]["area"] == region["area"]
    assert item["result"]["shape_passed"] is True
    assert item["result"]["boundary_passed"] is False
    assert item["result"]["outside_pixels"] == 280
    assert item["result"]["reasons"] == ["foreground_outside_allowed_roi"]
    assert item["source"]["bbox_xyxy"] == region["bbox_xyxy"]
    # 正常参考自身越界时配置无效，不能据此给出正常结论。
    result = compare(
        replace(
            req,
            input_values=req.input_values
            | {"reference_image": req.input_values["image"]},
        )
    )
    assert (
        result["summary"]["value"]["items"][0]["result"]["state"] == "invalid_reference"
    )
    with pytest.raises(InvalidRequestError, match="大于"):
        compare(replace(req, parameters=req.parameters | {"tolerance_pixels": 12}))
    with pytest.raises(InvalidRequestError, match="超出"):
        compare(replace(req, parameters=req.parameters | {"search_margin_pixels": 40}))
