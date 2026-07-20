"""OpenCV 圆形候选精定位与质量评估共享实现。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True, slots=True)
class RadialEdgeSamples:
    """沿参考圆径向采样得到的亚像素边缘点。"""

    points_xy: Any
    edge_strengths: Any
    attempted_count: int
    accepted_count: int


@dataclass(frozen=True, slots=True)
class CircleFitResult:
    """robust circle fitting 的几何结果与诊断指标。"""

    center_x: float
    center_y: float
    radius: float
    fit_rmse_px: float
    max_residual_px: float
    arc_coverage: float
    ransac_inlier_count: int
    inlier_count: int
    sample_count: int


def _fit_weighted_algebraic_circle(points_xy: Any, weights: Any, *, np_module: Any) -> tuple[float, float, float]:
    """使用加权代数最小二乘拟合圆。"""

    if int(points_xy.shape[0]) < 3:
        raise InvalidRequestError("Circle fitting 至少需要 3 个有效边缘点")
    x_values = points_xy[:, 0].astype(np_module.float64, copy=False)
    y_values = points_xy[:, 1].astype(np_module.float64, copy=False)
    design = np_module.column_stack((2.0 * x_values, 2.0 * y_values, np_module.ones_like(x_values)))
    target = x_values * x_values + y_values * y_values
    sqrt_weights = np_module.sqrt(np_module.maximum(weights, 1e-9))
    solution, _, rank, _ = np_module.linalg.lstsq(
        design * sqrt_weights[:, None],
        target * sqrt_weights,
        rcond=None,
    )
    if int(rank) < 3:
        raise InvalidRequestError("Circle fitting 边缘点退化，无法得到稳定圆")
    center_x = float(solution[0])
    center_y = float(solution[1])
    radius_squared = float(solution[2]) + center_x * center_x + center_y * center_y
    if not math.isfinite(radius_squared) or radius_squared <= 0:
        raise InvalidRequestError("Circle fitting 得到无效半径")
    return center_x, center_y, math.sqrt(radius_squared)


def _circle_residuals(points_xy: Any, *, center_x: float, center_y: float, radius: float, np_module: Any) -> Any:
    """计算点到圆周的有符号径向残差。"""

    distances = np_module.hypot(points_xy[:, 0] - center_x, points_xy[:, 1] - center_y)
    return distances - radius


def _fit_circle_from_three_points(points_xy: Any, *, np_module: Any) -> tuple[float, float, float]:
    """从三个非共线点构造圆，供有界 RANSAC 初始化使用。"""

    point_a, point_b, point_c = points_xy.astype(np_module.float64, copy=False)
    ax, ay = float(point_a[0]), float(point_a[1])
    bx, by = float(point_b[0]), float(point_b[1])
    cx, cy = float(point_c[0]), float(point_c[1])
    denominator = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(denominator) <= 1e-9:
        raise InvalidRequestError("RANSAC 样本点共线，无法构造圆")
    center_x = (
        (ax * ax + ay * ay) * (by - cy)
        + (bx * bx + by * by) * (cy - ay)
        + (cx * cx + cy * cy) * (ay - by)
    ) / denominator
    center_y = (
        (ax * ax + ay * ay) * (cx - bx)
        + (bx * bx + by * by) * (ax - cx)
        + (cx * cx + cy * cy) * (bx - ax)
    ) / denominator
    radius = math.hypot(ax - center_x, ay - center_y)
    if not all(math.isfinite(value) for value in (center_x, center_y, radius)) or radius <= 0:
        raise InvalidRequestError("RANSAC 得到无效圆")
    return center_x, center_y, radius


def _select_ransac_inliers(
    points_xy: Any,
    *,
    np_module: Any,
    inlier_threshold_px: float,
    max_iterations: int,
) -> Any:
    """使用固定随机种子的有界 RANSAC 选择初始圆内点，保证结果可复现。"""

    sample_count = int(points_xy.shape[0])
    if sample_count < 3:
        raise InvalidRequestError("Circle RANSAC 至少需要 3 个有效边缘点")
    random_generator = np_module.random.default_rng(0)
    best_mask = None
    best_count = 0
    best_median_residual = math.inf
    for _ in range(max_iterations):
        sample_indices = random_generator.choice(sample_count, size=3, replace=False)
        try:
            center_x, center_y, radius = _fit_circle_from_three_points(
                points_xy[sample_indices],
                np_module=np_module,
            )
        except InvalidRequestError:
            continue
        absolute_residuals = np_module.abs(
            _circle_residuals(
                points_xy,
                center_x=center_x,
                center_y=center_y,
                radius=radius,
                np_module=np_module,
            )
        )
        inlier_mask = absolute_residuals <= inlier_threshold_px
        inlier_count = int(np_module.count_nonzero(inlier_mask))
        if inlier_count < 3:
            continue
        median_residual = float(np_module.median(absolute_residuals[inlier_mask]))
        if inlier_count > best_count or (
            inlier_count == best_count and median_residual < best_median_residual
        ):
            best_mask = inlier_mask
            best_count = inlier_count
            best_median_residual = median_residual
    if best_mask is None:
        raise InvalidRequestError("Circle RANSAC 未找到稳定初始圆")
    return best_mask


def _build_robust_weights(residuals: Any, *, loss: str, scale: float, np_module: Any) -> Any:
    """按 Huber 或 Tukey loss 生成迭代重加权系数。"""

    normalized = np_module.abs(residuals) / max(scale, 1e-6)
    if loss == "tukey":
        weights = np_module.square(np_module.maximum(0.0, 1.0 - np_module.square(normalized)))
        return weights
    return np_module.where(normalized <= 1.0, 1.0, 1.0 / np_module.maximum(normalized, 1e-6))


def _compute_arc_coverage(
    points_xy: Any,
    *,
    center_x: float,
    center_y: float,
    inlier_mask: Any,
    bin_count: int,
    np_module: Any,
) -> float:
    """按圆周角度分箱计算有效边缘覆盖率。"""

    inlier_points = points_xy[inlier_mask]
    if int(inlier_points.shape[0]) == 0:
        return 0.0
    angles = np_module.mod(
        np_module.arctan2(inlier_points[:, 1] - center_y, inlier_points[:, 0] - center_x),
        2.0 * math.pi,
    )
    bins = np_module.floor(angles / (2.0 * math.pi) * bin_count).astype(np_module.int32)
    bins = np_module.clip(bins, 0, bin_count - 1)
    return float(np_module.unique(bins).size) / float(bin_count)


def fit_circle_robust(
    points_xy: Any,
    *,
    np_module: Any,
    robust_loss: str = "huber",
    inlier_threshold_px: float = 2.0,
    ransac_iterations: int = 64,
    max_iterations: int = 12,
    arc_bin_count: int = 72,
) -> CircleFitResult:
    """使用有界 IRLS robust fitting 精定位圆，并返回可诊断质量指标。"""

    sample_count = int(points_xy.shape[0])
    if sample_count < 3:
        raise InvalidRequestError("Circle fitting 至少需要 3 个有效边缘点")
    if robust_loss not in {"huber", "tukey"}:
        raise InvalidRequestError("robust_loss 仅支持 huber、tukey")
    if inlier_threshold_px <= 0:
        raise InvalidRequestError("inlier_threshold_px 必须大于 0")
    if ransac_iterations < 1 or ransac_iterations > 256:
        raise InvalidRequestError("ransac_iterations 必须在 1 到 256 之间")
    if max_iterations < 1 or max_iterations > 100:
        raise InvalidRequestError("max_iterations 必须在 1 到 100 之间")
    if arc_bin_count < 8 or arc_bin_count > 720:
        raise InvalidRequestError("arc_bin_count 必须在 8 到 720 之间")

    ransac_inlier_mask = _select_ransac_inliers(
        points_xy,
        np_module=np_module,
        inlier_threshold_px=inlier_threshold_px,
        max_iterations=ransac_iterations,
    )
    ransac_inlier_count = int(np_module.count_nonzero(ransac_inlier_mask))
    weights = ransac_inlier_mask.astype(np_module.float64)
    center_x, center_y, radius = _fit_weighted_algebraic_circle(points_xy, weights, np_module=np_module)
    # 径向采样可能同时命中同一圆环的内外边缘。比较全体点模型和 RANSAC 模型，
    # 选择内点更多、残差中位数更小的初始化，避免局部圆弧偶然形成更偏的圆。
    global_center_x, global_center_y, global_radius = _fit_weighted_algebraic_circle(
        points_xy,
        np_module.ones(sample_count, dtype=np_module.float64),
        np_module=np_module,
    )
    ransac_residuals = np_module.abs(
        _circle_residuals(
            points_xy,
            center_x=center_x,
            center_y=center_y,
            radius=radius,
            np_module=np_module,
        )
    )
    global_residuals = np_module.abs(
        _circle_residuals(
            points_xy,
            center_x=global_center_x,
            center_y=global_center_y,
            radius=global_radius,
            np_module=np_module,
        )
    )
    ransac_consensus_count = int(np_module.count_nonzero(ransac_residuals <= inlier_threshold_px))
    global_consensus_count = int(np_module.count_nonzero(global_residuals <= inlier_threshold_px))
    if global_consensus_count > ransac_consensus_count or (
        global_consensus_count == ransac_consensus_count
        and float(np_module.median(global_residuals)) < float(np_module.median(ransac_residuals))
    ):
        center_x, center_y, radius = global_center_x, global_center_y, global_radius
    for _ in range(max_iterations):
        residuals = _circle_residuals(
            points_xy,
            center_x=center_x,
            center_y=center_y,
            radius=radius,
            np_module=np_module,
        )
        median_residual = float(np_module.median(residuals))
        mad = float(np_module.median(np_module.abs(residuals - median_residual)))
        scale = max(inlier_threshold_px, 1.4826 * mad)
        next_weights = _build_robust_weights(
            residuals,
            loss=robust_loss,
            scale=scale,
            np_module=np_module,
        )
        if int(np_module.count_nonzero(next_weights > 1e-6)) < 3:
            break
        next_center_x, next_center_y, next_radius = _fit_weighted_algebraic_circle(
            points_xy,
            next_weights,
            np_module=np_module,
        )
        delta = math.hypot(next_center_x - center_x, next_center_y - center_y) + abs(next_radius - radius)
        center_x, center_y, radius = next_center_x, next_center_y, next_radius
        weights = next_weights
        if delta < 1e-4:
            break

    residuals = _circle_residuals(
        points_xy,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        np_module=np_module,
    )
    absolute_residuals = np_module.abs(residuals)
    inlier_mask = absolute_residuals <= inlier_threshold_px
    inlier_count = int(np_module.count_nonzero(inlier_mask))
    if inlier_count < 3:
        raise InvalidRequestError("Circle fitting 有效内点不足")
    inlier_residuals = residuals[inlier_mask]
    fit_rmse_px = float(np_module.sqrt(np_module.mean(np_module.square(inlier_residuals))))
    max_residual_px = float(np_module.max(np_module.abs(inlier_residuals)))
    arc_coverage = _compute_arc_coverage(
        points_xy,
        center_x=center_x,
        center_y=center_y,
        inlier_mask=inlier_mask,
        bin_count=arc_bin_count,
        np_module=np_module,
    )
    return CircleFitResult(
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        fit_rmse_px=fit_rmse_px,
        max_residual_px=max_residual_px,
        arc_coverage=arc_coverage,
        ransac_inlier_count=ransac_inlier_count,
        inlier_count=inlier_count,
        sample_count=sample_count,
    )


def sample_radial_edges(
    image_matrix: Any,
    *,
    center_x: float,
    center_y: float,
    reference_radius_px: float,
    radius_tolerance_px: float,
    sample_count: int,
    gradient_threshold: float,
    edge_polarity: str,
    cv2_module: Any,
    np_module: Any,
) -> RadialEdgeSamples:
    """在参考圆周两侧建立径向 profile，并提取亚像素边缘点。"""

    if reference_radius_px <= 0:
        raise InvalidRequestError("reference_radius_px 必须大于 0")
    if radius_tolerance_px <= 0:
        raise InvalidRequestError("radius_tolerance_px 必须大于 0")
    if sample_count < 12 or sample_count > 720:
        raise InvalidRequestError("sample_count 必须在 12 到 720 之间")
    if gradient_threshold < 0:
        raise InvalidRequestError("gradient_threshold 不能小于 0")
    if edge_polarity not in {"any", "dark-to-bright", "bright-to-dark"}:
        raise InvalidRequestError("edge_polarity 仅支持 any、dark-to-bright、bright-to-dark")

    radial_start = max(0.5, reference_radius_px - radius_tolerance_px)
    radial_end = reference_radius_px + radius_tolerance_px
    radial_sample_count = max(5, min(1024, int(math.ceil(radial_end - radial_start)) + 1))
    angles = np_module.linspace(0.0, 2.0 * math.pi, sample_count, endpoint=False, dtype=np_module.float32)
    radii = np_module.linspace(radial_start, radial_end, radial_sample_count, dtype=np_module.float32)
    cos_values = np_module.cos(angles)[:, None]
    sin_values = np_module.sin(angles)[:, None]
    map_x = center_x + cos_values * radii[None, :]
    map_y = center_y + sin_values * radii[None, :]
    image_height, image_width = [int(value) for value in image_matrix.shape[:2]]
    valid_profiles = (
        (np_module.min(map_x, axis=1) >= 0.0)
        & (np_module.max(map_x, axis=1) <= float(image_width - 1))
        & (np_module.min(map_y, axis=1) >= 0.0)
        & (np_module.max(map_y, axis=1) <= float(image_height - 1))
    )
    profiles = cv2_module.remap(
        image_matrix,
        map_x.astype(np_module.float32),
        map_y.astype(np_module.float32),
        interpolation=cv2_module.INTER_LINEAR,
        borderMode=cv2_module.BORDER_REPLICATE,
    ).astype(np_module.float32, copy=False)
    gradients = np_module.diff(profiles, axis=1)
    if edge_polarity == "dark-to-bright":
        scores = np_module.maximum(gradients, 0.0)
    elif edge_polarity == "bright-to-dark":
        scores = np_module.maximum(-gradients, 0.0)
    else:
        scores = np_module.abs(gradients)

    points: list[list[float]] = []
    strengths: list[float] = []
    radial_step = float(radial_end - radial_start) / float(max(1, radial_sample_count - 1))
    for angle_index in range(sample_count):
        if not bool(valid_profiles[angle_index]):
            continue
        row_scores = scores[angle_index]
        peak_index = int(np_module.argmax(row_scores))
        peak_strength = float(row_scores[peak_index])
        if peak_strength < gradient_threshold:
            continue
        refined_index = float(peak_index)
        if 0 < peak_index < int(row_scores.size) - 1:
            left_value = float(row_scores[peak_index - 1])
            center_value = peak_strength
            right_value = float(row_scores[peak_index + 1])
            denominator = left_value - 2.0 * center_value + right_value
            if abs(denominator) > 1e-9:
                refined_index += max(-0.5, min(0.5, 0.5 * (left_value - right_value) / denominator))
        edge_radius = radial_start + (refined_index + 0.5) * radial_step
        points.append(
            [
                center_x + math.cos(float(angles[angle_index])) * edge_radius,
                center_y + math.sin(float(angles[angle_index])) * edge_radius,
            ]
        )
        strengths.append(peak_strength)
    return RadialEdgeSamples(
        points_xy=np_module.asarray(points, dtype=np_module.float64).reshape((-1, 2)),
        edge_strengths=np_module.asarray(strengths, dtype=np_module.float64),
        attempted_count=sample_count,
        accepted_count=len(points),
    )
