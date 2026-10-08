"""平面坐标映射、有限边缘截面和控制点标定的通用计算。"""

import cv2
import numpy as np

from backend.contracts.workflows.metrology import PlanarCalibration


def map_points(points, matrix) -> np.ndarray:
    """映射点后再计算几何；不把像素长度乘任意比例冒充物理值。"""
    values = np.asarray(points, dtype=np.float64)
    transform = np.asarray(matrix, dtype=np.float64)
    if (
        values.ndim != 2
        or values.shape[1] != 2
        or transform.shape != (3, 3)
        or not np.isfinite(values).all()
        or not np.isfinite(transform).all()
    ):
        raise ValueError("坐标或变换无效")
    result = np.column_stack((values, np.ones(len(values)))) @ transform.T
    if np.any(np.abs(result[:, 2]) < 1e-10):
        raise ValueError("点位于投影无穷远")
    mapped = result[:, :2] / result[:, 2, None]
    if not np.isfinite(mapped).all():
        raise ValueError("映射坐标溢出")
    return mapped


def measure_section(points, direction, section: float) -> np.ndarray | None:
    """在有限折线上求指定截面交点；越界不外推，多交点无效。"""
    values = np.asarray(points, dtype=np.float64)
    axis = np.asarray(direction, dtype=np.float64)
    if (
        values.ndim != 2
        or values.shape[1] != 2
        or len(values) < 2
        or not np.isfinite(values).all()
        or axis.shape != (2,)
        or not np.isfinite(axis).all()
        or abs(np.linalg.norm(axis) - 1) > 1e-6
        or not np.isfinite(section)
    ):
        raise ValueError("截面定义或有限边缘无效")
    normal = np.array([-axis[1], axis[0]])
    projections = values @ normal
    intersections = []
    for a, b, pa, pb in zip(values, values[1:], projections, projections[1:]):
        if abs(pb - pa) < 1e-10:
            if abs(section - pa) < 1e-8:
                return None
            continue
        t = (section - pa) / (pb - pa)
        if -1e-8 <= t <= 1 + 1e-8:
            point = a + np.clip(t, 0, 1) * (b - a)
            if not any(np.linalg.norm(point - other) < 1e-7 for other in intersections):
                intersections.append(point)
    return intersections[0] if len(intersections) == 1 else None


def calibrated_points(points, calibration: PlanarCalibration) -> np.ndarray:
    """只映射标定凸有效域内的实测点；越界不外推、不返回名义值。"""
    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 2 or not np.isfinite(values).all():
        raise ValueError("invalid_measurement_points")
    polygon = np.asarray(calibration.valid_polygon)
    edges = np.roll(polygon, -1, axis=0) - polygon
    relative = values[:, None, :] - polygon[None, :, :]
    cross = (
        edges[None, :, 0] * relative[:, :, 1] - edges[None, :, 1] * relative[:, :, 0]
    )
    if not np.all(np.all(cross >= -1e-8, axis=1) | np.all(cross <= 1e-8, axis=1)):
        raise ValueError("outside_calibration_area")
    try:
        return map_points(values, calibration.world_from_image)
    except ValueError as exc:
        raise ValueError("invalid_calibration_projection") from exc


def map_unit_direction(point, direction, matrix) -> np.ndarray:
    """用投影变换的解析 Jacobian 映射局部方向，不依赖差分步长或域外辅助点。"""
    point, direction, matrix = (
        np.asarray(point, dtype=float),
        np.asarray(direction, dtype=float),
        np.asarray(matrix, dtype=float),
    )
    if (
        point.shape != (2,)
        or direction.shape != (2,)
        or matrix.shape != (3, 3)
        or not all(np.isfinite(a).all() for a in (point, direction, matrix))
    ):
        raise ValueError("invalid_measurement_axis")
    projected = matrix @ np.r_[point, 1.0]
    if abs(projected[2]) < 1e-10:
        raise ValueError("degenerate_measurement_axis")
    tangent = matrix[:, :2] @ direction
    mapped = (tangent[:2] * projected[2] - projected[:2] * tangent[2]) / projected[
        2
    ] ** 2
    length = np.linalg.norm(mapped)
    if not np.isfinite(length) or length < 1e-12:
        raise ValueError("degenerate_measurement_axis")
    return mapped / length


