"""验证通用图案配准和局部裁剪的确定性、歧义拒绝及坐标边界。"""

import json
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import NodeDefinition
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.circle_pattern_locate import (
    Settings,
    locate_pattern,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.mapped_roi_crop import (
    Region,
    crop_geometry,
    lift_transform,
    handle_node,
)


def pattern_settings(points, **kw):
    """创建不规则、可命名且允许少量漏点的参考图案。"""
    return Settings(
        reference_points=[
            {"point_id": str(i), "center_xy": p} for i, p in enumerate(points)
        ],
        match_tolerance_px=2,
        maximum_rmse_px=0.2,
        minimum_match_ratio=0.8,
        maximum_angle_degrees=15,
        maximum_translation_px=500,
        **kw,
    )


@pytest.mark.parametrize("angle", [0, -9, 7])
def test_pattern_order_missing_outliers(angle):
    """打乱候选顺序、少一个圆且增加伪圆，仍得到相同刚性位姿。"""
    points = np.array(
        [[20, 20], [80, 25], [140, 40], [30, 100], [90, 110], [160, 140]], float
    )
    truth = np.eye(3)
    truth[:2] = cv2.getRotationMatrix2D((80, 70), angle, 1)
    truth[:2, 2] += [30, 15]
    observed = points @ truth[:2, :2].T + truth[:2, 2]
    observed = np.vstack([observed[:-1], [[250, 180], [280, 220]]])[::-1]
    matrix, ri, ci, rmse, _ = locate_pattern(points, observed, pattern_settings(points))
    np.testing.assert_allclose(matrix, truth, atol=1e-8)
    assert len(ri) == 5 and rmse < 1e-8 and len(set(ci)) == 5


def test_pattern_rejects_ambiguous_and_insufficient_and_scale():
    """两个同图案、过少圆或尺度变化都不能被静默解释成唯一刚性定位。"""
    points = np.array(
        [[20, 20], [80, 25], [140, 40], [30, 100], [90, 110], [160, 140]], float
    )
    for observed in [np.vstack([points, points + [240, 0]]), points[:2], points * 1.3]:
        with pytest.raises(ValueError):
            locate_pattern(points, observed, pattern_settings(points))


def test_pattern_hypothesis_budget_and_cancellation():
    """搜索不能无限增长；取消必须传播。"""
    points = np.array(
        [[20, 20], [80, 25], [140, 40], [30, 100], [90, 110], [160, 140]], float
    )
    with pytest.raises(ValueError, match="上限"):
        locate_pattern(points, points, pattern_settings(points, maximum_hypotheses=1))

    def stop():
        raise TimeoutError("cancelled")

    with pytest.raises(TimeoutError):
        locate_pattern(points, points, pattern_settings(points), check=stop)


def test_resize_pixel_centers_and_local_sampling():
    """定位图倍率包含半像素偏移，局部反向采样与原图像素一致。"""
    small = np.eye(3)
    small[:2] = cv2.getRotationMatrix2D((30, 20), 7, 1)
    small[:2, 2] += [3, 4]
    lifted = lift_transform(small, 8)
    p = np.array([10.0, 12.0, 1])
    raw = p.copy()
    raw[:2] = (p[:2] + 0.5) * 8 - 0.5
    mapped = small @ p
    expected = (mapped[:2] + 0.5) * 8 - 0.5
    np.testing.assert_allclose((lifted @ raw)[:2], expected)
    image = np.arange(160 * 120, dtype=np.uint16).reshape(120, 160)
    translation = np.array([[1.0, 0, 15], [0, 1, 20], [0, 0, 1]])
    region = Region(roi_id="a", bbox_xyxy=(20, 10, 60, 50))
    matrix, polygon, size = crop_geometry(region, translation, 160, 120)
    actual = cv2.warpPerspective(
        image, matrix, size, flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP
    )
    np.testing.assert_array_equal(actual, image[30:70, 35:75])
    np.testing.assert_allclose(polygon[0], [35, 30])
    with pytest.raises(ValueError, match="超出"):
        crop_geometry(region, translation, 40, 40)


def test_crop_empty_selection_and_invalid_contract():
    """空选择不读图；重复名称、无效选择、错误方向和退化变换被拒绝。"""
    path = Path(
        "custom_nodes/opencv_nodes/categories/geometry/workflow/catalog_sources/nodes/mapped_roi_crop.json"
    )
    transform = {
        "transform_kind": "rigid",
        "matrix_3x3": np.eye(3).tolist(),
        "source_coordinate_space": "template-image-pixels",
        "target_coordinate_space": "source-image-pixels",
        "match_count": 3,
        "inlier_count": 3,
        "inlier_match_ids": [],
    }
    region = {"roi_id": "a", "bbox_xyxy": [10, 10, 30, 30]}
    values = {
        "transform": transform,
        "roi_items": {"value": [region]},
        "selected_ids": {"value": []},
    }
    req = WorkflowNodeExecutionRequest(
        node_id="crop",
        node_definition=NodeDefinition.model_validate(
            json.loads(path.read_text("utf-8"))
        ),
        parameters={},
        input_values=values,
    )
    result = handle_node(req)
    assert result["crops"]["items"] == []
    assert result["summary"]["value"]["items"][0]["state"] == "skipped"
    # 执行器为未连接的可选端口传入 None，和显式空列表语义不同。
    result = handle_node(
        replace(
            req,
            input_values=values
            | {
                "roi_items": {"value": []},
                "selected_ids": None,
            },
        )
    )
    assert result["crops"]["count"] == 0
    for patch in [
        {"roi_items": {"value": [region, region]}},
        {"selected_ids": {"value": ["unknown"]}},
        {"transform": transform | {"source_coordinate_space": "other"}},
        {"transform": transform | {"matrix_3x3": np.zeros((3, 3)).tolist()}},
        {"roi_items": {"value": [region | {"bbox_xyxy": [10, 10, 5, 20]}]}},
    ]:
        with pytest.raises(InvalidRequestError):
            handle_node(replace(req, input_values=values | patch))


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_mapped_crop_pixels_identity_budget_and_scale(tmp_path, dtype):
    """实际载图、裁剪及注册输出，验证相同像素、来源矩阵与配置边界。"""
    from backend.nodes import ExecutionImageRegistry

    image = np.arange(120 * 160, dtype=dtype).reshape(120, 160)
    path = tmp_path / "source.png"
    path.write_bytes(cv2.imencode(".png", image)[1].tobytes())
    source = {
        "transport_kind": "local-path",
        "local_path": str(path),
        "width": 160,
        "height": 120,
        "media_type": "image/png",
    }
    definition = NodeDefinition.model_validate(
        json.loads(
            Path(
                "custom_nodes/opencv_nodes/categories/geometry/workflow/catalog_sources/nodes/mapped_roi_crop.json"
            ).read_text("utf-8")
        )
    )
    values = {
        "image": source,
        "roi_items": {"value": [{"roi_id": "part-b", "bbox_xyxy": [20, 10, 60, 50]}]},
        "selected_ids": None,
        "transform": {
            "transform_kind": "rigid",
            "matrix_3x3": [[1, 0, 15], [0, 1, 20], [0, 0, 1]],
            "source_coordinate_space": "template-image-pixels",
            "target_coordinate_space": "source-image-pixels",
            "source_b_image": source,
            "match_count": 3,
            "inlier_count": 3,
            "inlier_match_ids": [],
        },
    }
    registry = ExecutionImageRegistry()
    req = WorkflowNodeExecutionRequest(
        node_id="crop",
        node_definition=definition,
        input_values=values,
        parameters={"interpolation": "nearest"},
        execution_metadata={"execution_image_registry": registry},
    )
    try:
        if dtype == np.uint16:
            with pytest.raises(InvalidRequestError, match="uint8"):
                handle_node(req)
            return
        output = handle_node(req)["crops"]["items"][0]
        np.testing.assert_array_equal(
            registry.read_matrix(output["image_handle"]), image[30:70, 35:75]
        )
        assert output["roi_id"] == "part-b" and "bbox_xyxy" not in output
        assert output["mapped_source"]["source_from_crop"] == [
            [1, 0, 35],
            [0, 1, 30],
            [0, 0, 1],
        ]
        for parameters in [{"maximum_total_pixels": 1599}, {"coordinate_scale": 2}]:
            with pytest.raises(InvalidRequestError):
                handle_node(replace(req, parameters=parameters))
        # 标准 ROI 端口可直接使用概览坐标，并显式换算到原图像素。
        roi = {
            "roi_id": "part-b",
            "roi_kind": "bbox",
            "bbox_xyxy": [10, 5, 30, 25],
            "polygon_xy": [[10, 5], [30, 5], [30, 25], [10, 25]],
            "area": 400,
        }
        roi_req = replace(
            req,
            input_values={**values, "roi_items": None, "roi": roi},
            parameters={"roi_coordinate_scale": 2, "interpolation": "nearest"},
        )
        full = handle_node(roi_req)["crops"]["items"][0]
        np.testing.assert_array_equal(
            registry.read_matrix(full["image_handle"]), image[30:70, 35:75]
        )
        with pytest.raises(InvalidRequestError):
            handle_node(replace(roi_req, input_values=values | {"roi": roi}))
        # 标准 ROI 列表一次裁剪，与逐个调用的像素、ID、坐标逐项完全一致。
        regions = [roi, roi | {"roi_id": "part-c", "bbox_xyxy": [15, 10, 35, 30]}]
        list_req = replace(
            roi_req, input_values=roi_req.input_values | {"roi": None, "rois": regions}
        )
        batch = handle_node(list_req)["crops"]["items"]
        for region, actual in zip(regions, batch, strict=True):
            single = handle_node(
                replace(roi_req, input_values=roi_req.input_values | {"roi": region})
            )["crops"]["items"][0]
            np.testing.assert_array_equal(
                registry.read_matrix(actual["image_handle"]),
                registry.read_matrix(single["image_handle"]),
            )
            assert actual["roi_id"] == single["roi_id"]
            assert actual["mapped_source"] == single["mapped_source"]
        empty = handle_node(
            replace(
                list_req,
                input_values=list_req.input_values | {"selected_ids": {"value": []}},
            )
        )
        assert empty["crops"]["count"] == 0
        with pytest.raises(InvalidRequestError):
            handle_node(
                replace(list_req, input_values=list_req.input_values | {"roi": roi})
            )
        # 工件图二次选择任意尺寸搜索框，原图变换应与两次裁剪逐像素一致。
        from custom_nodes.opencv_nodes.categories.basic.backend.nodes.crop_export import (
            handle_node as crop_export,
        )

        selection = roi | {
            "roi_id": "search",
            "bbox_xyxy": [3, 4, 23, 19],
            "polygon_xy": [[3, 4], [23, 4], [23, 19], [3, 19]],
            "area": 300,
        }
        cropped = crop_export(
            replace(
                req, parameters={}, input_values={"image": full, "rois": [selection]}
            )
        )["crops"]["items"][0]
        np.testing.assert_array_equal(
            registry.read_matrix(cropped["image_handle"]), image[34:49, 38:58]
        )
        np.testing.assert_allclose(
            cropped["mapped_source"]["source_from_crop"],
            [[1, 0, 38], [0, 1, 34], [0, 0, 1]],
        )
        # 直接采样局部窗口与先完整裁图再裁窗口逐像素相同，来源坐标也相同。
        for angle in (0, -3.7, 6.3):
            matrix = np.vstack((cv2.getRotationMatrix2D((60, 50), angle, 1), [0, 0, 1]))
            matrix[:2, 2] += [15.25, 20.125]
            for interpolation in ("nearest", "linear", "cubic"):
                transformed_req = replace(
                    roi_req,
                    parameters={
                        "roi_coordinate_scale": 2,
                        "interpolation": interpolation,
                    },
                    input_values=roi_req.input_values
                    | {
                        "transform": values["transform"]
                        | {"matrix_3x3": matrix.tolist()}
                    },
                )
                full = handle_node(transformed_req)["crops"]["items"][0]
                direct = handle_node(
                    replace(
                        transformed_req,
                        input_values=transformed_req.input_values
                        | {"window_roi": selection},
                    )
                )
                crop = direct["crops"]["items"][0]
                np.testing.assert_array_equal(
                    registry.read_matrix(crop["image_handle"]),
                    registry.read_matrix(full["image_handle"])[4:19, 3:23],
                )
                expected = np.asarray(
                    full["mapped_source"]["source_from_crop"]
                ) @ np.array([[1, 0, 3], [0, 1, 4], [0, 0, 1]])
                np.testing.assert_allclose(
                    crop["mapped_source"]["source_from_crop"], expected
                )
                assert crop["roi_id"] == "part-b"
                record = direct["summary"]["value"]["items"][0]
                assert record["parent_reference_bbox_xyxy"] == [20, 10, 60, 50]
                assert record["window_bbox_xyxy"] == [3, 4, 23, 19]
        for box in ([-1, 0, 2, 3], [0, 0, 41, 10], [1, 1, 1, 2]):
            with pytest.raises(InvalidRequestError):
                handle_node(
                    replace(
                        roi_req,
                        input_values=roi_req.input_values
                        | {"window_roi": selection | {"bbox_xyxy": box}},
                    )
                )
    finally:
        registry.clear()
