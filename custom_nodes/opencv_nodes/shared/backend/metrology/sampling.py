"""有预算、位深保真的扫描带边缘对提取；全部坐标为原图像素。"""

from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np


@dataclass(frozen=True)
class EdgePairSettings:
    """通用扫描参数：长度、宽度、步距、梯度阈值和有效覆盖。"""

    search_length: float = 48.0
    band_width: float = 8.0
    scan_lines: int = 9
    sample_step: float = 0.5
    polarity: str = "bright"
    gradient_threshold: float = 0.03
    min_width: float = 2.0
    max_width: float = 40.0
    min_coverage: float = 0.7
    max_residual: float = 1.0

    def validate(self) -> None:
        """数组级调用也检查边界，不能依赖节点表单限制。"""
        numeric = (
            self.search_length,
            self.band_width,
            self.sample_step,
            self.gradient_threshold,
            self.min_width,
            self.max_width,
            self.min_coverage,
            self.max_residual,
        )
        if any(isinstance(x, bool) or not math.isfinite(x) for x in numeric):
            raise ValueError("扫描参数必须为有限数值")
        if not (
            4 <= self.search_length <= 2048
            and 1 <= self.band_width <= 256
            and type(self.scan_lines) is int
            and 3 <= self.scan_lines <= 65
            and 0.25 <= self.sample_step <= 2
        ):
            raise ValueError("扫描区域或采样数量超限")
        if not (
            0 < self.min_width <= self.max_width < self.search_length
            and 0 < self.gradient_threshold <= 1
            and 0 < self.min_coverage <= 1
            and 0 < self.max_residual <= 10
            and self.polarity in {"bright", "dark"}
        ):
            raise ValueError("扫描阈值配置无效")


def prepare_gray(image: np.ndarray) -> np.ndarray:
    """只读输入转为 0–1 float32 灰度；uint16 不降为 uint8。"""
    if not isinstance(image, np.ndarray) or image.ndim not in (2, 3) or image.size == 0:
        raise ValueError("图像矩阵无效")
    if image.shape[0] * image.shape[1] > 64_000_000 or max(image.shape[:2]) >= 32767:
        raise ValueError("计量原图超过 6400 万像素")
    if image.dtype not in (np.uint8, np.uint16, np.float32):
        raise ValueError("只支持 uint8、uint16 或 0–1 float32 图像")
    if image.ndim == 3 and image.shape[2] not in (1, 3, 4):
        raise ValueError("图像通道必须为灰度、BGR 或 BGRA")
    if image.dtype == np.float32 and (
        not np.isfinite(image).all() or image.min() < 0 or image.max() > 1
    ):
        raise ValueError("float32 图像必须是有限的 0–1 强度")
    gray = (
        image
        if image.ndim == 2
        else image[:, :, 0]
        if image.shape[2] == 1
        else cv2.cvtColor(
            image, cv2.COLOR_BGR2GRAY if image.shape[2] == 3 else cv2.COLOR_BGRA2GRAY
        )
    )
    divisor = (
        255.0
        if image.dtype == np.uint8
        else 65535.0
        if image.dtype == np.uint16
        else 1.0
    )
    return gray.astype(np.float32) / divisor


def _peaks(scores: np.ndarray, threshold: float, *, limit: int = 16) -> list[float]:
    """局部极值加有界 NMS 和三点细化；边界不伪造峰。"""
    indices = (
        np.flatnonzero(
            (scores[1:-1] >= threshold)
            & (scores[1:-1] > scores[:-2])
            & (scores[1:-1] >= scores[2:])
        )
        + 1
    )
    if len(indices) > limit * 8:
        raise ValueError("扫描线候选峰过多，请限定区域或阈值")
    chosen = []
    for index in sorted(indices.tolist(), key=lambda i: (-scores[i], i)):
        if any(abs(index - old) < 2 for old in chosen):
            continue
        chosen.append(index)
        if len(chosen) > limit:
            raise ValueError(f"扫描线有效候选超过 {limit}")
    results = []
    for index in sorted(chosen):
        left, center, right = (float(x) for x in scores[index - 1 : index + 2])
        curvature = left - 2 * center + right
        if curvature >= -1e-8:
            continue
        results.append(index + max(-0.5, min(0.5, 0.5 * (left - right) / curvature)))
    return results


def _fit_edge(across: np.ndarray, along: np.ndarray, residual_limit: float):
    """确定性稳健线拟合，保留有效覆盖范围和残差。"""
    keep = np.ones(len(across), dtype=bool)
    design = np.column_stack((across, np.ones_like(across)))
    for _ in range(4):
        if keep.sum() < 3 or np.ptp(across[keep]) < 1e-6:
            return None
        fit = np.linalg.lstsq(design[keep], along[keep], rcond=None)[0]
        residual = np.abs(design @ fit - along)
        candidate = residual <= residual_limit
        if np.array_equal(candidate, keep):
            break
        keep = candidate
    if keep.sum() < 3:
        return None
    fit = np.linalg.lstsq(design[keep], along[keep], rcond=None)[0]
    residual = np.abs(design[keep] @ fit - along[keep])
    return fit, keep, float(np.max(residual))