def fit_planar_calibration(
    image_points,
    world_points,
    validation_image_points,
    validation_world_points,
    *,
    model: str,
    image_size,
    unit="millimeter",
    plane_id="plane",
) -> PlanarCalibration:
    """使用控制点求解平面映射，以独立控制点验证；不宣称实际仪器精度。"""
    image = np.asarray(image_points, dtype=np.float64)
    world = np.asarray(world_points, dtype=np.float64)
    valid_image = np.asarray(validation_image_points, dtype=np.float64)
    valid_world = np.asarray(validation_world_points, dtype=np.float64)
    minimum = {"similarity": 3, "affine": 3, "homography": 4}.get(model)
    if (
        minimum is None
        or image.shape != world.shape
        or image.ndim != 2
        or image.shape[1] != 2
        or not minimum <= len(image) <= 4096
    ):
        raise ValueError("标定控制点数量或形状无效")
    if (
        valid_image.ndim != 2
        or valid_image.shape != valid_world.shape
        or valid_image.shape[1] != 2
        or not 2 <= len(valid_image) <= 4096
    ):
        raise ValueError("至少提供两个独立验证点")
    if not all(np.isfinite(x).all() for x in (image, world, valid_image, valid_world)):
        raise ValueError("标定点必须是有限数值")
    if len(np.unique(valid_image, axis=0)) != len(valid_image) or len(
        np.unique(valid_world, axis=0)
    ) != len(valid_world):
        raise ValueError("独立验证点不能重复")
    # 每次只比较一个验证点，避免 Python 双重循环及 N×M×2 临时数组。
    if any(np.min(np.linalg.norm(image - q, axis=1)) < 1e-8 for q in valid_image):
        raise ValueError("验证点不能重复拟合控制点")
    for points in (image, world):
        if len(np.unique(points, axis=0)) != len(points):
            raise ValueError("标定控制点重复")
        if np.linalg.matrix_rank(np.column_stack((points, np.ones(len(points))))) < 3:
            raise ValueError("标定点共线或重复")
    if model == "homography":
        matrix, _ = cv2.findHomography(image, world, method=0)
        if matrix is None:
            raise ValueError("平面投影求解失败")
    elif model == "affine":
        matrix = np.eye(3)
        matrix[:2] = np.linalg.lstsq(
            np.column_stack((image, np.ones(len(image)))), world, rcond=None
        )[0].T
    else:
        design = np.zeros((len(image) * 2, 4))
        design[::2] = np.column_stack(
            (image[:, 0], -image[:, 1], np.ones(len(image)), np.zeros(len(image)))
        )
        design[1::2] = np.column_stack(
            (image[:, 1], image[:, 0], np.zeros(len(image)), np.ones(len(image)))
        )
        a, b, tx, ty = np.linalg.lstsq(design, world.reshape(-1), rcond=None)[0]
        matrix = np.array([[a, -b, tx], [b, a, ty], [0, 0, 1]])
    hull = cv2.convexHull(image.astype(np.float32)).reshape(-1, 2)
    if any(cv2.pointPolygonTest(hull, tuple(p), False) < 0 for p in valid_image):
        raise ValueError("验证点必须位于标定控制点覆盖区")
    fit_errors = np.linalg.norm(map_points(image, matrix) - world, axis=1)
    errors = np.linalg.norm(map_points(valid_image, matrix) - valid_world, axis=1)
    return PlanarCalibration(
        image_width=image_size[0],
        image_height=image_size[1],
        model=model,
        world_from_image=matrix.tolist(),
        unit=unit,
        plane_id=plane_id,
        valid_polygon=hull.tolist(),
        fit_rms=float(np.sqrt(np.mean(fit_errors**2))),
        validation_max_error=float(errors.max()),
        evidence={
            "control_points": [
                {"image": a.tolist(), "world": b.tolist()} for a, b in zip(image, world)
            ],
            "validation_points": [
                {"image": a.tolist(), "world": b.tolist()}
                for a, b in zip(valid_image, valid_world)
            ],
        },
    )
