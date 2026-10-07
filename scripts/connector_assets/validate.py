"""独立检查开发资源的文件、几何投影、图像边缘和标定；不导入生成器或节点算法。"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


def read_json(path: Path) -> dict:
    """读取 UTF-8 JSON 文档。"""
    return json.loads(path.read_text(encoding="utf-8"))


def project_independently(points: list, camera: dict) -> np.ndarray:
    """以 NumPy 解析投影交叉检查 Blender 投影，所有输入世界点单位为毫米。"""
    xyz = np.asarray(points, dtype=np.float64)
    if camera["model"] == "orthographic":
        scale = camera["pixels_per_mm"]
    else:
        scale = camera["focal_px"] / (camera["camera_world_mm"][2] - xyz[:, 2])
        scale = scale[:, None]
    uv = xyz[:, :2] * np.asarray([1, -1]) * scale
    return uv + camera["principal_point_px"]


def inspect_reference_edges(image: np.ndarray, truth: dict) -> float:
    """从实际渲染像素提取金属截面，核对边缘宽度而非只比较两个 JSON 字段。"""
    differences = []
    for pin in truth["pins"]:
        if not pin["actual_present"]:
            continue
        x, y = pin["center_image_px"]
        iy = int(round(y))
        start, stop = int(round(x)) - 22, int(round(x)) + 23
        strip = image[iy - 1:iy + 2, start:stop].astype(np.float32).mean(axis=0)
        gold = (strip[:, 2] - strip[:, 0] > 20) & (strip[:, 2] > strip[:, 1] * 1.15)
        positions = np.flatnonzero(gold)
        if len(positions) < 3 or np.any(np.diff(positions) > 1):
            raise ValueError(f"Reference pin not resolved in pixels: {pin['pin_id']}")
        measured = positions[-1] - positions[0] + 1
        ends = np.asarray(pin["width_endpoints_image_px"])
        expected = float(np.linalg.norm(ends[1] - ends[0]))
        differences.append(abs(measured - expected))
    error = max(differences)
    if error > 2.0:
        raise ValueError(f"Rendered pin width inconsistent with geometry: {error} px")
    return error


def write_gallery(root: Path, manifest: dict) -> None:
    """生成离线资源索引，原图和真值均可直接打开，不修改任何输入图像。"""
    cards = []
    for sample in manifest["samples"]:
        title = html.escape(sample["id"])
        state = html.escape(sample.get("expected_state", "calibration"))
        image = html.escape(sample["image"], quote=True)
        truth = html.escape(sample["truth"], quote=True)
        cards.append(f'<article><a href="{image}"><img loading="lazy" src="{image}" alt="{title}"></a><h2>{title}</h2><p>{state} · {sample["split"]} · <a href="{truth}">JSON truth</a></p></article>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connector engineering assets</title><style>
body{font-family:system-ui,sans-serif;margin:28px;color:#dfe5e7;background:#181c20}h1{font-size:24px}p{line-height:1.6}a{color:#82d4bf}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:20px}article{background:#252b30;border:1px solid #424a50;padding:12px}img{width:100%;display:block}h2{font-size:14px;overflow-wrap:anywhere}article p{font-size:13px}
</style><h1>连接器开发资源 · 合成样本</h1><p>单排正视 / 双排顶视 / 标定棋盘。图片不包含文字标注。点击查看原图或 JSON 真值。<br>这些是 Blender 理想几何样本，用于开发验证；不是实物测量报告，也不是现场精度验收结果。</p><main>'''
    (root / "gallery.html").write_text(page + "".join(cards) + "</main></html>", encoding="utf-8")


def validate(root: Path) -> dict:
    """校验完整数据包，任一失败立即报错，防止不完整资源被标为可用。"""
    manifest = read_json(root / "manifest.json")
    if not manifest["synthetic"] or manifest["real_metrology_reference"]:
        raise ValueError("Synthetic provenance missing")
    ids = [item["id"] for item in manifest["samples"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate sample IDs")
    errors = []
    edge_errors = []
    object_points, image_points = [], []
    corner_errors = []
    known_camera = None
    invalid_cases = {"no_part", "two_parts", "cropped"}
    ng_cases = {"missing_first", "missing_middle", "missing_last", "offset", "narrow", "wide", "width_outside_limit", "empty_occupied", "extra_pin"}
    for sample in manifest["samples"]:
        for key in ("image", "truth"):
            path = (root / sample[key]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Asset path escapes dataset")
            if hashlib.sha256(path.read_bytes()).hexdigest() != sample[key + "_sha256"]:
                raise ValueError(f"Hash mismatch: {path}")
        image = cv2.imdecode(np.fromfile(root / sample["image"], dtype=np.uint8), cv2.IMREAD_COLOR)
        truth = read_json(root / sample["truth"])
        camera = truth["camera"]
        if image is None or image.shape != (camera["height"], camera["width"], 3):
            raise ValueError(f"Image decode/shape failed: {sample['id']}")
        if image.std() < 2 and "no_part" not in sample["id"]:
            raise ValueError(f"Blank image: {sample['id']}")
        if sample["split"] == "calibration":
            expected = np.asarray(truth["corners_image_px"])
            actual = project_independently(truth["corners_world_mm"], camera)
            errors.append(float(np.max(np.linalg.norm(expected - actual, axis=1))))
            pattern = tuple(truth["pattern_size"])
            found, corners = cv2.findChessboardCornersSB(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), pattern)
            if not found:
                raise ValueError(f"Calibration corners not detected: {sample['id']}")
            distances = np.linalg.norm(corners[:, 0, None, :] - expected[None, :, :], axis=2)
            matches = distances.argmin(axis=1)
            if len(set(matches)) != len(expected):
                raise ValueError("Calibration corner association not one-to-one")
            corner_errors.append(float(distances.min(axis=1).max()))
            grid = np.zeros((pattern[0] * pattern[1], 3), dtype=np.float32)
            grid[:, :2] = np.mgrid[:pattern[0], :pattern[1]].T.reshape(-1, 2) * truth["square_size_mm"]
            object_points.append(grid)
            image_points.append(corners)
            known_camera = camera
            continue
        condition = truth["condition"]["id"]
        required_state = "invalid" if condition in invalid_cases else "ng" if condition in ng_cases else "ok"
        if truth["expected"]["state"] != required_state:
            raise ValueError(f"Wrong rule oracle: {sample['id']}")
        family = truth["family"]
        if len(truth["pins"]) != family["rows"] * family["columns"]:
            raise ValueError("Nominal identity lost on missing PIN")
        pin_ids = [pin["pin_id"] for pin in truth["pins"]]
        if len(pin_ids) != len(set(pin_ids)):
            raise ValueError("Duplicate PIN IDs")
        homography = np.asarray(truth["image_from_measurement_plane"])
        for pin in truth["pins"]:
            if not pin["actual_present"]:
                if pin["width_mm"] is not None:
                    raise ValueError("Missing PIN contains measurement")
                continue
            expected = np.asarray(pin["width_endpoints_image_px"])
            actual = project_independently(pin["width_endpoints_world_mm"], camera)
            errors.append(float(np.max(np.linalg.norm(expected - actual, axis=1))))
            local = np.array([*pin["actual_center_local_mm"][:2], 1])
            mapped = homography @ local
            errors.append(float(np.linalg.norm(mapped[:2] / mapped[2] - pin["center_image_px"])))
        if condition == "reference":
            edge_errors.append(inspect_reference_edges(image, truth))
    if max(errors) > 0.005:
        raise ValueError(f"Coordinate projection mismatch: {max(errors)}")
    report = {"status": "passed", "sample_count": len(ids), "splits": dict(Counter(s["split"] for s in manifest["samples"])),
              "max_projection_difference_px": max(errors), "max_reference_width_difference_px": max(edge_errors),
              "scope": "Resource integrity, independent projection, rendered reference width and ideal camera calibration only; not production-node or real-metrology acceptance."}
    if object_points:
        flags = cv2.CALIB_ZERO_TANGENT_DIST | cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2 | cv2.CALIB_FIX_K3
        rms, intrinsic, _, _, _ = cv2.calibrateCamera(object_points, image_points, (known_camera["width"], known_camera["height"]), None, None, flags=flags)
        focal_error = max(abs(intrinsic[0, 0] / known_camera["focal_px"] - 1), abs(intrinsic[1, 1] / known_camera["focal_px"] - 1))
        principal_error = float(np.linalg.norm(intrinsic[:2, 2] - known_camera["principal_point_px"]))
        report["calibration"] = {"views_detected": len(object_points), "rms_px": rms, "max_corner_error_px": max(corner_errors),
                                 "estimated_intrinsic": intrinsic.tolist(), "max_focal_relative_error": focal_error,
                                 "principal_point_error_px": principal_error, "distortion_fixed_to_known_zero": True}
        if rms > 0.5 or max(corner_errors) > 1 or focal_error > 0.02 or principal_error > 3:
            raise ValueError(f"Calibration fixture inconsistent: {report['calibration']}")
    (root / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_gallery(root, manifest)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.dataset.resolve()), indent=2))
