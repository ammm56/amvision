"""用 3913 正面实图验证通用圆心配准；产品坐标仅存放于开发验证配方。"""

import json
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from backend.contracts.workflows.workflow_graph import NodeDefinition
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.hough_circles import (
    handle_node as hough,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.circle_pattern_locate import (
    handle_node as locate,
)
from scripts.configure_linescan_3913_workflow import DATA

OUT = DATA / "validation/front-registered"


def definition(category, filename):
    """从实际 catalog 源读取本次节点定义。"""
    path = Path(
        f"custom_nodes/opencv_nodes/categories/{category}/workflow/catalog_sources/nodes/{filename}.json"
    )
    return NodeDefinition.model_validate(json.loads(path.read_text("utf-8")))


def request(category, filename, values, parameters):
    """构建实际处理器请求，不模拟视觉算法。"""
    return WorkflowNodeExecutionRequest(
        node_id=filename,
        node_definition=definition(category, filename),
        input_values=values,
        parameters=parameters,
    )


def image_ref(path):
    """验证图尺寸固定为原图的 1/8，维持等比像素关系。"""
    return {
        "transport_kind": "local-path",
        "local_path": str(path.resolve()),
        "width": 2500,
        "height": 2048,
        "media_type": "image/png",
    }


def build_recipe():
    """冻结经过人工核对的六行托盘圆和十八个工件区域；运行时不按排序关联。"""
    circles = json.loads((OUT / "hough-reference.json").read_text("utf-8"))["circles"][
        "items"
    ]
    points = []
    for row, y in enumerate([230, 450, 725, 950, 1225, 1455], 1):
        row_circles = sorted(
            [c for c in circles if abs(c["center_xy"][1] - y) < 30],
            key=lambda c: c["center_xy"][0],
        )
        for col, circle in enumerate(row_circles, 1):
            points.append(
                {
                    "point_id": f"anchor-r{row:02}-c{col:02}",
                    "center_xy": circle["center_xy"],
                }
            )
    inspection, codes = [], []
    code_centers = [
        [(382, 355), (723, 352), (1067, 348), (1410, 345), (1753, 342), (2096, 338)],
        [(386, 847), (729, 846), (1070, 842), (1413, 837), (1758, 834), (2100, 831)],
        [
            (389, 1345),
            (731, 1342),
            (1076, 1339),
            (1418, 1336),
            (1761, 1332),
            (2104, 1329),
        ],
    ]
    for row in range(3):
        for col in range(6):
            name = f"slot-r{row + 1:02}-c{col + 1:02}"
            # 参考托盘在图内有轻微倾角；比较域沿参考槽位变化，不能跨入上一行 PCB。
            x, y = 343 * col + 4 * row, 500 * row - 3 * col
            polygon = [
                [190 + x, 155 + y],
                [530 + x, 155 + y],
                [530 + x, 410 + y],
                [430 + x, 410 + y],
                [430 + x, 665 + y],
                [105 + x, 665 + y],
                [105 + x, 410 + y],
                [190 + x, 410 + y],
            ]
            inspection.append(
                {
                    "roi_id": name,
                    "roi_kind": "polygon",
                    "polygon_xy": polygon,
                    "bbox_xyxy": [105 + x, 155 + y, 530 + x, 665 + y],
                    "area": int(cv2.contourArea(np.asarray(polygon, np.float32))),
                }
            )
            cx, cy = code_centers[row][col]
            cx, cy = round(8 * cx + 3.5), round(8 * cy + 3.5)
            codes.append(
                {"roi_id": name, "bbox_xyxy": [cx - 500, cy - 500, cx + 500, cy + 500]}
            )
    recipe = {
        "face": "front",
        "source_image_size": [20000, 16384],
        "overview_size": [2500, 2048],
        "coordinate_scale": 8,
        "reference_path": str((OUT / "reference.png").resolve()),
        "hough": json.loads((OUT / "hough-parameters.json").read_text()),
        "localization": {
            "reference_points": points,
            "match_tolerance_px": 8,
            "maximum_rmse_px": 2,
            "minimum_match_ratio": 0.8,
            "maximum_angle_degrees": 10,
            "maximum_translation_px": 500,
            "maximum_hypotheses": 5000,
        },
        "inspection_rois": inspection,
        "barcode_rois": codes,
    }
    (OUT / "recipe.json").write_text(
        json.dumps(recipe, ensure_ascii=False, indent=2), "utf-8"
    )
    return recipe


def main():
    """先验证真实图，再验证已知平移/旋转；这是定位测试，不是生产精度认证。"""
    recipe = build_recipe()
    image = cv2.imdecode(np.fromfile(OUT / "reference.png", np.uint8), cv2.IMREAD_COLOR)
    records = []
    for name, angle, tx, ty in [
        ("original", 0, 0, 0),
        ("shift", 0, 60, 35),
        ("rotate", 2, 20, 10),
        ("rotate-negative", -2, 30, -25),
    ]:
        truth = np.eye(3)
        truth[:2] = cv2.getRotationMatrix2D((1250, 1024), angle, 1)
        truth[:2, 2] += [tx, ty]
        current = cv2.warpAffine(image, truth[:2], (2500, 2048))
        path = OUT / f"localization-{name}.png"
        cv2.imencode(".png", current)[1].tofile(path)
        started = perf_counter()
        detected = hough(
            request(
                "shape", "hough_circles", {"image": image_ref(path)}, recipe["hough"]
            )
        )
        found = locate(
            request(
                "matching",
                "circle_pattern_locate",
                {"circles": detected["circles"]},
                recipe["localization"],
            )
        )
        matrix = np.asarray(found["transform"]["matrix_3x3"])
        points = np.asarray(
            [p["center_xy"] + [1] for p in recipe["localization"]["reference_points"]]
        )
        error = float(
            np.max(
                np.linalg.norm((points @ matrix.T - points @ truth.T)[:, :2], axis=1)
            )
        )
        record = {
            "case": name,
            "seconds": perf_counter() - started,
            "maximum_anchor_error_px": error,
            **found["summary"]["value"],
        }
        records.append(record)
        assert error < 2, record
        overlay = current.copy()
        for match in record["matches"]:
            x, y = map(round, match["observed_xy"])
            cv2.circle(overlay, (x, y), 32, (0, 200, 0), 2)
            cv2.putText(
                overlay,
                match["point_id"],
                (x - 45, y - 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (0, 200, 0),
                1,
            )
        for region in recipe["inspection_rois"]:
            poly = np.asarray(region["polygon_xy"], np.float32).reshape(-1, 1, 2)
            mapped = cv2.perspectiveTransform(poly, matrix)
            cv2.polylines(overlay, [np.int32(mapped)], True, (255, 180, 0), 2)
            x, y = map(int, mapped[0, 0])
            cv2.putText(
                overlay,
                region["roi_id"],
                (x, y + 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255),
                1,
            )
        cv2.imencode(".jpg", overlay)[1].tofile(
            OUT / f"localization-{name}-overlay.jpg"
        )
        print(
            name,
            record["matched_count"],
            "error",
            round(error, 3),
            "seconds",
            round(record["seconds"], 3),
            flush=True,
        )
    (OUT / "localization-report.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), "utf-8"
    )


if __name__ == "__main__":
    main()
