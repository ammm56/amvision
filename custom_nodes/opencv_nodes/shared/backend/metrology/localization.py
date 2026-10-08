"""有界刚性模板定位，显式区分未发现和多个可信工件。"""

import math
from typing import Annotated, Self

import cv2
import numpy as np
from pydantic import Field, model_validator

from backend.contracts.workflows.metrology import Contract, Finite, Identifier, Point
from .geometry import map_points


class RigidLocateSettings(Contract):
    """参考图的 ROI、原图锚点与有限角度搜索；没有尺度自由度。"""

    reference_id: Identifier
    template_roi: tuple[
        Annotated[int, Field(strict=True, ge=0)],
        Annotated[int, Field(strict=True, ge=0)],
        Annotated[int, Field(strict=True, ge=4)],
        Annotated[int, Field(strict=True, ge=4)],
    ]
    anchor: Point
    angle_min: Annotated[Finite, Field(ge=-180, le=180)] = -15.0
    angle_max: Annotated[Finite, Field(ge=-180, le=180)] = 15.0
    angle_step: Annotated[Finite, Field(ge=0.1, le=30)] = 1.0
    minimum_score: Annotated[Finite, Field(gt=0, le=1)] = 0.75

    @model_validator(mode="after")
    def check_budget(self) -> Self:
        """先校验搜索次数和 ROI 面积，防止先创建过大数组。"""
        if (
            self.angle_max < self.angle_min
            or math.ceil((self.angle_max - self.angle_min) / self.angle_step) > 180
        ):
            raise ValueError("定位角度候选超过 181 或范围倒置")
        x, y, w, h = self.template_roi
        if w * h > 2_000_000 or not (
            x <= self.anchor[0] < x + w and y <= self.anchor[1] < y + h
        ):
            raise ValueError("模板 ROI 超过 200 万像素或锚点不在 ROI 内")
        return self