def extract_edge_pair(
    gray: np.ndarray,
    center,
    direction,
    settings: EdgePairSettings,
    *,
    check=lambda: None,
    diagnostics: dict | None = None,
) -> dict:
    """提取带内两侧有限边缘；越界/缺边/歧义返回无效，不做补边或重试。"""
    settings.validate()
    if diagnostics is not None:
        diagnostics.clear()
    check()
    if (
        not isinstance(gray, np.ndarray)
        or gray.ndim != 2
        or gray.dtype != np.float32
        or not gray.size
        or max(gray.shape) >= 32767
    ):
        raise ValueError("扫描图必须是 prepare_gray 生成的 float32 二维灰度图")
    center = np.asarray(center, dtype=np.float64)
    axis = np.asarray(direction, dtype=np.float64)
    if (
        center.shape != (2,)
        or axis.shape != (2,)
        or not np.isfinite(center).all()
        or not np.isfinite(axis).all()
        or abs(np.linalg.norm(axis) - 1) > 1e-6
    ):
        raise ValueError("扫描中心和单位方向无效")
    normal = np.array([-axis[1], axis[0]])
    samples = math.ceil(settings.search_length / settings.sample_step) + 1
    along = np.linspace(
        -settings.search_length / 2, settings.search_length / 2, samples
    )
    across = np.linspace(
        -settings.band_width / 2, settings.band_width / 2, settings.scan_lines
    )
    coordinates = center + across[:, None, None] * normal + along[None, :, None] * axis
    if (
        coordinates[:, :, 0].min() < 0
        or coordinates[:, :, 1].min() < 0
        or coordinates[:, :, 0].max() > gray.shape[1] - 1
        or coordinates[:, :, 1].max() > gray.shape[0] - 1
    ):
        return {"state": "out_of_view", "reason": "scan_out_of_view"}
    strips = cv2.remap(
        gray,
        coordinates[:, :, 0].astype(np.float32),
        coordinates[:, :, 1].astype(np.float32),
        cv2.INTER_LINEAR,
    )
    if not np.isfinite(strips).all() or strips.min() < 0 or strips.max() > 1:
        raise ValueError("扫描区强度必须为有限的 0–1 数值")
    step = float(along[1] - along[0])
    strips = cv2.GaussianBlur(strips, (5, 1), 0.8)
    gradient = np.gradient(strips.astype(np.float64), step, axis=1)
    if settings.polarity == "dark":
        gradient = -gradient
    if diagnostics is not None:
        # 诊断仅抽取显示点，检测仍使用全部样本；不在默认生产路径分配列表。
        indices = np.unique(np.linspace(0, samples - 1, min(samples, 1024)).astype(int))
        diagnostics.update(
            distance_px=along[indices].tolist(),
            intensity=strips.mean(axis=0)[indices].tolist(),
            gradient=gradient.mean(axis=0)[indices].tolist(),
            gradient_threshold=settings.gradient_threshold,
            scan_lines=settings.scan_lines,
            polarity=settings.polarity,
        )
    chosen = []
    ambiguous_lines = 0
    for row, derivative in enumerate(gradient):
        check()
        first = _peaks(derivative, settings.gradient_threshold)
        second = _peaks(-derivative, settings.gradient_threshold)
        pairs = [
            (
                a,
                b,
                min(
                    float(np.interp(a, np.arange(samples), derivative)),
                    float(np.interp(b, np.arange(samples), -derivative)),
                ),
            )
            for a in first
            for b in second
            if settings.min_width <= (b - a) * step <= settings.max_width
        ]
        # 表面纹理的弱峰不能仅因靠近名义中心而优先于两侧真实边缘。
        pairs.sort(key=lambda p: (-p[2], abs((p[0] + p[1]) / 2 - (samples - 1) / 2), p))
        if not pairs:
            continue
        if any(
            other[2] >= pairs[0][2] * 0.9
            and abs((other[0] + other[1] - pairs[0][0] - pairs[0][1]) / 2) * step > 1.5
            for other in pairs[1:]
        ):
            ambiguous_lines += 1
            continue
        a, b, _ = pairs[0]
        chosen.append((across[row], along[0] + a * step, along[0] + b * step))
    if diagnostics is not None:
        diagnostics.update(
            observed_pairs=[list(point) for point in chosen],
            ambiguous_lines=ambiguous_lines,
        )
    if len(chosen) < max(3, math.ceil(settings.scan_lines * settings.min_coverage)):
        if ambiguous_lines:
            return {"state": "ambiguous", "reason": "multiple_edge_pairs"}
        return {"state": "not_found", "reason": "edge_coverage_low"}
    raw = np.asarray(chosen)
    left = _fit_edge(raw[:, 0], raw[:, 1], settings.max_residual)
    right = _fit_edge(raw[:, 0], raw[:, 2], settings.max_residual)
    if left is None or right is None:
        return {"state": "not_found", "reason": "edge_fit_invalid"}
    common = left[1] & right[1]
    if common.sum() < max(3, math.ceil(settings.scan_lines * settings.min_coverage)):
        return {"state": "not_found", "reason": "edge_coverage_low"}
    support = raw[common, 0]
    if support.min() > 0 or support.max() < 0:
        return {"state": "not_found", "reason": "section_not_observed"}
    edges = []
    for fit, _, _ in (left, right):
        edges.append(
            (
                center
                + support[:, None] * normal
                + (support * fit[0] + fit[1])[:, None] * axis
            ).tolist()
        )
    if diagnostics is not None:
        diagnostics.update(
            inlier_pairs=raw[common].tolist(),
            residual_px=max(left[2], right[2]),
            coverage=float(common.sum() / settings.scan_lines),
        )
    return {
        "state": "found",
        "reason": None,
        "left": edges[0],
        "right": edges[1],
        "center": (center + axis * (left[0][1] + right[0][1]) / 2).tolist(),
        "residual_px": max(left[2], right[2]),
        "coverage": float(common.sum() / settings.scan_lines),
    }


