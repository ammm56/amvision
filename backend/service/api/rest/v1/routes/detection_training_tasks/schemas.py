"""detection 训练任务 API 请求与提交响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.models.platform_model_support import build_platform_model_type_field_description


class DetectionTrainingTaskCreateRequestBody(BaseModel):
    """描述 detection 训练任务创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description=build_platform_model_type_field_description(DETECTION_TASK_TYPE))
    dataset_export_id: str | None = Field(default=None, description="训练输入使用的 DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="训练输入使用的导出 manifest object key")
    recipe_id: str = Field(description="训练 recipe id")
    model_scale: str = Field(description="训练目标的模型 scale")
    output_model_name: str = Field(description="训练后登记的模型名")
    warm_start_model_version_id: str | None = Field(default=None, description="warm start 使用的 ModelVersion id")
    evaluation_interval: int | None = Field(default=5, ge=1, description="每隔多少轮执行一次真实验证评估；未指定时默认 5")
    max_epochs: int | None = Field(default=None, description="最大训练轮数")
    batch_size: int | None = Field(default=None, description="batch size")
    gpu_count: int | None = Field(
        default=None,
        ge=1,
        le=1,
        description="当前版本只支持单 GPU 训练；可省略或填写 1",
    )
    precision: Literal["fp16", "fp32"] | None = Field(
        default=None,
        description="请求使用的训练 precision；未指定时由具体 detection training backend 解析默认值",
    )
    input_size: tuple[int, int] | None = Field(default=None, description="训练输入尺寸")
    extra_options: "DetectionTrainingExtraOptionsRequest" = Field(
        default_factory=lambda: DetectionTrainingExtraOptionsRequest(),
        description="附加训练选项；当前 OpenAPI 会展开 detection 训练公开字段说明，其余 backend 专用字段仍允许透传",
    )
    display_name: str = Field(default="", description="可选任务展示名称")


class DetectionTrainingExtraOptionsRequest(BaseModel):
    """描述 detection 训练任务 extra_options 的公开可选字段。"""

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "learning_rate": 0.01,
                    "weight_decay": 0.0005,
                    "flip_prob": 0.5,
                    "hsv_prob": 1.0,
                    "mosaic_prob": 1.0,
                    "enable_mixup": True,
                    "mixup_prob": 0.0,
                    "degrees": 0.0,
                    "translate": 0.1,
                    "scale": 0.5,
                    "shear": 0.0,
                    "close_mosaic": 10,
                }
            ]
        },
    )

    seed: int | None = Field(default=None, description="训练随机种子；YOLOX 当前默认 0")
    num_workers: int | None = Field(default=None, description="DataLoader worker 数量；YOLOX 当前默认 0")
    device: str | None = Field(
        default=None,
        description="单卡训练 device；支持 auto、cpu、cuda、cuda:<index>，空值按 CUDA 可用性自动选择",
    )
    max_labels: int | None = Field(default=None, description="单张图片保留的最大标签数；YOLOX 当前默认 120")
    learning_rate: float | None = Field(default=None, description="训练学习率；YOLOv8/YOLO11/YOLO26 detection 默认 0.01，YOLOX 按 batch size 缩放")
    weight_decay: float | None = Field(default=None, description="训练 weight decay；YOLOv8/YOLO11/YOLO26 detection 默认 5e-4，YOLOX 默认 5e-4")
    class_loss_weight: float | None = Field(default=None, description="分类损失权重；YOLO 主线 detection 当前默认 0.5")
    box_loss_weight: float | None = Field(default=None, description="框回归损失权重；YOLO 主线 detection 当前默认 7.5")
    dfl_loss_weight: float | None = Field(default=None, description="DFL 损失权重；YOLO 主线 detection 当前默认 1.5")
    evaluation_confidence_threshold: float | None = Field(
        default=None,
        description="验证阶段 detection 评估 confidence threshold；YOLOX 默认 0.01，YOLOv8/YOLO11/YOLO26 默认 0.001",
    )
    evaluation_nms_threshold: float | None = Field(
        default=None,
        description="验证阶段 detection 评估 NMS threshold；YOLOX 默认 0.65，YOLOv8/YOLO11/YOLO26 默认 0.7；端到端模型导出后会改走 top-k 输出",
    )
    assign_topk: int | None = Field(default=None, description="标签分配 top-k；YOLO 主线 detection 当前默认 10")
    assign_alpha: float | None = Field(default=None, description="标签分配 alpha；YOLO 主线 detection 当前默认 0.5")
    assign_beta: float | None = Field(default=None, description="标签分配 beta；YOLO 主线 detection 当前默认 6.0")
    min_lr_ratio: float | None = Field(default=None, description="余弦退火最小学习率比例；YOLO 主线 detection 当前默认 0.01")
    grad_clip_norm: float | None = Field(default=None, description="梯度裁剪上限；YOLO 主线 detection 当前默认 10.0")
    flip_prob: float | None = Field(default=None, description="随机水平翻转概率；YOLOv8/YOLO11/YOLO26 和 YOLOX 默认 0.5")
    hsv_prob: float | None = Field(default=None, description="HSV 抖动概率；YOLOv8/YOLO11/YOLO26 和 YOLOX 默认 1.0")
    mosaic_prob: float | None = Field(default=None, description="Mosaic 增强概率；YOLOv8/YOLO11/YOLO26 和 YOLOX 默认 1.0")
    mixup_prob: float | None = Field(default=None, description="MixUp 增强概率；YOLOv8/YOLO11/YOLO26 默认 0.0，YOLOX 默认 1.0")
    enable_mixup: bool | None = Field(default=None, description="是否允许在 Mosaic 链路后追加 MixUp；YOLOv8/YOLO11/YOLO26 和 YOLOX 默认 true")
    affine_prob: float | None = Field(default=None, description="随机仿射增强概率；YOLOv8/YOLO11/YOLO26 默认 1.0")
    degrees: float | None = Field(default=None, description="随机仿射旋转角度范围；YOLOv8/YOLO11/YOLO26 默认 0.0，YOLOX 默认 10.0")
    translate: float | None = Field(default=None, description="随机仿射平移比例；YOLOv8/YOLO11/YOLO26 和 YOLOX 默认 0.1")
    scale: float | None = Field(default=None, description="随机仿射缩放范围；YOLOv8/YOLO11/YOLO26 默认 0.5")
    shear: float | None = Field(default=None, description="随机仿射错切角度范围；YOLOv8/YOLO11/YOLO26 默认 0.0，YOLOX 默认 2.0")
    perspective: float | None = Field(default=None, description="随机透视变换强度；YOLOv8/YOLO11/YOLO26 默认 0.0")
    mosaic_scale: tuple[float, float] | None = Field(
        default=None,
        description="Mosaic 拼图缩放范围；YOLOv8/YOLO11/YOLO26 默认 [0.5, 1.5]，YOLOX 默认 [0.1, 2.0]",
    )
    mixup_scale: tuple[float, float] | None = Field(
        default=None,
        description="MixUp 缩放范围；YOLO 主线 detection 当前默认 [0.5, 1.5]",
    )
    close_mosaic: int | None = Field(default=None, description="最后关闭 Mosaic 的 epoch 数；YOLOv8/YOLO11/YOLO26 默认 10")
    multi_scale: float | None = Field(default=None, description="多尺度训练幅度；YOLOv8/YOLO11/YOLO26 默认 0.0 表示关闭")
    multi_scale_stride: int | None = Field(default=None, description="多尺度训练尺寸对齐 stride；YOLOv8/YOLO11/YOLO26 默认 32")
    multiscale_range: int | None = Field(default=None, description="多尺度训练范围；YOLOX 当前默认 5")
    ema: bool | None = Field(default=None, description="是否启用 EMA；YOLOX 当前默认 true")
    warmup_epochs: int | None = Field(default=None, description="warmup epoch 数；YOLOX 当前默认 5")
    no_aug_epochs: int | None = Field(default=None, description="训练尾段 no-aug epoch 数；YOLOX 当前默认 15")


DetectionTrainingTaskCreateRequestBody.model_rebuild()

class DetectionTrainingTaskSubmissionResponse(BaseModel):
    """描述 detection 训练任务创建响应。"""

    task_id: str = Field(description="训练任务 id")
    status: str = Field(description="训练任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    model_type: str = Field(description="模型分类")
    dataset_export_id: str = Field(description="解析后的 DatasetExport id")
    dataset_export_manifest_key: str = Field(description="解析后的导出 manifest object key")
    dataset_version_id: str = Field(description="导出来源的 DatasetVersion id")
    format_id: str = Field(description="训练使用的数据集导出格式 id")