def _variant(template, angle):
    """围绕像素中心旋转 ROI，返回 ROI→变体矩阵。"""
    height, width = template.shape
    affine = cv2.getRotationMatrix2D(((width - 1) / 2, (height - 1) / 2), angle, 1.0)
    corners = (
        np.array(
            [
                [0, 0, 1],
                [width - 1, 0, 1],
                [width - 1, height - 1, 1],
                [0, height - 1, 1],
            ],
            np.float64,
        )
        @ affine.T
    )
    low, high = corners.min(axis=0), corners.max(axis=0)
    affine[:, 2] -= low
    size = tuple((np.ceil(high - low) + 1).astype(int))
    border = float(
        np.median(
            np.concatenate((template[0], template[-1], template[:, 0], template[:, -1]))
        )
    )
    rotated = cv2.warpAffine(
        template,
        affine,
        size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border,
    )
    matrix = np.eye(3)
    matrix[:2] = affine
    mask = cv2.warpAffine(
        np.ones(template.shape, np.uint8),
        affine,
        size,
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return rotated, matrix, mask


def _masked_correlation(source, template, mask, *, squared=None):
    """二值掩膜的归一化零均值相关；复用源图平方，避免通用掩膜路径的重复卷积。"""
    if np.all(mask):
        return cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
    weights = mask.astype(np.float32)
    count = float(weights.sum())
    centered = (
        template - float(np.sum(template * weights, dtype=np.float64) / count)
    ) * weights
    energy = float(np.sum(centered * centered, dtype=np.float64))
    cross = cv2.matchTemplate(source, centered, cv2.TM_CCORR)
    sums = cv2.matchTemplate(source, weights, cv2.TM_CCORR)
    squares = cv2.matchTemplate(
        source * source if squared is None else squared, weights, cv2.TM_CCORR
    )
    variance = np.maximum(squares - sums * sums / count, 0)
    # 常量区域的浮点消去误差不能产生虚假的高分。
    valid = variance > np.maximum(squares * 1e-6, 1e-10)
    denominator = np.sqrt(variance * energy)
    return np.clip(
        np.divide(
            cross,
            denominator,
            out=np.full_like(cross, -1),
            where=valid & (denominator > 0),
        ),
        -1,
        1,
    )


def _locate_full(
    source, reference, settings: RigidLocateSettings, *, check=lambda: None
):
    """返回有限候选中的唯一位姿；同物体的相邻角度峰合并后再检查歧义。"""
    if any(
        not isinstance(a, np.ndarray) or a.dtype != np.float32 or a.ndim != 2
        for a in (source, reference)
    ):
        raise ValueError("定位输入必须为准备后的 float32 灰度图")
    if source.size > 16_000_000 or reference.size > 16_000_000:
        raise ValueError("定位输入超过 1600 万像素")
    x, y, width, height = settings.template_roi
    if x + width > reference.shape[1] or y + height > reference.shape[0]:
        raise ValueError("模板 ROI 超出参考图")
    template = reference[y : y + height, x : x + width]
    if not np.isfinite(template).all() or float(template.std()) < 0.005:
        raise ValueError("模板缺少可区分的灰度变化")
    crop = np.array([[1.0, 0, -x], [0, 1.0, -y], [0, 0, 1.0]])
    angles = np.linspace(
        settings.angle_min,
        settings.angle_max,
        math.ceil((settings.angle_max - settings.angle_min) / settings.angle_step) + 1,
    )
    candidates = []
    search_positions = 0
    squared = source * source
    for angle in angles:
        check()
        variant, matrix, mask = _variant(template, float(angle))
        vh, vw = variant.shape
        if vh > source.shape[0] or vw > source.shape[1]:
            continue
        search_positions += (source.shape[0] - vh + 1) * (source.shape[1] - vw + 1)
        if search_positions > 100_000_000:
            raise ValueError("定位搜索预算超过 1 亿位置，请缩小角度范围或输入图像")
        # 旋转补出的三角区没有参考证据，不参与匹配，避免背景/针脚污染定位分数。
        scores = _masked_correlation(source, variant, mask, squared=squared)
        # 常量搜索区的归一化相关没有定义，表示无候选，不是有效的完美匹配。
        scores[~np.isfinite(scores)] = -1
        # 单角度最多四个工件候选；超过上限不静默截断为唯一结果。
        for _ in range(5):
            _, score, _, (px, py) = cv2.minMaxLoc(scores)
            if score < settings.minimum_score:
                break
            if _ == 4:
                raise ValueError("定位候选超过单角度上限 4")
            offset = np.array([px, py], np.float64)
            for axis, coordinate in enumerate((px, py)):
                limit = scores.shape[1 - axis]
                if 0 < coordinate < limit - 1:
                    triple = (
                        scores[py, px - 1 : px + 2]
                        if axis == 0
                        else scores[py - 1 : py + 2, px]
                    )
                    a, b, c = (float(v) for v in triple)
                    curvature = a - 2 * b + c
                    if curvature < -1e-8:
                        offset[axis] += np.clip(0.5 * (a - c) / curvature, -0.5, 0.5)
            translation = np.eye(3)
            translation[:2, 2] = offset
            transform = translation @ matrix @ crop
            anchor = map_points([settings.anchor], transform)[0]
            candidates.append((float(score), transform, anchor))
            rx, ry = max(4, vw // 2), max(4, vh // 2)
            scores[max(0, py - ry) : py + ry + 1, max(0, px - rx) : px + rx + 1] = -1
    if not candidates:
        return dict(
            state="not_found",
            reason="template_not_found",
            matrix=None,
            score=None,
            candidate_count=0,
        )
    distinct = []
    for candidate in sorted(candidates, key=lambda c: -c[0]):
        if not any(
            np.linalg.norm(candidate[2] - old[2]) < max(5, min(width, height) * 0.4)
            for old in distinct
        ):
            distinct.append(candidate)
    if len(distinct) > 1:
        return dict(
            state="ambiguous",
            reason="multiple_objects",
            matrix=None,
            score=distinct[0][0],
            candidate_count=len(distinct),
        )
    return dict(
        state="found",
        reason=None,
        matrix=distinct[0][1].tolist(),
        score=distinct[0][0],
        candidate_count=1,
    )


def locate_rigid(
    source, reference, settings: RigidLocateSettings, *, check=lambda: None
):
    """低分辨率全图搜索后在原图局部精定位；全分辨率证据决定最终结果。"""
    if any(
        not isinstance(a, np.ndarray)
        or a.dtype != np.float32
        or a.ndim != 2
        or not a.size
        or a.size > 16_000_000
        for a in (source, reference)
    ):
        raise ValueError("定位需要不超过 1600 万像素的 float32 灰度图")
    x, y, width, height = settings.template_roi
    if x + width > reference.shape[1] or y + height > reference.shape[0]:
        raise ValueError("模板 ROI 超出参考图")
    # 小图/细小模板直接计算，避免下采样消灭真实定位信息。
    scale = 0.5 if source.size > 250_000 and min(width, height) >= 32 else 1.0
    if scale == 1.0:
        return _locate_full(source, reference, settings, check=check)
    check()
    transform = np.array(
        [[scale, 0, (scale - 1) / 2], [0, scale, (scale - 1) / 2], [0, 0, 1.0]]
    )

    def small(image):
        """显式像素中心变换，不依赖奇数图像的隐式 resize 比例。"""
        return cv2.warpAffine(
            image,
            transform[:2],
            (math.ceil(image.shape[1] * scale), math.ceil(image.shape[0] * scale)),
            flags=cv2.INTER_LINEAR,
        )

    left, top = max(0, math.floor(x * scale)), max(0, math.floor(y * scale))
    right, bottom = math.ceil((x + width) * scale), math.ceil((y + height) * scale)
    reduced = RigidLocateSettings.model_validate(
        settings.model_dump()
        | {
            "template_roi": (left, top, right - left, bottom - top),
            "anchor": map_points([settings.anchor], transform)[0].tolist(),
        }
    )
    coarse = _locate_full(small(source), small(reference), reduced, check=check)
    if coarse["state"] != "found":
        return coarse
    estimate = np.linalg.inv(transform) @ np.asarray(coarse["matrix"]) @ transform
    angle = math.degrees(math.atan2(estimate[0, 1], estimate[0, 0]))
    template = reference[y : y + height, x : x + width]
    center = ((width - 1) / 2, (height - 1) / 2)
    target_center = map_points([[x + center[0], y + center[1]]], estimate)[0]
    crop = np.array([[1.0, 0, -x], [0, 1.0, -y], [0, 0, 1.0]])
    best = None
    for fine_angle in np.linspace(
        max(settings.angle_min, angle - settings.angle_step / 2),
        min(settings.angle_max, angle + settings.angle_step / 2),
        5,
    ):
        check()
        variant, matrix, mask = _variant(template, float(fine_angle))
        expected = target_center - map_points([center], matrix)[0]
        left, top = np.maximum(0, np.floor(expected - 4).astype(int))
        right = min(source.shape[1], math.ceil(expected[0]) + variant.shape[1] + 5)
        bottom = min(source.shape[0], math.ceil(expected[1]) + variant.shape[0] + 5)
        region = source[top:bottom, left:right]
        if region.shape[0] < variant.shape[0] or region.shape[1] < variant.shape[1]:
            continue
        scores = _masked_correlation(region, variant, mask)
        scores[~np.isfinite(scores)] = -1
        _, score, _, (px, py) = cv2.minMaxLoc(scores)
        offset = np.array([px + left, py + top], np.float64)
        for axis, coordinate in enumerate((px, py)):
            if 0 < coordinate < scores.shape[1 - axis] - 1:
                triple = (
                    scores[py, px - 1 : px + 2]
                    if axis == 0
                    else scores[py - 1 : py + 2, px]
                )
                a, b, c = (float(v) for v in triple)
                curvature = a - 2 * b + c
                if curvature < -1e-8:
                    offset[axis] += np.clip(0.5 * (a - c) / curvature, -0.5, 0.5)
        translation = np.eye(3)
        translation[:2, 2] = offset
        if best is None or score > best[0]:
            best = (float(score), translation @ matrix @ crop)
    if best is None or best[0] < settings.minimum_score:
        return dict(
            state="not_found",
            reason="template_not_found",
            matrix=None,
            score=best[0] if best else None,
            candidate_count=0,
        )
    return dict(
        state="found",
        reason=None,
        matrix=best[1].tolist(),
        score=best[0],
        candidate_count=1,
    )