def extract_band_pairs(
    gray: np.ndarray,
    center,
    direction,
    length: float,
    settings: EdgePairSettings,
    *,
    check=lambda: None,
    consume_samples=lambda n: None,
) -> dict:
    """在明确扫描带内查找全部同类型边缘对，再逐个复核；不代表带外不存在物体。"""
    settings.validate()
    center, axis = np.asarray(center, dtype=float), np.asarray(direction, dtype=float)
    if not math.isfinite(length) or not settings.search_length <= length <= 8190:
        raise ValueError("候选搜索带长度必须覆盖局部扫描窗口且不超过 8190 像素")
    if (
        center.shape != (2,)
        or axis.shape != (2,)
        or not np.isfinite(center).all()
        or not np.isfinite(axis).all()
        or abs(np.linalg.norm(axis) - 1) > 1e-6
    ):
        raise ValueError("候选扫描中心和方向无效")
    if gray.ndim != 2 or gray.dtype != np.float32 or max(gray.shape) >= 32767:
        raise ValueError("候选图必须是 prepare_gray 生成的灰度矩阵")
    count = math.ceil(length / settings.sample_step) + 1
    if count >= 32767 or count * settings.scan_lines > 2_000_000:
        raise ValueError("候选带采样预算超限")
    normal = np.array([-axis[1], axis[0]])
    along = np.linspace(-length / 2, length / 2, count)
    across = np.linspace(
        -settings.band_width / 2, settings.band_width / 2, settings.scan_lines
    )
    coordinates = center + across[:, None, None] * normal + along[None, :, None] * axis
    if (
        coordinates[:, :, 0].min() < 0
        or coordinates[:, :, 1].min() < 0
        or coordinates[:, :, 0].max() > gray.shape[1] - 1
        or coordinates[:, :, 1].max() > gray.shape[0] - 1
    ):
        return {"state": "out_of_view", "reason": "scan_out_of_view", "candidates": []}
    check()
    strips = cv2.remap(
        gray,
        coordinates[:, :, 0].astype(np.float32),
        coordinates[:, :, 1].astype(np.float32),
        cv2.INTER_LINEAR,
    )
    if not np.isfinite(strips).all() or strips.min() < 0 or strips.max() > 1:
        raise ValueError("候选扫描强度必须在 0–1 内")
    profile = cv2.GaussianBlur(strips, (5, 1), 0.8).mean(axis=0, dtype=np.float64)
    step = along[1] - along[0]
    gradient = np.gradient(profile, step) * (1 if settings.polarity == "bright" else -1)
    # 相邻异极性边缘形成一个候选，避免跨过其他 PIN 配对成虚假大宽度。
    transitions = sorted(
        [(p, 1) for p in _peaks(gradient, settings.gradient_threshold, limit=2048)]
        + [(p, -1) for p in _peaks(-gradient, settings.gradient_threshold, limit=2048)]
    )
    seeds = [
        (a + b) / 2
        for (a, polarity), (b, following) in zip(transitions, transitions[1:])
        if polarity == 1
        and following == -1
        and settings.min_width <= (b - a) * step <= settings.max_width
    ]
    if len(seeds) > 2048:
        raise ValueError("候选数量超过 2048")
    consume_samples(
        len(seeds)
        * (math.ceil(settings.search_length / settings.sample_step) + 1)
        * settings.scan_lines
    )
    candidates = []
    for seed in seeds:
        check()
        point = center + axis * (along[0] + seed * step)
        result = extract_edge_pair(gray, point, axis, settings, check=check)
        if result["state"] != "found":
            return {
                "state": "ambiguous",
                "reason": "candidate_not_confirmed",
                "candidates": candidates,
            }
        candidates.append(result)
    return {"state": "found", "reason": None, "candidates": candidates}
