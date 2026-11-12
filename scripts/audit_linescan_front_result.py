"""独立复算真实 Runtime 返回坐标，并在直接缩放的原图上绘制核对图。"""

import json
import math

import numpy as np
from PIL import Image, ImageDraw

from scripts.configure_linescan_front_result import DATA, OUT


def project(points, matrix):
    """使用独立 NumPy 运算投影，不调用待验证的 ROI 节点处理器。"""
    points = np.asarray(points, dtype=float)
    homogeneous = np.column_stack((points, np.ones(len(points))))
    mapped = homogeneous @ np.asarray(matrix, dtype=float).T
    return mapped[:, :2] / mapped[:, 2:]


def validate_coordinates(result, diagnostic):
    """按 item_id 核对所有槽位与条码坐标，覆盖两条不同来源的坐标链。"""
    placement = {v["item_id"]: v for v in diagnostic["placement_2d"]["items"]}
    barcodes = {v["item_id"]: v for v in diagnostic["barcodes"]}
    summary = diagnostic["tray_localization"]
    angle = math.radians(summary["angle_degrees"])
    dx, dy = summary["translation_xy"]
    transform = [
        [math.cos(angle), -math.sin(angle), dx],
        [math.sin(angle), math.cos(angle), dy],
        [0, 0, 1],
    ]
    source_size = diagnostic["recipe_source_image_size"]
    sx, sy = np.asarray(result["image_size"]) / np.asarray(source_size)
    resize = [[sx, 0, (sx - 1) / 2], [0, sy, (sy - 1) / 2], [0, 0, 1]]
    errors = []

    def check_geometry(actual, polygon):
        """保留浮点误差度量，不能把明显错位隐藏在整数舍入中。"""
        bbox = [*polygon.min(axis=0), *polygon.max(axis=0)]
        errors.append(float(np.max(np.abs(np.asarray(actual["polygon_xy"]) - polygon))))
        errors.append(float(np.max(np.abs(np.asarray(actual["bbox_xyxy"]) - bbox))))

    for item in result["items"]:
        item_id = item["item_id"]
        source_roi = placement[item_id]["source"]
        check_geometry(
            item["placement"]["roi"], project(source_roi["polygon_xy"], transform)
        )
        barcode = barcodes.get(item_id)
        if barcode is None:
            assert item["barcode"]["detections"] == []
            continue
        assert len(item["barcode"]["detections"]) == len(barcode["detections"])
        for actual, detection in zip(
            item["barcode"]["detections"], barcode["detections"], strict=True
        ):
            x1, y1, x2, y2 = detection["bbox_xyxy"]
            polygon = project(
                [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                np.asarray(resize) @ np.asarray(barcode["source"]["source_from_crop"]),
            )
            check_geometry(actual, polygon)
    maximum = max(errors, default=0)
    assert maximum < 0.0002, maximum
    return maximum


def main():
    """审计已有真实结果，不重新执行模型；所有产物写入独立验证目录。"""
    OUT.mkdir(parents=True, exist_ok=True)
    verification = {}
    for case in ("normal", "missing"):
        path = DATA / f"validation/front-performance/final-result-{case}/report.json"
        report = json.loads(path.read_text("utf-8"))
        assert report["cleanup"]["runtime_deleted"]
        assert report["cleanup"]["application_deleted"]
        for run in report["runs"]:
            outputs = run["response"]["outputs"]
            result, diagnostic = (
                outputs["report"]["value"],
                outputs["audit_report"]["value"],
            )
            maximum = validate_coordinates(result, diagnostic)
        (OUT / f"result-{case}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), "utf-8"
        )
        bad_ids = [
            item["item_id"] for item in result["items"] if item["result"] == "NG"
        ]
        assert bad_ids == ([] if case == "normal" else ["slot-02-03"])
        verification[case] = {
            "count": result["count"],
            "result": result["result"],
            "ng_item_ids": bad_ids,
            "maximum_coordinate_error_pixels": maximum,
            "elapsed_ms": [run["elapsed_ms"] for run in report["runs"]],
            "temporary_resources_deleted": True,
        }
    result = json.loads((OUT / "result-normal.json").read_text("utf-8"))
    # 仅缩放原始 BMP，不执行托盘配准；直接使用最终 JSON 中的返回坐标绘制。
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(DATA / "3913正面大图.bmp") as source:
        image = source.resize(
            tuple(result["image_size"]), Image.Resampling.BILINEAR
        ).convert("RGB")
    draw = ImageDraw.Draw(image)
    for item in result["items"]:
        roi = item["placement"]["roi"]
        polygon = [tuple(point) for point in roi["polygon_xy"]]
        draw.line([*polygon, polygon[0]], fill="#00d992", width=2)
        draw.text(
            tuple(roi["bbox_xyxy"][:2]), item["item_id"], fill="#00d992", font_size=18
        )
        for detection in item["barcode"]["detections"]:
            draw.rectangle(detection["bbox_xyxy"], outline="#ffab00", width=2)
    image.save(OUT / "returned-coordinates-2500x2048.png")
    (OUT / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2), "utf-8"
    )
    print(json.dumps(verification, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
