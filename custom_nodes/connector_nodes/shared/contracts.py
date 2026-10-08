"""连接器的稳定 PIN 身份、采样配置和命名尺寸定义。"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.metrology import (
    Contract,
    FeatureObservations,
    Finite,
    Identifier,
    ImageIdentity,
    Matrix3,
    Point,
    PoseObservation,
    unique_ids,
)


class SamplingType(Contract):
    """某种 PIN 复用的扫描配置；长度及步距采用参考图像像素。"""

    type_id: Identifier
    search_length: Annotated[Finite, Field(ge=4, le=2048)] = 48.0
    band_width: Annotated[Finite, Field(ge=1, le=256)] = 8.0
    scan_lines: Annotated[int, Field(strict=True, ge=3, le=65)] = 9
    sample_step: Annotated[Finite, Field(ge=0.25, le=2)] = 0.5
    angle_degrees: Finite = 0.0
    polarity: Literal["bright", "dark"] = "bright"
    gradient_threshold: Annotated[Finite, Field(gt=0, le=1)] = 0.03
    min_width: Annotated[Finite, Field(gt=0, le=2048)] = 2.0
    max_width: Annotated[Finite, Field(gt=0, le=2048)] = 40.0
    min_coverage: Annotated[Finite, Field(gt=0, le=1)] = 0.7
    max_residual: Annotated[Finite, Field(gt=0, le=10)] = 1.0

    @model_validator(mode="after")
    def check_span(self) -> Self:
        """宽度窗口必须可被配置的扫描线覆盖。"""
        if self.min_width > self.max_width or self.max_width >= self.search_length:
            raise ValueError("PIN 宽度范围必须位于扫描线内")
        return self


class EndpointPair(Contract):
    """相对 PIN 名义中心的一条扫描带，提取两个具名端点，不推断不可见针根。"""

    first_id: Identifier
    second_id: Identifier
    sampling_type: Identifier
    center_offset: Point = (0.0, 0.0)


class CandidateBand(Contract):
    """额外候选的显式搜索域；仅声明配置范围及采样类型内的检查。"""

    band_id: Identifier
    center: Point
    length: Annotated[Finite, Field(ge=4, le=8190)]
    sampling_type: Identifier


class PinDefinition(Contract):
    """名义位置身份，不随观测排序变化；留空仍需要检查。"""

    pin_id: Identifier
    row_id: Identifier
    pin_type: Identifier
    center: Point
    expected_present: StrictBool = True
    endpoint_pairs: Annotated[tuple[EndpointPair, ...], Field(max_length=2)] = ()


class PinLayout(Contract):
    """参考像素坐标中的展开布局；间距和产品名称不写入节点类型。"""

    reference_id: Identifier
    reference_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    pins: Annotated[tuple[PinDefinition, ...], Field(min_length=1, max_length=1024)]
    types: Annotated[tuple[SamplingType, ...], Field(min_length=1, max_length=64)]
    candidate_bands: Annotated[tuple[CandidateBand, ...], Field(max_length=64)] = ()
    diagnostic_pin_id: Identifier | None = None

    @model_validator(mode="after")
    def check_layout(self) -> Self:
        """校验身份/类型引用和整次调用的采样预算，超限不截断。"""
        unique_ids([p.pin_id for p in self.pins], "pins")
        unique_ids([t.type_id for t in self.types], "types")
        unique_ids([b.band_id for b in self.candidate_bands], "candidate_bands")
        if self.diagnostic_pin_id is not None and self.diagnostic_pin_id not in {
            pin.pin_id for pin in self.pins
        }:
            raise ValueError("诊断 PIN 必须来自当前布局")
        types = {t.type_id: t for t in self.types}
        total = 0
        for pin in self.pins:
            if len("presence:" + pin.pin_id) > 128:
                raise ValueError("展开后的检查 ID 过长")
            if pin.pin_type not in types:
                raise ValueError("PIN 引用了不存在的采样类型")
            scan = types[pin.pin_type]
            total += (int(scan.search_length / scan.sample_step) + 2) * scan.scan_lines
            feature_names = ["left", "right", "center"]
            for pair in pin.endpoint_pairs:
                if pair.sampling_type not in types:
                    raise ValueError("端点扫描类型不存在")
                feature_names.extend([pair.first_id, pair.second_id])
                endpoint = types[pair.sampling_type]
                total += (
                    int(endpoint.search_length / endpoint.sample_step) + 2
                ) * endpoint.scan_lines
            unique_ids(feature_names, "PIN feature names")
            if any(len(pin.pin_id + ":" + name) > 128 for name in feature_names):
                raise ValueError("展开后的特征 ID 过长")
        if sum(3 + 2 * len(pin.endpoint_pairs) for pin in self.pins) > 6144:
            raise ValueError("特征总数超过 6144")
        for band in self.candidate_bands:
            if len("extra:" + band.band_id) > 128:
                raise ValueError("展开后的检查 ID 过长")
            if (
                band.sampling_type not in types
                or band.length < types[band.sampling_type].search_length
            ):
                raise ValueError("候选带类型或长度无效")
            scan = types[band.sampling_type]
            total += (int(band.length / scan.sample_step) + 2) * scan.scan_lines
        if total > 4_000_000:
            raise ValueError("单次采样点数超过 4000000")
        return self


class PinObservation(Contract):
    """PIN 名义要求和本次观测分开，缺失/歧义不补测量坐标。"""

    pin_id: Identifier
    row_id: Identifier
    pin_type: Identifier
    expected_present: StrictBool
    nominal_image_point: Point
    state: Literal["found", "not_found", "ambiguous", "out_of_view", "not_evaluated"]
    center_image_point: Point | None
    feature_ids: tuple[Identifier, ...] = ()
    reason: Identifier | None

    @model_validator(mode="after")
    def check_observation(self) -> Self:
        """只有有效观测允许引用实际几何。"""
        unique_ids(self.feature_ids, "feature_ids")
        if self.state == "found":
            if (
                self.center_image_point is None
                or self.reason is not None
                or not self.feature_ids
            ):
                raise ValueError("有效 PIN 观测缺少位置或特征")
        elif (
            self.center_image_point is not None
            or self.feature_ids
            or self.reason is None
        ):
            raise ValueError("无效 PIN 观测不能带有实际位置或特征")
        return self


class PinObservations(Contract):
    """PIN 集与 Features 通过观察 ID、原图身份及参考布局关联。"""

    observation_id: Identifier
    image: ImageIdentity
    reference_id: Identifier
    pins: Annotated[tuple[PinObservation, ...], Field(min_length=1, max_length=1024)]
    image_from_reference: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    unassigned_points: Annotated[tuple[Point, ...], Field(max_length=2048)] = ()

    @model_validator(mode="after")
    def check_ids(self) -> Self:
        """禁止重复 PIN 和重复分配同一个特征。"""
        unique_ids([p.pin_id for p in self.pins], "pins")
        unique_ids([f for p in self.pins for f in p.feature_ids], "assigned_features")
        PoseObservation(
            image=self.image,
            reference_id=self.reference_id,
            state="found",
            reason=None,
            image_from_reference=self.image_from_reference,
        )
        return self

    def require_matching_features(self, features: FeatureObservations) -> None:
        """拒绝错帧/错观察/错布局和不存在的特征引用。"""
        if (self.observation_id, self.image, self.reference_id) != (
            features.observation_id,
            features.image,
            features.reference_id,
        ):
            raise ValueError("Pins 与 Features 不属于同一次观察")
        available = {f.feature_id for f in features.features}
        if any(f not in available for p in self.pins for f in p.feature_ids):
            raise ValueError("PIN 引用了缺失特征")


class MeasurementDefinition(Contract):
    """命名尺寸项；公差由通用 Check Limits 配置。"""

    item_id: Identifier
    kind: Literal["width", "pitch", "total_pitch", "gap", "offset", "length", "angle"]
    enabled: StrictBool = True
    pin_a: Identifier
    pin_b: Identifier | None = None
    direction: Point = (1.0, 0.0)
    section: Finite | None = None
    distance_mode: Literal["projected", "euclidean"] = "projected"
    feature_a: Identifier | None = None
    feature_b: Identifier | None = None

    @model_validator(mode="after")
    def check_definition(self) -> Self:
        """约束对象数和方向；宽度/间隙显式限定观测截面。"""
        pair = self.kind in {"pitch", "total_pitch", "gap", "angle"}
        if self.kind == "length":
            if (
                self.feature_a is None
                or self.feature_b is None
                or self.feature_a == self.feature_b
            ):
                raise ValueError("长度必须指定不同的起止点特征，不能从框或中心距推断")
            if self.pin_b is None:
                raise ValueError("长度必须指定起止特征的所属 PIN；同 PIN 可重复指定")
            pair = True
        if pair != (self.pin_b is not None) or (
            self.pin_a == self.pin_b and self.kind != "length"
        ):
            raise ValueError("尺寸对象定义无效")
        if self.kind != "length" and (
            self.feature_a is not None or self.feature_b is not None
        ):
            raise ValueError("此尺寸使用固定语义的观测特征，不接受长度端点配置")
        if abs(sum(x * x for x in self.direction) - 1) > 1e-6:
            raise ValueError("测量方向必须是单位向量")
        if self.kind in {"width", "gap"} and self.section is None:
            raise ValueError("宽度/间隙必须配置截面")
        return self
