"""YOLOX detection 最小训练执行模块。"""

from __future__ import annotations

import io
import json
import math
from collections.abc import Callable
from contextlib import nullcontext, redirect_stdout
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class YoloXScaleProfile:
    """描述单个 YOLOX model scale 对应的建模参数。

    字段：
    - depth：backbone 与 head 的深度缩放系数。
    - width：backbone 与 head 的宽度缩放系数。
    - depthwise：是否启用 depthwise 卷积。
    """

    depth: float
    width: float
    depthwise: bool = False


@dataclass(frozen=True)
class YoloXDetectionTrainingExecutionRequest:
    """描述一次最小 YOLOX detection 训练执行请求。

    字段：
    - dataset_storage：本地文件存储服务。
    - manifest_payload：DatasetExport manifest 内容。
    - model_scale：当前训练使用的 model scale。
    - evaluation_interval：每隔多少个 epoch 执行一次真实验证评估；为空时使用默认值。
    - max_epochs：最大训练 epoch 数；为空时使用最小默认值。
    - batch_size：训练 batch size；为空时使用最小默认值。
    - gpu_count：请求参与训练的 GPU 数量；为空时按本机可用资源回退。
    - precision：请求使用的训练 precision。
    - warm_start_checkpoint_path：warm start checkpoint 的绝对路径。
    - resume_checkpoint_path：恢复训练使用的 latest checkpoint 绝对路径。
    - warm_start_source_summary：warm start 来源摘要。
    - input_size：训练输入尺寸；为空时使用最小默认值。
    - extra_options：附加训练选项。
    - epoch_callback：每轮训练结束后的进度回写回调；返回值可携带 save/pause 控制命令。
    - savepoint_callback：当训练收到手动保存或暂停请求时回传当前 savepoint。
    """

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_scale: str
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    gpu_count: int | None = None
    precision: str | None = None
    warm_start_checkpoint_path: Path | None = None
    resume_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    input_size: tuple[int, int] | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: Callable[["YoloXTrainingEpochProgress"], "YoloXTrainingControlCommand | None"] | None = None
    savepoint_callback: Callable[["YoloXTrainingSavePoint"], None] | None = None


@dataclass(frozen=True)
class YoloXDetectionTrainingExecutionResult:
    """描述一次最小 YOLOX detection 训练执行结果。

    字段：
    - checkpoint_bytes：训练生成的 checkpoint 二进制内容。
    - latest_checkpoint_bytes：训练结束时的最新 checkpoint 二进制内容。
    - metrics_payload：训练指标摘要。
    - validation_metrics_payload：验证指标摘要。
    - warm_start_summary：warm start 加载摘要。
    - implementation_mode：当前训练执行模式标识。
    - best_metric_name：最佳指标名称。
    - best_metric_value：最佳指标值。
    - evaluation_interval：真实验证评估周期。
    - category_names：训练使用的类别名列表。
    - split_names：manifest 中可见的 split 列表。
    - sample_count：manifest 中记录的总样本数。
    - train_sample_count：实际参与训练的样本数。
    - input_size：实际训练输入尺寸。
    - batch_size：实际训练 batch size。
    - max_epochs：实际训练 epoch 数。
    - device：实际训练使用的 device。
    - gpu_count：实际参与训练的 GPU 数量。
    - device_ids：实际参与训练的 GPU 编号列表。
    - distributed_mode：当前训练的设备并行模式。
    - precision：实际训练使用的 precision。
    - validation_split_name：当前训练使用的验证 split 名称。
    - validation_sample_count：实际参与验证的样本数。
    - parameter_count：模型参数总量。
    """

    checkpoint_bytes: bytes
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    warm_start_summary: dict[str, object]
    implementation_mode: str
    best_metric_name: str
    best_metric_value: float
    evaluation_interval: int
    category_names: tuple[str, ...]
    split_names: tuple[str, ...]
    sample_count: int
    train_sample_count: int
    input_size: tuple[int, int]
    batch_size: int
    max_epochs: int
    device: str
    gpu_count: int
    device_ids: tuple[int, ...]
    distributed_mode: str
    precision: str
    validation_split_name: str | None
    validation_sample_count: int
    parameter_count: int


@dataclass(frozen=True)
class YoloXTrainingEpochProgress:
    """描述单轮训练结束后的进度快照。

    字段：
    - epoch：当前完成的 epoch 序号。
    - max_epochs：本次训练总 epoch 数。
    - evaluation_interval：真实验证评估周期。
    - validation_ran：当前轮是否执行了真实验证评估。
    - evaluated_epochs：截至当前轮已执行真实验证评估的 epoch 列表。
    - train_metrics：当前轮训练指标摘要。
    - validation_metrics：当前轮验证指标摘要。
    - train_metrics_snapshot：当前轮结束后形成的完整训练指标快照。
    - validation_snapshot：当前轮评估完成后形成的完整验证快照；未执行评估时为空。
    - current_metric_name：当前用于比较的指标名。
    - current_metric_value：当前轮该指标值；当前轮未执行评估时为空。
    - best_metric_name：当前最佳指标名。
    - best_metric_value：截至当前轮的最佳指标值；首次评估前为空。
    """

    epoch: int
    max_epochs: int
    evaluation_interval: int
    validation_ran: bool
    evaluated_epochs: tuple[int, ...]
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    train_metrics_snapshot: dict[str, object]
    validation_snapshot: dict[str, object] | None
    current_metric_name: str
    current_metric_value: float | None
    best_metric_name: str
    best_metric_value: float | None


@dataclass(frozen=True)
class YoloXTrainingControlCommand:
    """描述单轮训练结束后由上层返回给训练循环的控制命令。

    字段：
    - save_checkpoint：是否在当前 epoch 边界生成并交付 savepoint。
    - pause_training：是否在交付 savepoint 后暂停训练。
    """

    save_checkpoint: bool = False
    pause_training: bool = False


@dataclass(frozen=True)
class YoloXTrainingSavePoint:
    """描述训练在某个 epoch 边界导出的可恢复 savepoint。

    字段：
    - epoch：当前 savepoint 对应的已完成 epoch。
    - latest_checkpoint_bytes：用于继续训练的 latest checkpoint 二进制内容。
    - best_checkpoint_bytes：当前 best checkpoint 二进制内容；在尚未产生 best checkpoint 时为空。
    - best_metric_name：当前最佳指标名称。
    - best_metric_value：当前最佳指标值；尚未产生时为空。
    """

    epoch: int
    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes | None = None
    best_metric_name: str = ""
    best_metric_value: float | None = None


@dataclass(frozen=True)
class _YoloXTrainingImports:
    """描述最小训练执行所需的第三方依赖对象。"""

    cv2: Any
    np: Any
    torch: Any
    TrainTransform: Any
    YOLOPAFPN: Any
    YOLOX: Any
    YOLOXHead: Any
    LRScheduler: Any
    postprocess: Any
    COCO: Any
    COCOeval: Any


@dataclass(frozen=True)
class _ResolvedCocoSplit:
    """描述一个已经解析到本地绝对路径的 COCO split。"""

    name: str
    image_root: Path
    annotation_file: Path
    sample_count: int


@dataclass(frozen=True)
class _ResolvedCocoSample:
    """描述一个训练样本的原始 COCO 信息。"""

    image_path: Path
    width: int
    height: int
    image_id: int
    boxes_xyxy_with_class: list[tuple[float, float, float, float, float]]


@dataclass(frozen=True)
class _ResolvedTrainingRuntime:
    """描述当前训练请求解析后的运行时资源。

    字段：
    - device：训练主 device。
    - gpu_count：实际参与训练的 GPU 数量。
    - device_ids：实际参与训练的 GPU 编号列表。
    - distributed_mode：当前训练的设备并行模式。
    """

    device: str
    gpu_count: int
    device_ids: tuple[int, ...]
    distributed_mode: str


@dataclass(frozen=True)
class _LoadedResumeState:
    """描述从 latest checkpoint 解析出的恢复训练状态。

    字段：
    - resume_epoch：恢复前已经完成的 epoch 数。
    - epoch_history：恢复前累计的训练指标轨迹。
    - validation_history：恢复前累计的验证指标轨迹。
    - best_metric_name：恢复前记录的最佳指标名称。
    - best_metric_value：恢复前记录的最佳指标值。
    - best_checkpoint_state：恢复前缓存的 best checkpoint 状态；为空时表示尚未产生。
    - warm_start_summary：恢复后继续沿用的 warm start 摘要。
    """

    resume_epoch: int
    epoch_history: list[dict[str, object]]
    validation_history: list[dict[str, object]]
    best_metric_name: str
    best_metric_value: float | None
    best_checkpoint_state: dict[str, object] | None
    warm_start_summary: dict[str, object]


class YoloXTrainingPausedError(Exception):
    """表示训练在 epoch 边界按请求完成保存后进入 paused 状态。"""

    def __init__(self, savepoint: YoloXTrainingSavePoint) -> None:
        """初始化暂停异常。

        参数：
        - savepoint：暂停前最后一次导出的 savepoint。
        """

        super().__init__("yolox training paused")
        self.savepoint = savepoint


YOLOX_MINIMAL_IMPLEMENTATION_MODE = "yolox-detection-minimal"
YOLOX_MINIMAL_DEFAULT_INPUT_SIZE = (640, 640)
YOLOX_MINIMAL_DEFAULT_BATCH_SIZE = 1
YOLOX_MINIMAL_DEFAULT_MAX_EPOCHS = 1
YOLOX_MINIMAL_DEFAULT_EVALUATION_INTERVAL = 5
YOLOX_MINIMAL_DEFAULT_EVAL_CONFIDENCE_THRESHOLD = 0.01
YOLOX_MINIMAL_DEFAULT_EVAL_NMS_THRESHOLD = 0.65

YOLOX_SCALE_PROFILES: dict[str, YoloXScaleProfile] = {
    "nano": YoloXScaleProfile(depth=0.33, width=0.25, depthwise=True),
    "tiny": YoloXScaleProfile(depth=0.33, width=0.375),
    "s": YoloXScaleProfile(depth=0.33, width=0.5),
    "m": YoloXScaleProfile(depth=0.67, width=0.75),
    "l": YoloXScaleProfile(depth=1.0, width=1.0),
    "x": YoloXScaleProfile(depth=1.33, width=1.25),
}
YOLOX_SUPPORTED_MODEL_SCALES = tuple(YOLOX_SCALE_PROFILES.keys())


class _CocoDetectionExportDataset:
    """从 coco-detection-v1 导出目录读取最小训练样本。"""

    def __init__(
        self,
        *,
        annotation_file: Path,
        image_root: Path,
        input_size: tuple[int, int],
        imports: _YoloXTrainingImports,
        flip_prob: float,
        hsv_prob: float,
        max_labels: int,
    ) -> None:
        """初始化最小 COCO detection 数据集。

        参数：
        - annotation_file：COCO annotation JSON 绝对路径。
        - image_root：当前 split 的图片目录绝对路径。
        - input_size：训练输入尺寸。
        - imports：YOLOX 训练依赖对象集合。
        - flip_prob：翻转增强概率。
        - hsv_prob：HSV 增强概率。
        - max_labels：单张图片允许的最大标签数。
        """

        self.annotation_file = annotation_file
        self.image_root = image_root
        self.input_size = input_size
        self.imports = imports
        self.preproc = imports.TrainTransform(
            max_labels=max_labels,
            flip_prob=flip_prob,
            hsv_prob=hsv_prob,
        )

        payload = json.loads(annotation_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise InvalidRequestError(
                "COCO annotation 文件内容不合法",
                details={"annotation_file": annotation_file.as_posix()},
            )

        categories_payload = payload.get("categories", [])
        images_payload = payload.get("images", [])
        annotations_payload = payload.get("annotations", [])
        if not isinstance(categories_payload, list):
            raise InvalidRequestError("COCO categories 必须是数组")
        if not isinstance(images_payload, list):
            raise InvalidRequestError("COCO images 必须是数组")
        if not isinstance(annotations_payload, list):
            raise InvalidRequestError("COCO annotations 必须是数组")

        self.category_names = tuple(
            str(category_item.get("name", "")).strip()
            for category_item in categories_payload
            if isinstance(category_item, dict) and str(category_item.get("name", "")).strip()
        )
        self.category_ids = tuple(
            int(category_item.get("id"))
            for category_item in categories_payload
            if isinstance(category_item, dict) and isinstance(category_item.get("id"), int)
        )
        category_id_to_index = self._build_category_id_to_index(categories_payload)
        annotations_by_image_id = self._build_annotations_by_image_id(
            annotations_payload,
            category_id_to_index,
        )
        self.samples = self._build_samples(images_payload, annotations_by_image_id)

    def __len__(self) -> int:
        """返回当前训练数据集的样本数量。"""

        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[object, object, tuple[int, int], int]:
        """读取单条样本并执行最小 YOLOX 预处理。

        参数：
        - index：样本索引。

        返回：
        - 预处理后的图片、标签、原图尺寸和 image_id。
        """

        sample = self.samples[index]
        image = self.imports.cv2.imread(str(sample.image_path))
        if image is None:
            raise InvalidRequestError(
                "训练图片读取失败",
                details={"image_path": sample.image_path.as_posix()},
            )

        targets = self.imports.np.array(sample.boxes_xyxy_with_class, dtype=self.imports.np.float32)
        if targets.size == 0:
            targets = self.imports.np.zeros((0, 5), dtype=self.imports.np.float32)

        transformed_image, transformed_targets = self.preproc(image, targets, self.input_size)
        return transformed_image, transformed_targets, (sample.height, sample.width), sample.image_id

    def _build_category_id_to_index(
        self,
        categories_payload: list[object],
    ) -> dict[int, int]:
        """构建 COCO category_id 到连续训练索引的映射。"""

        category_id_to_index: dict[int, int] = {}
        for category_index, category_item in enumerate(categories_payload):
            if not isinstance(category_item, dict):
                continue
            raw_category_id = category_item.get("id")
            if not isinstance(raw_category_id, int):
                raise InvalidRequestError("COCO category.id 必须是整数")
            category_id_to_index[raw_category_id] = category_index

        if not category_id_to_index:
            raise InvalidRequestError("训练输入缺少有效的 categories")
        return category_id_to_index

    def _build_annotations_by_image_id(
        self,
        annotations_payload: list[object],
        category_id_to_index: dict[int, int],
    ) -> dict[int, list[tuple[float, float, float, float, float]]]:
        """把 COCO annotations 整理为按 image_id 分组的边界框列表。"""

        annotations_by_image_id: dict[int, list[tuple[float, float, float, float, float]]] = {}
        for annotation_item in annotations_payload:
            if not isinstance(annotation_item, dict):
                continue
            raw_image_id = annotation_item.get("image_id")
            raw_category_id = annotation_item.get("category_id")
            raw_bbox = annotation_item.get("bbox")
            if not isinstance(raw_image_id, int):
                raise InvalidRequestError("COCO annotation.image_id 必须是整数")
            if not isinstance(raw_category_id, int):
                raise InvalidRequestError("COCO annotation.category_id 必须是整数")
            if raw_category_id not in category_id_to_index:
                raise InvalidRequestError(
                    "COCO annotation 引用了未定义的 category_id",
                    details={"category_id": raw_category_id},
                )
            if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
                raise InvalidRequestError("COCO annotation.bbox 必须是长度为 4 的数组")

            x, y, width, height = (float(value) for value in raw_bbox)
            if width <= 0 or height <= 0:
                continue
            annotations_by_image_id.setdefault(raw_image_id, []).append(
                (
                    x,
                    y,
                    x + width,
                    y + height,
                    float(category_id_to_index[raw_category_id]),
                )
            )

        return annotations_by_image_id

    def _build_samples(
        self,
        images_payload: list[object],
        annotations_by_image_id: dict[int, list[tuple[float, float, float, float, float]]],
    ) -> tuple[_ResolvedCocoSample, ...]:
        """把 COCO images 与 annotations 整理成可直接训练的样本列表。"""

        samples: list[_ResolvedCocoSample] = []
        for image_item in images_payload:
            if not isinstance(image_item, dict):
                continue
            raw_image_id = image_item.get("id")
            raw_file_name = image_item.get("file_name")
            raw_width = image_item.get("width")
            raw_height = image_item.get("height")
            if not isinstance(raw_image_id, int):
                raise InvalidRequestError("COCO image.id 必须是整数")
            if not isinstance(raw_file_name, str) or not raw_file_name.strip():
                raise InvalidRequestError("COCO image.file_name 不能为空")
            if not isinstance(raw_width, int) or raw_width <= 0:
                raise InvalidRequestError("COCO image.width 必须是正整数")
            if not isinstance(raw_height, int) or raw_height <= 0:
                raise InvalidRequestError("COCO image.height 必须是正整数")

            image_path = self.image_root.joinpath(*PurePosixPath(raw_file_name).parts)
            if not image_path.is_file():
                raise InvalidRequestError(
                    "训练图片不存在",
                    details={"image_path": image_path.as_posix()},
                )

            samples.append(
                _ResolvedCocoSample(
                    image_path=image_path,
                    width=raw_width,
                    height=raw_height,
                    image_id=raw_image_id,
                    boxes_xyxy_with_class=list(annotations_by_image_id.get(raw_image_id, [])),
                )
            )

        if not samples:
            raise InvalidRequestError("训练输入缺少有效图片样本")
        return tuple(samples)


def run_yolox_detection_training(
    request: YoloXDetectionTrainingExecutionRequest,
) -> YoloXDetectionTrainingExecutionResult:
    """执行最小可跑通的 YOLOX detection 训练链路。

    参数：
    - request：训练执行请求。

    返回：
    - 训练执行结果。
    """

    imports = _require_training_imports()
    manifest_payload = dict(request.manifest_payload)
    resolved_splits = _resolve_coco_splits(request.dataset_storage, manifest_payload)
    train_split = _resolve_train_split(resolved_splits)
    input_size = _resolve_input_size(request.input_size)
    batch_size = max(1, request.batch_size or YOLOX_MINIMAL_DEFAULT_BATCH_SIZE)
    max_epochs = max(1, request.max_epochs or YOLOX_MINIMAL_DEFAULT_MAX_EPOCHS)
    extra_options = dict(request.extra_options or {})
    evaluation_interval = max(
        1,
        request.evaluation_interval
        or _read_int_option(
            extra_options,
            "evaluation_interval",
            default=YOLOX_MINIMAL_DEFAULT_EVALUATION_INTERVAL,
        ),
    )
    runtime = _resolve_training_runtime(
        imports=imports,
        requested_gpu_count=request.gpu_count,
        extra_options=extra_options,
    )
    precision = _resolve_precision(
        imports=imports,
        requested_precision=request.precision,
        device=runtime.device,
        extra_options=extra_options,
    )
    flip_prob = _read_float_option(extra_options, "flip_prob", default=0.0)
    hsv_prob = _read_float_option(extra_options, "hsv_prob", default=0.0)
    max_labels = _read_int_option(extra_options, "max_labels", default=50)
    num_workers = _read_int_option(extra_options, "num_workers", default=0)
    random_seed = _read_int_option(extra_options, "seed", default=0)
    evaluation_confidence_threshold = _read_float_option(
        extra_options,
        "evaluation_confidence_threshold",
        default=YOLOX_MINIMAL_DEFAULT_EVAL_CONFIDENCE_THRESHOLD,
    )
    evaluation_nms_threshold = _read_float_option(
        extra_options,
        "evaluation_nms_threshold",
        default=YOLOX_MINIMAL_DEFAULT_EVAL_NMS_THRESHOLD,
    )
    imports.torch.manual_seed(random_seed)
    if runtime.device.startswith("cuda"):
        imports.torch.cuda.manual_seed_all(random_seed)

    train_dataset = _CocoDetectionExportDataset(
        annotation_file=train_split.annotation_file,
        image_root=train_split.image_root,
        input_size=input_size,
        imports=imports,
        flip_prob=flip_prob,
        hsv_prob=hsv_prob,
        max_labels=max_labels,
    )
    train_loader = imports.torch.utils.data.DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=runtime.device.startswith("cuda"),
        drop_last=False,
    )
    if len(train_loader) == 0:
        raise InvalidRequestError("训练输入中没有可消费的 batch")

    validation_split = _resolve_validation_split(
        resolved_splits,
        train_split_name=train_split.name,
    )
    validation_dataset: _CocoDetectionExportDataset | None = None
    validation_loader = None
    warm_start_summary: dict[str, object] = {"enabled": False}
    resume_state: _LoadedResumeState | None = None
    if validation_split is not None:
        validation_dataset = _CocoDetectionExportDataset(
            annotation_file=validation_split.annotation_file,
            image_root=validation_split.image_root,
            input_size=input_size,
            imports=imports,
            flip_prob=0.0,
            hsv_prob=0.0,
            max_labels=max_labels,
        )
        validation_loader = imports.torch.utils.data.DataLoader(
            validation_dataset,
            batch_size=batch_size,
            shuffle=False,
            num_workers=num_workers,
            pin_memory=runtime.device.startswith("cuda"),
            drop_last=False,
        )
    validation_split_name = validation_split.name if validation_split is not None else None

    base_model = _build_yolox_model(
        imports=imports,
        model_scale=request.model_scale,
        num_classes=len(train_dataset.category_names),
    )
    if request.resume_checkpoint_path is None and request.warm_start_checkpoint_path is not None:
        warm_start_summary = _load_warm_start_checkpoint(
            imports=imports,
            model=base_model,
            checkpoint_path=request.warm_start_checkpoint_path,
            source_summary=dict(request.warm_start_source_summary or {}),
        )
    base_model.to(runtime.device)
    optimizer = _build_optimizer(imports=imports, model=base_model, batch_size=batch_size)
    if request.resume_checkpoint_path is not None:
        resume_state = _load_resume_checkpoint(
            imports=imports,
            model=base_model,
            optimizer=optimizer,
            checkpoint_path=request.resume_checkpoint_path,
            expected_category_names=train_dataset.category_names,
            expected_model_scale=request.model_scale,
            expected_input_size=input_size,
            expected_precision=precision,
            expected_validation_split_name=validation_split_name,
            expected_evaluation_interval=evaluation_interval,
            expected_evaluation_confidence_threshold=(
                evaluation_confidence_threshold if validation_loader is not None else None
            ),
            expected_evaluation_nms_threshold=(
                evaluation_nms_threshold if validation_loader is not None else None
            ),
        )
        warm_start_summary = dict(resume_state.warm_start_summary)
        if resume_state.resume_epoch >= max_epochs:
            raise InvalidRequestError(
                "resume checkpoint 已经达到当前任务的最大 epoch，不能继续训练",
                details={
                    "resume_epoch": resume_state.resume_epoch,
                    "max_epochs": max_epochs,
                },
            )
    training_model = base_model
    if runtime.distributed_mode == "data-parallel":
        training_model = imports.torch.nn.DataParallel(
            base_model,
            device_ids=list(runtime.device_ids),
        )
    training_model.train()
    parameter_count = sum(parameter.numel() for parameter in base_model.parameters())
    scheduler = imports.LRScheduler(
        "yoloxwarmcos",
        (0.01 / 64.0) * batch_size,
        len(train_loader),
        max_epochs,
        warmup_epochs=0,
        warmup_lr_start=0,
        no_aug_epochs=0,
        min_lr_ratio=0.1,
    )
    use_fp16 = precision == "fp16" and runtime.device.startswith("cuda")
    grad_scaler_device = "cuda" if runtime.device.startswith("cuda") else "cpu"
    grad_scaler = imports.torch.amp.GradScaler(grad_scaler_device, enabled=use_fp16)

    total_sample_count = sum(split.sample_count for split in resolved_splits)
    train_sample_count = len(train_dataset)
    validation_sample_count = len(validation_dataset) if validation_dataset is not None else 0
    epoch_history: list[dict[str, object]] = []
    validation_epoch_history: list[dict[str, object]] = []
    best_metric_name = "val_map50_95" if validation_loader is not None else "train_total_loss"
    best_metric_value: float | None = None if validation_loader is not None else float("inf")
    best_checkpoint_state: dict[str, object] | None = None
    start_epoch = 0
    if resume_state is not None:
        epoch_history = [dict(item) for item in resume_state.epoch_history]
        validation_epoch_history = [dict(item) for item in resume_state.validation_history]
        best_metric_name = resume_state.best_metric_name or best_metric_name
        best_metric_value = resume_state.best_metric_value
        best_checkpoint_state = (
            dict(resume_state.best_checkpoint_state)
            if resume_state.best_checkpoint_state is not None
            else None
        )
        start_epoch = max(0, resume_state.resume_epoch)
    global_iter = start_epoch * len(train_loader)
    for epoch_index in range(start_epoch, max_epochs):
        epoch_totals: dict[str, float] = {}
        epoch_iterations = 0
        for images, targets, _image_infos, _image_ids in train_loader:
            optimizer.zero_grad(set_to_none=True)
            images = images.to(device=runtime.device, dtype=imports.torch.float32)
            targets = targets.to(device=runtime.device, dtype=imports.torch.float32)

            with _build_autocast_context(
                imports=imports,
                device=runtime.device,
                precision=precision,
            ):
                outputs = training_model(images, targets)
                total_loss = outputs["total_loss"]

            if use_fp16:
                grad_scaler.scale(total_loss).backward()
                grad_scaler.step(optimizer)
                grad_scaler.update()
            else:
                total_loss.backward()
                optimizer.step()

            learning_rate = scheduler.update_lr(global_iter + 1)
            for param_group in optimizer.param_groups:
                param_group["lr"] = learning_rate

            global_iter += 1
            epoch_iterations += 1
            scalar_outputs = _convert_training_outputs(outputs)
            scalar_outputs["lr"] = float(learning_rate)
            for metric_name, metric_value in scalar_outputs.items():
                if metric_name == "lr":
                    target_metric_name = metric_name
                else:
                    target_metric_name = f"train_{metric_name}"
                epoch_totals[target_metric_name] = (
                    epoch_totals.get(target_metric_name, 0.0) + metric_value
                )

        epoch_metrics = {
            metric_name: metric_total / epoch_iterations
            for metric_name, metric_total in epoch_totals.items()
        }
        validation_metrics: dict[str, float] = {}
        validation_ran = False
        validation_snapshot: dict[str, object] | None = None
        if validation_loader is not None:
            validation_ran = _should_run_validation_evaluation(
                epoch=epoch_index + 1,
                max_epochs=max_epochs,
                evaluation_interval=evaluation_interval,
            )
            if validation_ran:
                validation_metrics = _evaluate_validation_losses(
                    imports=imports,
                    model=training_model,
                    loader=validation_loader,
                    device=runtime.device,
                    precision=precision,
                )
                validation_metrics.update(
                    _evaluate_validation_map(
                        imports=imports,
                        model=training_model,
                        loader=validation_loader,
                        device=runtime.device,
                        precision=precision,
                        input_size=input_size,
                        num_classes=len(train_dataset.category_names),
                        category_ids=validation_dataset.category_ids if validation_dataset is not None else (),
                        annotation_file=(
                            validation_split.annotation_file
                            if validation_split is not None
                            else train_split.annotation_file
                        ),
                        conf_threshold=evaluation_confidence_threshold,
                        nms_threshold=evaluation_nms_threshold,
                    )
                )
            for metric_name, metric_value in validation_metrics.items():
                epoch_metrics[f"val_{metric_name}"] = metric_value
        epoch_metrics["epoch"] = epoch_index + 1
        epoch_history.append(epoch_metrics)

        current_metric_value: float | None = None
        raw_current_metric_value = epoch_metrics.get(best_metric_name)
        if isinstance(raw_current_metric_value, int | float):
            current_metric_value = float(raw_current_metric_value)
        if current_metric_value is not None and _is_metric_improved(
            current_metric_value=current_metric_value,
            best_metric_value=best_metric_value,
            higher_is_better=validation_loader is not None,
        ):
            best_metric_value = current_metric_value
            best_checkpoint_state = _build_checkpoint_state(
                model=base_model,
                optimizer=optimizer,
                epoch=epoch_index + 1,
                metric_name=best_metric_name,
                metric_value=current_metric_value,
                category_names=train_dataset.category_names,
                model_scale=request.model_scale,
                input_size=input_size,
                precision=precision,
                gpu_count=runtime.gpu_count,
                device_ids=runtime.device_ids,
                checkpoint_kind="best",
                validation_split_name=validation_split_name,
                evaluation_interval=(
                    evaluation_interval if validation_loader is not None else None
                ),
                evaluation_confidence_threshold=(
                    evaluation_confidence_threshold if validation_loader is not None else None
                ),
                evaluation_nms_threshold=(
                    evaluation_nms_threshold if validation_loader is not None else None
                ),
            )

        if validation_ran:
            validation_epoch_history.append(
                {
                    "epoch": epoch_index + 1,
                    **dict(validation_metrics),
                }
            )
            validation_snapshot = _build_validation_metrics_payload(
                enabled=True,
                split_name=validation_split.name if validation_split is not None else None,
                sample_count=len(validation_dataset) if validation_dataset is not None else 0,
                evaluation_interval=evaluation_interval,
                confidence_threshold=evaluation_confidence_threshold,
                nms_threshold=evaluation_nms_threshold,
                best_metric_name="map50_95",
                best_metric_value=best_metric_value,
                validation_history=validation_epoch_history,
            )

        train_metrics_snapshot = _build_train_metrics_payload(
            device=runtime.device,
            gpu_count=runtime.gpu_count,
            device_ids=runtime.device_ids,
            distributed_mode=runtime.distributed_mode,
            precision=precision,
            batch_size=batch_size,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
            input_size=input_size,
            train_split_name=train_split.name,
            validation_split_name=validation_split_name,
            sample_count=total_sample_count,
            train_sample_count=train_sample_count,
            validation_sample_count=validation_sample_count,
            category_names=train_dataset.category_names,
            best_metric_name=best_metric_name,
            best_metric_value=best_metric_value,
            final_metrics=epoch_metrics,
            epoch_history=epoch_history,
            parameter_count=int(parameter_count),
            warm_start_summary=warm_start_summary,
        )

        control_command = None
        if request.epoch_callback is not None:
            control_command = request.epoch_callback(
                YoloXTrainingEpochProgress(
                    epoch=epoch_index + 1,
                    max_epochs=max_epochs,
                    evaluation_interval=evaluation_interval,
                    validation_ran=validation_ran,
                    evaluated_epochs=tuple(
                        current_epoch_metrics["epoch"]
                        for current_epoch_metrics in validation_epoch_history
                        if isinstance(current_epoch_metrics.get("epoch"), int)
                    ),
                    train_metrics=_extract_train_progress_metrics(epoch_metrics),
                    validation_metrics=dict(validation_metrics),
                    train_metrics_snapshot=dict(train_metrics_snapshot),
                    validation_snapshot=(
                        dict(validation_snapshot) if validation_snapshot is not None else None
                    ),
                    current_metric_name=best_metric_name,
                    current_metric_value=current_metric_value,
                    best_metric_name=best_metric_name,
                    best_metric_value=best_metric_value,
                )
            )

        if control_command is not None and (
            control_command.save_checkpoint or control_command.pause_training
        ):
            latest_checkpoint_state = _build_checkpoint_state(
                model=base_model,
                optimizer=optimizer,
                epoch=epoch_index + 1,
                metric_name=best_metric_name,
                metric_value=(
                    float(current_metric_value)
                    if current_metric_value is not None
                    else float(best_metric_value or 0.0)
                ),
                category_names=train_dataset.category_names,
                model_scale=request.model_scale,
                input_size=input_size,
                precision=precision,
                gpu_count=runtime.gpu_count,
                device_ids=runtime.device_ids,
                checkpoint_kind="latest",
                validation_split_name=validation_split_name,
                evaluation_interval=(
                    evaluation_interval if validation_loader is not None else None
                ),
                evaluation_confidence_threshold=(
                    evaluation_confidence_threshold if validation_loader is not None else None
                ),
                evaluation_nms_threshold=(
                    evaluation_nms_threshold if validation_loader is not None else None
                ),
                epoch_history=epoch_history,
                validation_history=validation_epoch_history,
                best_metric_name=best_metric_name,
                best_metric_value=best_metric_value,
                warm_start_summary=warm_start_summary,
                best_checkpoint_state=best_checkpoint_state,
            )
            savepoint = YoloXTrainingSavePoint(
                epoch=epoch_index + 1,
                latest_checkpoint_bytes=_serialize_checkpoint_bytes(
                    imports=imports,
                    checkpoint_state=latest_checkpoint_state,
                ),
                best_checkpoint_bytes=(
                    _serialize_checkpoint_bytes(
                        imports=imports,
                        checkpoint_state=best_checkpoint_state,
                    )
                    if best_checkpoint_state is not None
                    else None
                ),
                best_metric_name=best_metric_name,
                best_metric_value=best_metric_value,
            )
            if request.savepoint_callback is not None:
                request.savepoint_callback(savepoint)
            if control_command.pause_training:
                raise YoloXTrainingPausedError(savepoint)

    if best_checkpoint_state is None or best_metric_value is None:
        raise ServiceConfigurationError("YOLOX 训练没有生成有效 checkpoint")

    final_metrics = dict(epoch_history[-1]) if epoch_history else {}
    raw_final_metric_value = final_metrics.get(best_metric_name)
    if isinstance(raw_final_metric_value, int | float):
        final_metric_value = float(raw_final_metric_value)
    else:
        final_metric_value = float(best_metric_value)
    latest_checkpoint_state = _build_checkpoint_state(
        model=base_model,
        optimizer=optimizer,
        epoch=max_epochs,
        metric_name=best_metric_name,
        metric_value=final_metric_value,
        category_names=train_dataset.category_names,
        model_scale=request.model_scale,
        input_size=input_size,
        precision=precision,
        gpu_count=runtime.gpu_count,
        device_ids=runtime.device_ids,
        checkpoint_kind="latest",
        validation_split_name=validation_split_name,
        evaluation_interval=(evaluation_interval if validation_loader is not None else None),
        evaluation_confidence_threshold=(
            evaluation_confidence_threshold if validation_loader is not None else None
        ),
        evaluation_nms_threshold=(
            evaluation_nms_threshold if validation_loader is not None else None
        ),
    )

    checkpoint_buffer = io.BytesIO()
    imports.torch.save(best_checkpoint_state, checkpoint_buffer)
    checkpoint_bytes = checkpoint_buffer.getvalue()
    latest_checkpoint_buffer = io.BytesIO()
    imports.torch.save(latest_checkpoint_state, latest_checkpoint_buffer)
    latest_checkpoint_bytes = latest_checkpoint_buffer.getvalue()
    validation_metrics_payload = _build_validation_metrics_payload(
        enabled=validation_loader is not None,
        split_name=validation_split.name if validation_split is not None else None,
        sample_count=len(validation_dataset) if validation_dataset is not None else 0,
        evaluation_interval=evaluation_interval if validation_loader is not None else None,
        confidence_threshold=(
            evaluation_confidence_threshold if validation_loader is not None else None
        ),
        nms_threshold=evaluation_nms_threshold if validation_loader is not None else None,
        best_metric_name="map50_95" if validation_loader is not None else None,
        best_metric_value=best_metric_value if validation_loader is not None else None,
        validation_history=validation_epoch_history,
    )
    metrics_payload = _build_train_metrics_payload(
        device=runtime.device,
        gpu_count=runtime.gpu_count,
        device_ids=runtime.device_ids,
        distributed_mode=runtime.distributed_mode,
        precision=precision,
        batch_size=batch_size,
        max_epochs=max_epochs,
        evaluation_interval=evaluation_interval,
        input_size=input_size,
        train_split_name=train_split.name,
        validation_split_name=validation_split_name,
        sample_count=total_sample_count,
        train_sample_count=train_sample_count,
        validation_sample_count=validation_sample_count,
        category_names=train_dataset.category_names,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        final_metrics=final_metrics,
        epoch_history=epoch_history,
        parameter_count=int(parameter_count),
        warm_start_summary=warm_start_summary,
    )
    return YoloXDetectionTrainingExecutionResult(
        checkpoint_bytes=checkpoint_bytes,
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        metrics_payload=metrics_payload,
        validation_metrics_payload=validation_metrics_payload,
        warm_start_summary=warm_start_summary,
        implementation_mode=YOLOX_MINIMAL_IMPLEMENTATION_MODE,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        evaluation_interval=evaluation_interval,
        category_names=train_dataset.category_names,
        split_names=tuple(split.name for split in resolved_splits),
        sample_count=sum(split.sample_count for split in resolved_splits),
        train_sample_count=len(train_dataset),
        input_size=input_size,
        batch_size=batch_size,
        max_epochs=max_epochs,
        device=runtime.device,
        gpu_count=runtime.gpu_count,
        device_ids=runtime.device_ids,
        distributed_mode=runtime.distributed_mode,
        precision=precision,
        validation_split_name=validation_split.name if validation_split is not None else None,
        validation_sample_count=len(validation_dataset) if validation_dataset is not None else 0,
        parameter_count=int(parameter_count),
    )


def _require_training_imports() -> _YoloXTrainingImports:
    """按需导入训练执行所需的第三方依赖。"""

    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]
        from pycocotools.coco import COCO  # type: ignore[import-not-found]
        from pycocotools.cocoeval import COCOeval  # type: ignore[import-not-found]
        from yolox.data import TrainTransform  # type: ignore[import-not-found]
        from yolox.models import YOLOPAFPN, YOLOX, YOLOXHead  # type: ignore[import-not-found]
        from yolox.utils import LRScheduler, postprocess  # type: ignore[import-not-found]
    except ImportError as error:
        raise ServiceConfigurationError(
            "YOLOX 训练依赖缺失，至少需要 torch、opencv-python、numpy、pycocotools 和 yolox"
        ) from error

    return _YoloXTrainingImports(
        cv2=cv2,
        np=np,
        torch=torch,
        TrainTransform=TrainTransform,
        YOLOPAFPN=YOLOPAFPN,
        YOLOX=YOLOX,
        YOLOXHead=YOLOXHead,
        LRScheduler=LRScheduler,
        postprocess=postprocess,
        COCO=COCO,
        COCOeval=COCOeval,
    )


def _resolve_coco_splits(
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
) -> tuple[_ResolvedCocoSplit, ...]:
    """从 coco-detection-v1 manifest 中解析本地 split 路径。"""

    splits_payload = manifest_payload.get("splits")
    if not isinstance(splits_payload, list):
        raise InvalidRequestError("训练输入 manifest 缺少 splits 定义")

    resolved_splits: list[_ResolvedCocoSplit] = []
    for split_item in splits_payload:
        if not isinstance(split_item, dict):
            continue
        split_name = str(split_item.get("name", "")).strip()
        image_root = str(split_item.get("image_root", "")).strip()
        annotation_file = str(split_item.get("annotation_file", "")).strip()
        sample_count = split_item.get("sample_count", 0)
        if not split_name or not image_root or not annotation_file:
            continue
        resolved_splits.append(
            _ResolvedCocoSplit(
                name=split_name,
                image_root=dataset_storage.resolve(image_root),
                annotation_file=dataset_storage.resolve(annotation_file),
                sample_count=sample_count if isinstance(sample_count, int) else 0,
            )
        )

    if not resolved_splits:
        raise InvalidRequestError("训练输入 manifest 中没有可用的 split")
    return tuple(resolved_splits)


def _resolve_train_split(resolved_splits: tuple[_ResolvedCocoSplit, ...]) -> _ResolvedCocoSplit:
    """优先解析训练链路要使用的 train split。"""

    for split in resolved_splits:
        if split.name == "train":
            return split
    return resolved_splits[0]


def _resolve_validation_split(
    resolved_splits: tuple[_ResolvedCocoSplit, ...],
    *,
    train_split_name: str,
) -> _ResolvedCocoSplit | None:
    """优先解析训练链路要使用的验证 split。

    参数：
    - resolved_splits：当前 manifest 中可用的全部 split。
    - train_split_name：已经选定的训练 split 名称。

    返回：
    - _ResolvedCocoSplit | None：优先返回 val、valid、validation；缺失时回退 test；再缺失时回退第一个非训练 split。
    """

    preferred_validation_names = ("val", "valid", "validation", "test")
    for preferred_name in preferred_validation_names:
        for split in resolved_splits:
            if split.name == preferred_name and split.name != train_split_name:
                return split

    for split in resolved_splits:
        if split.name != train_split_name:
            return split

    return None


def _resolve_input_size(input_size: tuple[int, int] | None) -> tuple[int, int]:
    """解析并校验训练输入尺寸。"""

    resolved_size = input_size or YOLOX_MINIMAL_DEFAULT_INPUT_SIZE
    if resolved_size[0] % 32 != 0 or resolved_size[1] % 32 != 0:
        raise InvalidRequestError("YOLOX 训练输入尺寸必须是 32 的倍数")
    return resolved_size


def _resolve_training_runtime(
    *,
    imports: _YoloXTrainingImports,
    requested_gpu_count: int | None,
    extra_options: dict[str, object],
) -> _ResolvedTrainingRuntime:
    """解析当前训练应使用的设备资源。"""

    requested_device = _read_str_option(extra_options, "device")
    if requested_device == "cpu":
        if requested_gpu_count is not None:
            raise InvalidRequestError("CPU 训练不能同时指定 gpu_count")
        return _ResolvedTrainingRuntime(
            device="cpu",
            gpu_count=0,
            device_ids=(),
            distributed_mode="single-device",
        )

    if not imports.torch.cuda.is_available():
        if requested_gpu_count is not None:
            raise InvalidRequestError("当前运行环境没有可用 GPU，不能指定 gpu_count")
        return _ResolvedTrainingRuntime(
            device="cpu",
            gpu_count=0,
            device_ids=(),
            distributed_mode="single-device",
        )

    available_gpu_count = int(imports.torch.cuda.device_count())
    gpu_count = requested_gpu_count or _read_int_option(extra_options, "gpu_count", default=1)
    if gpu_count < 1:
        raise InvalidRequestError("gpu_count 必须大于 0")
    if gpu_count > available_gpu_count:
        raise InvalidRequestError(
            "指定的 gpu_count 超过了本机可用 GPU 数量",
            details={
                "requested_gpu_count": gpu_count,
                "available_gpu_count": available_gpu_count,
            },
        )

    start_device_index = 0
    if requested_device is not None and requested_device.startswith("cuda:"):
        raw_device_index = requested_device.split(":", 1)[1]
        if not raw_device_index.isdigit():
            raise InvalidRequestError(
                "device 必须是 cpu、cuda 或 cuda:<index>",
                details={"device": requested_device},
            )
        start_device_index = int(raw_device_index)
        if start_device_index + gpu_count > available_gpu_count:
            raise InvalidRequestError(
                "指定的 device 和 gpu_count 超出了本机可用 GPU 范围",
                details={
                    "device": requested_device,
                    "requested_gpu_count": gpu_count,
                    "available_gpu_count": available_gpu_count,
                },
            )

    device_ids = tuple(range(start_device_index, start_device_index + gpu_count))
    distributed_mode = "data-parallel" if gpu_count > 1 else "single-device"
    return _ResolvedTrainingRuntime(
        device=f"cuda:{device_ids[0]}",
        gpu_count=gpu_count,
        device_ids=device_ids,
        distributed_mode=distributed_mode,
    )


def _resolve_precision(
    *,
    imports: _YoloXTrainingImports,
    requested_precision: str | None,
    device: str,
    extra_options: dict[str, object],
) -> str:
    """解析当前训练应使用的 precision。"""

    precision = requested_precision or _read_str_option(extra_options, "precision") or "fp32"
    if precision not in {"fp8", "fp16", "fp32"}:
        raise InvalidRequestError(
            "precision 必须是 fp8、fp16 或 fp32",
            details={"precision": precision},
        )
    if precision == "fp8":
        raise InvalidRequestError("当前最小真实训练暂不支持 fp8，当前可用值为 fp16 或 fp32")
    if precision == "fp16" and not device.startswith("cuda"):
        raise InvalidRequestError("fp16 训练需要 CUDA 环境")
    if precision == "fp16" and not hasattr(imports.torch, "autocast"):
        raise ServiceConfigurationError("当前 torch 版本缺少 autocast，无法执行 fp16 训练")
    return precision


def _build_autocast_context(
    *,
    imports: _YoloXTrainingImports,
    device: str,
    precision: str,
):
    """按当前 precision 构建自动混合精度上下文。"""

    if precision != "fp16" or not device.startswith("cuda"):
        return nullcontext()

    return imports.torch.autocast(device_type="cuda", dtype=imports.torch.float16)


def _read_float_option(extra_options: dict[str, object], key: str, *, default: float) -> float:
    """从 extra_options 中读取可选浮点数。"""

    value = extra_options.get(key)
    if isinstance(value, int | float):
        return float(value)
    return default


def _read_int_option(extra_options: dict[str, object], key: str, *, default: int) -> int:
    """从 extra_options 中读取可选整数。"""

    value = extra_options.get(key)
    if isinstance(value, int):
        return value
    return default


def _read_str_option(extra_options: dict[str, object], key: str) -> str | None:
    """从 extra_options 中读取可选字符串。"""

    value = extra_options.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _build_yolox_model(
    *,
    imports: _YoloXTrainingImports,
    model_scale: str,
    num_classes: int,
):
    """按 model scale 构建最小 YOLOX detection 模型。"""

    scale_profile = YOLOX_SCALE_PROFILES.get(model_scale)
    if scale_profile is None:
        raise InvalidRequestError(
            "当前不支持指定的 YOLOX model_scale",
            details={"model_scale": model_scale},
        )

    in_channels = [256, 512, 1024]
    backbone = imports.YOLOPAFPN(
        scale_profile.depth,
        scale_profile.width,
        in_channels=in_channels,
        act="silu",
        depthwise=scale_profile.depthwise,
    )
    head = imports.YOLOXHead(
        num_classes,
        scale_profile.width,
        in_channels=in_channels,
        act="silu",
        depthwise=scale_profile.depthwise,
    )
    model = imports.YOLOX(backbone, head)

    def init_yolo(module: Any) -> None:
        for current_module in module.modules():
            if isinstance(current_module, imports.torch.nn.BatchNorm2d):
                current_module.eps = 1e-3
                current_module.momentum = 0.03

    model.apply(init_yolo)
    model.head.initialize_biases(1e-2)
    return model


def _load_warm_start_checkpoint(
    *,
    imports: _YoloXTrainingImports,
    model: Any,
    checkpoint_path: Path,
    source_summary: dict[str, object],
) -> dict[str, object]:
    """把 warm start checkpoint 加载到当前模型中。"""

    if not checkpoint_path.is_file():
        raise InvalidRequestError(
            "warm start checkpoint 不存在",
            details={"checkpoint_path": checkpoint_path.as_posix()},
        )

    try:
        checkpoint_payload = imports.torch.load(str(checkpoint_path), map_location="cpu")
    except Exception as error:
        raise ServiceConfigurationError(
            "warm start checkpoint 读取失败",
            details={"checkpoint_path": checkpoint_path.as_posix()},
        ) from error

    raw_state_dict = _extract_checkpoint_state_dict(checkpoint_payload)
    model_state_dict = model.state_dict()
    compatible_state_dict: dict[str, object] = {}
    skipped_shape_keys: list[str] = []
    for key, value in raw_state_dict.items():
        normalized_key = key.removeprefix("module.")
        target_value = model_state_dict.get(normalized_key)
        if target_value is None:
            continue
        if not hasattr(value, "shape"):
            continue
        if tuple(value.shape) != tuple(target_value.shape):
            skipped_shape_keys.append(normalized_key)
            continue
        compatible_state_dict[normalized_key] = value

    if not compatible_state_dict:
        raise InvalidRequestError(
            "warm start checkpoint 与当前模型结构不兼容",
            details={"checkpoint_path": checkpoint_path.as_posix()},
        )

    incompatible_keys = model.load_state_dict(compatible_state_dict, strict=False)
    loaded_parameter_count = sum(
        int(parameter.numel())
        for parameter in compatible_state_dict.values()
        if hasattr(parameter, "numel")
    )
    warm_start_summary = dict(source_summary)
    warm_start_summary.update(
        {
            "enabled": True,
            "checkpoint_path": checkpoint_path.as_posix(),
            "loaded_tensor_count": len(compatible_state_dict),
            "loaded_parameter_count": loaded_parameter_count,
            "missing_key_count": len(incompatible_keys.missing_keys),
            "unexpected_key_count": len(incompatible_keys.unexpected_keys),
            "skipped_shape_key_count": len(skipped_shape_keys),
            "missing_keys_preview": list(incompatible_keys.missing_keys[:10]),
            "unexpected_keys_preview": list(incompatible_keys.unexpected_keys[:10]),
            "skipped_shape_keys_preview": skipped_shape_keys[:10],
        }
    )
    return warm_start_summary


def _load_resume_checkpoint(
    *,
    imports: _YoloXTrainingImports,
    model: Any,
    optimizer: Any,
    checkpoint_path: Path,
    expected_category_names: tuple[str, ...],
    expected_model_scale: str,
    expected_input_size: tuple[int, int],
    expected_precision: str,
    expected_validation_split_name: str | None,
    expected_evaluation_interval: int,
    expected_evaluation_confidence_threshold: float | None,
    expected_evaluation_nms_threshold: float | None,
) -> _LoadedResumeState:
    """从 latest checkpoint 中恢复模型、优化器和训练历史。

    参数：
    - imports：训练依赖对象集合，当前只依赖其中的 torch。
    - model：待恢复参数的模型对象。
    - optimizer：待恢复状态的优化器对象。
    - checkpoint_path：latest checkpoint 的绝对路径。
    - expected_category_names：当前任务期望的类别列表。
    - expected_model_scale：当前任务期望的 model_scale。
    - expected_input_size：当前任务期望的输入尺寸。
    - expected_precision：当前任务期望的 precision。
    - expected_validation_split_name：当前任务期望的 validation split 名称。
    - expected_evaluation_interval：当前任务期望的验证评估周期。
    - expected_evaluation_confidence_threshold：当前任务期望的验证 confidence threshold。
    - expected_evaluation_nms_threshold：当前任务期望的验证 nms threshold。

    返回：
    - 已经完成一致性校验并可继续训练的恢复状态。
    """

    if not checkpoint_path.is_file():
        raise InvalidRequestError(
            "resume checkpoint 不存在",
            details={"checkpoint_path": checkpoint_path.as_posix()},
        )

    try:
        checkpoint_payload = imports.torch.load(str(checkpoint_path), map_location="cpu")
    except Exception as error:
        raise ServiceConfigurationError(
            "resume checkpoint 读取失败",
            details={"checkpoint_path": checkpoint_path.as_posix()},
        ) from error

    if not isinstance(checkpoint_payload, dict):
        raise InvalidRequestError("resume checkpoint 内容不合法")

    model_state = checkpoint_payload.get("model")
    optimizer_state = checkpoint_payload.get("optimizer")
    if not isinstance(model_state, dict) or not isinstance(optimizer_state, dict):
        raise InvalidRequestError("resume checkpoint 缺少模型或优化器状态")

    checkpoint_category_names = checkpoint_payload.get("category_names")
    if isinstance(checkpoint_category_names, list):
        normalized_category_names = tuple(
            item
            for item in checkpoint_category_names
            if isinstance(item, str) and item.strip()
        )
        if normalized_category_names and normalized_category_names != expected_category_names:
            raise InvalidRequestError("resume checkpoint 的类别列表与当前任务不一致")

    checkpoint_model_scale = checkpoint_payload.get("model_scale")
    if isinstance(checkpoint_model_scale, str) and checkpoint_model_scale != expected_model_scale:
        raise InvalidRequestError("resume checkpoint 的 model_scale 与当前任务不一致")

    checkpoint_input_size = checkpoint_payload.get("input_size")
    if (
        isinstance(checkpoint_input_size, list)
        and len(checkpoint_input_size) == 2
        and all(isinstance(item, int) for item in checkpoint_input_size)
        and tuple(checkpoint_input_size) != expected_input_size
    ):
        raise InvalidRequestError("resume checkpoint 的 input_size 与当前任务不一致")

    checkpoint_precision = checkpoint_payload.get("precision")
    if isinstance(checkpoint_precision, str) and checkpoint_precision != expected_precision:
        raise InvalidRequestError("resume checkpoint 的 precision 与当前任务不一致")

    _validate_resume_validation_configuration(
        checkpoint_payload=checkpoint_payload,
        expected_validation_split_name=expected_validation_split_name,
        expected_evaluation_interval=expected_evaluation_interval,
        expected_evaluation_confidence_threshold=expected_evaluation_confidence_threshold,
        expected_evaluation_nms_threshold=expected_evaluation_nms_threshold,
    )

    model.load_state_dict({str(key): value for key, value in model_state.items()}, strict=True)
    optimizer.load_state_dict(optimizer_state)
    _move_optimizer_state_to_device(
        optimizer=optimizer,
        device=str(next(model.parameters()).device),
    )

    resume_epoch = checkpoint_payload.get("epoch")
    if not isinstance(resume_epoch, int) or resume_epoch < 0:
        raise InvalidRequestError("resume checkpoint 缺少有效的 epoch")

    epoch_history = _normalize_history_items(checkpoint_payload.get("epoch_history"))
    validation_history = _normalize_history_items(checkpoint_payload.get("validation_history"))
    best_metric_name = checkpoint_payload.get("best_metric_name")
    if not isinstance(best_metric_name, str) or not best_metric_name.strip():
        metric_name = checkpoint_payload.get("metric_name")
        best_metric_name = metric_name if isinstance(metric_name, str) and metric_name.strip() else ""

    raw_best_metric_value = checkpoint_payload.get("best_metric_value")
    if isinstance(raw_best_metric_value, int | float):
        best_metric_value: float | None = float(raw_best_metric_value)
    else:
        raw_metric_value = checkpoint_payload.get("metric_value")
        best_metric_value = float(raw_metric_value) if isinstance(raw_metric_value, int | float) else None

    raw_best_checkpoint_state = checkpoint_payload.get("best_checkpoint_state")
    best_checkpoint_state = (
        {str(key): value for key, value in raw_best_checkpoint_state.items()}
        if isinstance(raw_best_checkpoint_state, dict)
        else None
    )
    warm_start_summary = checkpoint_payload.get("warm_start_summary")
    return _LoadedResumeState(
        resume_epoch=resume_epoch,
        epoch_history=epoch_history,
        validation_history=validation_history,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        best_checkpoint_state=best_checkpoint_state,
        warm_start_summary=(
            dict(warm_start_summary)
            if isinstance(warm_start_summary, dict)
            else {"enabled": False}
        ),
    )


def _normalize_history_items(history_payload: object) -> list[dict[str, object]]:
    """把 checkpoint 中的历史轨迹载荷规范化为字典列表。"""

    if not isinstance(history_payload, list):
        return []

    normalized_history: list[dict[str, object]] = []
    for item in history_payload:
        if isinstance(item, dict):
            normalized_history.append({str(key): value for key, value in item.items()})
    return normalized_history


def _validate_resume_validation_configuration(
    *,
    checkpoint_payload: dict[str, object],
    expected_validation_split_name: str | None,
    expected_evaluation_interval: int,
    expected_evaluation_confidence_threshold: float | None,
    expected_evaluation_nms_threshold: float | None,
) -> None:
    """校验 resume checkpoint 中记录的 validation 配置是否与当前任务一致。

    参数：
    - checkpoint_payload：已经成功读取的 checkpoint 字典。
    - expected_validation_split_name：当前任务期望的 validation split 名称。
    - expected_evaluation_interval：当前任务期望的验证评估周期。
    - expected_evaluation_confidence_threshold：当前任务期望的验证 confidence threshold。
    - expected_evaluation_nms_threshold：当前任务期望的验证 nms threshold。
    """

    checkpoint_validation_split_name = checkpoint_payload.get("validation_split_name")
    if checkpoint_validation_split_name != expected_validation_split_name:
        raise InvalidRequestError("resume checkpoint 的 validation_split_name 与当前任务不一致")

    if expected_validation_split_name is None:
        return

    checkpoint_evaluation_interval = checkpoint_payload.get("evaluation_interval")
    if (
        not isinstance(checkpoint_evaluation_interval, int)
        or checkpoint_evaluation_interval != expected_evaluation_interval
    ):
        raise InvalidRequestError("resume checkpoint 的 evaluation_interval 与当前任务不一致")

    _assert_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_confidence_threshold"),
        expected_value=expected_evaluation_confidence_threshold,
        field_name="evaluation_confidence_threshold",
    )
    _assert_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_nms_threshold"),
        expected_value=expected_evaluation_nms_threshold,
        field_name="evaluation_nms_threshold",
    )


def _assert_resume_optional_float_matches(
    *,
    checkpoint_value: object,
    expected_value: float | None,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的可选浮点配置与当前任务一致。

    参数：
    - checkpoint_value：checkpoint 中记录的字段值。
    - expected_value：当前任务期望的字段值。
    - field_name：用于报错的字段名称。
    """

    if expected_value is None:
        if checkpoint_value is not None:
            raise InvalidRequestError(f"resume checkpoint 的 {field_name} 与当前任务不一致")
        return

    if not isinstance(checkpoint_value, int | float) or not math.isclose(
        float(checkpoint_value),
        float(expected_value),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise InvalidRequestError(f"resume checkpoint 的 {field_name} 与当前任务不一致")


def _move_optimizer_state_to_device(*, optimizer: Any, device: str) -> None:
    """把恢复后的 optimizer state 张量迁移到当前训练 device。"""

    for state in optimizer.state.values():
        if not isinstance(state, dict):
            continue
        for key, value in list(state.items()):
            if hasattr(value, "to"):
                state[key] = value.to(device=device)


def _serialize_checkpoint_bytes(
    *,
    imports: _YoloXTrainingImports,
    checkpoint_state: dict[str, object],
) -> bytes:
    """把 checkpoint 状态序列化为二进制内容。"""

    checkpoint_buffer = io.BytesIO()
    imports.torch.save(checkpoint_state, checkpoint_buffer)
    return checkpoint_buffer.getvalue()


def _extract_checkpoint_state_dict(checkpoint_payload: object) -> dict[str, object]:
    """从不同 checkpoint 结构中提取可加载的模型参数字典。"""

    if not isinstance(checkpoint_payload, dict):
        raise InvalidRequestError("warm start checkpoint 内容不合法")

    for candidate_key in ("model", "ema_model", "state_dict"):
        candidate_value = checkpoint_payload.get(candidate_key)
        if isinstance(candidate_value, dict):
            return {str(key): value for key, value in candidate_value.items()}

    if all(isinstance(key, str) for key in checkpoint_payload.keys()):
        return {str(key): value for key, value in checkpoint_payload.items()}

    raise InvalidRequestError("warm start checkpoint 缺少可识别的模型参数字典")


def _extract_train_progress_metrics(epoch_metrics: dict[str, object]) -> dict[str, float]:
    """从单轮指标中提取训练阶段进度展示指标。"""

    train_metrics = _extract_prefixed_metrics(epoch_metrics, prefix="train_")
    learning_rate = epoch_metrics.get("lr")
    if isinstance(learning_rate, int | float):
        train_metrics["lr"] = float(learning_rate)
    return train_metrics


def _extract_prefixed_metrics(
    epoch_metrics: dict[str, object],
    *,
    prefix: str,
) -> dict[str, float]:
    """从单轮指标中提取指定前缀的浮点指标。"""

    extracted_metrics: dict[str, float] = {}
    for key, value in epoch_metrics.items():
        if not key.startswith(prefix):
            continue
        if isinstance(value, int | float):
            extracted_metrics[key.removeprefix(prefix)] = float(value)
    return extracted_metrics


def _build_validation_metrics_payload(
    *,
    enabled: bool,
    split_name: str | None,
    sample_count: int,
    evaluation_interval: int | None,
    confidence_threshold: float | None,
    nms_threshold: float | None,
    best_metric_name: str | None,
    best_metric_value: float | None,
    validation_history: list[dict[str, object]],
) -> dict[str, object]:
    """构建验证指标摘要与中间快照负载。"""

    validation_final_metrics = dict(validation_history[-1]) if validation_history else {}
    evaluated_epochs = [
        epoch_metrics["epoch"]
        for epoch_metrics in validation_history
        if isinstance(epoch_metrics.get("epoch"), int)
    ]
    return {
        "enabled": enabled,
        "split_name": split_name,
        "sample_count": sample_count,
        "evaluation_interval": evaluation_interval,
        "confidence_threshold": confidence_threshold,
        "nms_threshold": nms_threshold,
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
        "final_metrics": validation_final_metrics,
        "evaluated_epochs": evaluated_epochs,
        "epoch_history": [dict(item) for item in validation_history],
    }


def _should_run_validation_evaluation(
    *,
    epoch: int,
    max_epochs: int,
    evaluation_interval: int,
) -> bool:
    """判断当前轮是否需要执行真实验证评估。"""

    if epoch >= max_epochs:
        return True
    return epoch % max(1, evaluation_interval) == 0


def _is_metric_improved(
    *,
    current_metric_value: float,
    best_metric_value: float | None,
    higher_is_better: bool,
) -> bool:
    """按指标方向判断当前轮是否刷新最佳结果。"""

    if best_metric_value is None:
        return True
    if higher_is_better:
        return current_metric_value >= best_metric_value
    return current_metric_value <= best_metric_value


def _evaluate_validation_losses(
    *,
    imports: _YoloXTrainingImports,
    model: Any,
    loader: Any,
    device: str,
    precision: str,
) -> dict[str, float]:
    """在不更新参数的前提下执行一次最小验证损失统计。"""

    if len(loader) == 0:
        return {}

    batch_norm_states = _freeze_batch_norm_modules(imports=imports, model=model)
    with imports.torch.no_grad():
        epoch_totals: dict[str, float] = {}
        epoch_iterations = 0
        for images, targets, _image_infos, _image_ids in loader:
            images = images.to(device=device, dtype=imports.torch.float32)
            targets = targets.to(device=device, dtype=imports.torch.float32)
            with _build_autocast_context(
                imports=imports,
                device=device,
                precision=precision,
            ):
                outputs = model(images, targets)
            scalar_outputs = _convert_training_outputs(outputs)
            for metric_name, metric_value in scalar_outputs.items():
                epoch_totals[metric_name] = epoch_totals.get(metric_name, 0.0) + metric_value
            epoch_iterations += 1

    _restore_batch_norm_modules(batch_norm_states)
    return {
        metric_name: metric_total / epoch_iterations
        for metric_name, metric_total in epoch_totals.items()
    }


def _load_coco_ground_truth_silently(*, imports: Any, annotation_file: Path) -> Any:
    """静默加载 COCO ground truth，避免 pycocotools 默认把索引日志打印到 stdout。

    参数：
    - imports：当前训练依赖对象集合，要求提供 COCO 构造器。
    - annotation_file：COCO annotation JSON 绝对路径。

    返回：
    - Any：pycocotools.COCO 实例。
    """

    with redirect_stdout(io.StringIO()):
        return imports.COCO(str(annotation_file))


def _evaluate_validation_map(
    *,
    imports: _YoloXTrainingImports,
    model: Any,
    loader: Any,
    device: str,
    precision: str,
    input_size: tuple[int, int],
    num_classes: int,
    category_ids: tuple[int, ...],
    annotation_file: Path,
    conf_threshold: float,
    nms_threshold: float,
) -> dict[str, float]:
    """执行一次真实 COCO mAP 评估。"""

    if len(loader) == 0:
        return {"map50": 0.0, "map50_95": 0.0}

    was_training = bool(model.training)
    model.eval()
    detections: list[dict[str, object]] = []
    try:
        with imports.torch.no_grad():
            for images, _targets, image_infos, image_ids in loader:
                images = images.to(device=device, dtype=imports.torch.float32)
                with _build_autocast_context(
                    imports=imports,
                    device=device,
                    precision=precision,
                ):
                    raw_outputs = model(images)
                processed_outputs = imports.postprocess(
                    raw_outputs,
                    num_classes,
                    conf_thre=conf_threshold,
                    nms_thre=nms_threshold,
                    class_agnostic=False,
                )
                detections.extend(
                    _convert_predictions_to_coco_detections(
                        predictions=processed_outputs,
                        image_infos=image_infos,
                        image_ids=image_ids,
                        input_size=input_size,
                        category_ids=category_ids,
                    )
                )
    finally:
        model.train(was_training)

    if not detections:
        return {"map50": 0.0, "map50_95": 0.0}

    ground_truth = _load_coco_ground_truth_silently(
        imports=imports,
        annotation_file=annotation_file,
    )
    with redirect_stdout(io.StringIO()):
        coco_detections = ground_truth.loadRes(detections)
        coco_evaluator = imports.COCOeval(ground_truth, coco_detections, "bbox")
        coco_evaluator.evaluate()
        coco_evaluator.accumulate()
        coco_evaluator.summarize()

    return {
        "map50_95": float(coco_evaluator.stats[0]),
        "map50": float(coco_evaluator.stats[1]),
    }


def _convert_predictions_to_coco_detections(
    *,
    predictions: list[object],
    image_infos: object,
    image_ids: object,
    input_size: tuple[int, int],
    category_ids: tuple[int, ...],
) -> list[dict[str, object]]:
    """把 YOLOX 后处理输出转换为 COCO detection 结果。"""

    detections: list[dict[str, object]] = []
    for batch_index, prediction in enumerate(predictions):
        if prediction is None:
            continue
        image_height, image_width = _extract_batch_image_info(image_infos, batch_index)
        image_id = _extract_batch_image_id(image_ids, batch_index)
        resize_ratio = min(
            input_size[0] / max(1.0, float(image_height)),
            input_size[1] / max(1.0, float(image_width)),
        )
        if resize_ratio <= 0:
            continue

        prediction_tensor = prediction.detach().cpu()
        boxes = prediction_tensor[:, 0:4] / resize_ratio
        scores = prediction_tensor[:, 4] * prediction_tensor[:, 5]
        classes = prediction_tensor[:, 6]
        for row_index in range(prediction_tensor.shape[0]):
            class_index = int(classes[row_index].item())
            if class_index < 0 or class_index >= len(category_ids):
                continue

            x1, y1, x2, y2 = boxes[row_index].tolist()
            x1 = max(0.0, min(float(x1), float(image_width)))
            y1 = max(0.0, min(float(y1), float(image_height)))
            x2 = max(0.0, min(float(x2), float(image_width)))
            y2 = max(0.0, min(float(y2), float(image_height)))
            box_width = max(0.0, x2 - x1)
            box_height = max(0.0, y2 - y1)
            if box_width <= 0 or box_height <= 0:
                continue

            detections.append(
                {
                    "image_id": image_id,
                    "category_id": category_ids[class_index],
                    "bbox": [x1, y1, box_width, box_height],
                    "score": float(scores[row_index].item()),
                }
            )
    return detections


def _extract_batch_image_info(image_infos: object, batch_index: int) -> tuple[int, int]:
    """从 DataLoader 合并结果中读取单张图片的原图尺寸。"""

    if (
        isinstance(image_infos, list | tuple)
        and len(image_infos) == 2
        and all(hasattr(item, "__getitem__") for item in image_infos)
    ):
        return int(image_infos[0][batch_index]), int(image_infos[1][batch_index])
    if isinstance(image_infos, list | tuple) and len(image_infos) > batch_index:
        image_info = image_infos[batch_index]
        if isinstance(image_info, list | tuple) and len(image_info) == 2:
            return int(image_info[0]), int(image_info[1])
    raise ServiceConfigurationError("验证批次中的 image_infos 结构不合法")


def _extract_batch_image_id(image_ids: object, batch_index: int) -> int:
    """从 DataLoader 合并结果中读取单张图片的 image_id。"""

    if hasattr(image_ids, "__getitem__"):
        return int(image_ids[batch_index])
    raise ServiceConfigurationError("验证批次中的 image_ids 结构不合法")


def _freeze_batch_norm_modules(
    *,
    imports: _YoloXTrainingImports,
    model: Any,
) -> tuple[tuple[Any, bool], ...]:
    """在验证阶段暂时冻结 BatchNorm 的统计更新。"""

    batch_norm_states: list[tuple[Any, bool]] = []
    for module in model.modules():
        if isinstance(module, imports.torch.nn.BatchNorm2d):
            batch_norm_states.append((module, bool(module.training)))
            module.eval()
    return tuple(batch_norm_states)


def _restore_batch_norm_modules(batch_norm_states: tuple[tuple[Any, bool], ...]) -> None:
    """恢复验证前 BatchNorm 的训练状态。"""

    for module, was_training in batch_norm_states:
        module.train(was_training)


def _build_checkpoint_state(
    *,
    model: Any,
    optimizer: Any,
    epoch: int,
    metric_name: str,
    metric_value: float,
    category_names: tuple[str, ...],
    model_scale: str,
    input_size: tuple[int, int],
    precision: str,
    gpu_count: int,
    device_ids: tuple[int, ...],
    checkpoint_kind: str,
    validation_split_name: str | None = None,
    evaluation_interval: int | None = None,
    evaluation_confidence_threshold: float | None = None,
    evaluation_nms_threshold: float | None = None,
    epoch_history: list[dict[str, object]] | None = None,
    validation_history: list[dict[str, object]] | None = None,
    best_metric_name: str | None = None,
    best_metric_value: float | None = None,
    warm_start_summary: dict[str, object] | None = None,
    best_checkpoint_state: dict[str, object] | None = None,
) -> dict[str, object]:
    """构建一个可直接序列化保存的 checkpoint 状态。

    参数：
    - model：需要保存参数的模型对象。
    - optimizer：需要保存状态的优化器对象。
    - epoch：当前 checkpoint 对应的已完成 epoch。
    - metric_name：当前 checkpoint 使用的指标名称。
    - metric_value：当前 checkpoint 使用的指标值。
    - category_names：当前训练任务的类别列表。
    - model_scale：当前训练任务的 model_scale。
    - input_size：当前训练任务的输入尺寸。
    - precision：当前训练任务的 precision。
    - gpu_count：当前训练任务使用的 GPU 数量。
    - device_ids：当前训练任务使用的 GPU 编号列表。
    - checkpoint_kind：checkpoint 类型，通常为 best 或 latest。
    - validation_split_name：当前训练任务使用的 validation split 名称。
    - evaluation_interval：当前训练任务的验证评估周期。
    - evaluation_confidence_threshold：当前训练任务的验证 confidence threshold。
    - evaluation_nms_threshold：当前训练任务的验证 nms threshold。
    - epoch_history：可选的训练指标轨迹。
    - validation_history：可选的验证指标轨迹。
    - best_metric_name：可选的最佳指标名称。
    - best_metric_value：可选的最佳指标值。
    - warm_start_summary：可选的 warm start 摘要。
    - best_checkpoint_state：可选的最佳 checkpoint 状态。

    返回：
    - 可直接使用 torch.save 序列化的 checkpoint 字典。
    """

    checkpoint_state = {
        "epoch": epoch,
        "model": {
            key: value.detach().cpu()
            for key, value in model.state_dict().items()
        },
        "optimizer": optimizer.state_dict(),
        "metric_name": metric_name,
        "metric_value": metric_value,
        "checkpoint_kind": checkpoint_kind,
        "category_names": list(category_names),
        "model_scale": model_scale,
        "input_size": list(input_size),
        "precision": precision,
        "gpu_count": gpu_count,
        "device_ids": list(device_ids),
        "validation_split_name": validation_split_name,
        "evaluation_interval": evaluation_interval,
        "evaluation_confidence_threshold": evaluation_confidence_threshold,
        "evaluation_nms_threshold": evaluation_nms_threshold,
    }
    if epoch_history is not None:
        checkpoint_state["epoch_history"] = [dict(item) for item in epoch_history]
    if validation_history is not None:
        checkpoint_state["validation_history"] = [dict(item) for item in validation_history]
    if best_metric_name is not None:
        checkpoint_state["best_metric_name"] = best_metric_name
    if best_metric_value is not None:
        checkpoint_state["best_metric_value"] = best_metric_value
    if warm_start_summary is not None:
        checkpoint_state["warm_start_summary"] = dict(warm_start_summary)
    if best_checkpoint_state is not None:
        checkpoint_state["best_checkpoint_state"] = best_checkpoint_state
    return checkpoint_state


def _build_train_metrics_payload(
    *,
    device: str,
    gpu_count: int,
    device_ids: tuple[int, ...],
    distributed_mode: str,
    precision: str,
    batch_size: int,
    max_epochs: int,
    evaluation_interval: int,
    input_size: tuple[int, int],
    train_split_name: str,
    validation_split_name: str | None,
    sample_count: int,
    train_sample_count: int,
    validation_sample_count: int,
    category_names: tuple[str, ...],
    best_metric_name: str,
    best_metric_value: float | None,
    final_metrics: dict[str, object],
    epoch_history: list[dict[str, object]],
    parameter_count: int,
    warm_start_summary: dict[str, object],
) -> dict[str, object]:
    """构建 train-metrics.json 对应的完整 JSON 载荷。"""

    return {
        "implementation_mode": YOLOX_MINIMAL_IMPLEMENTATION_MODE,
        "device": device,
        "gpu_count": gpu_count,
        "device_ids": list(device_ids),
        "distributed_mode": distributed_mode,
        "precision": precision,
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "evaluation_interval": evaluation_interval,
        "input_size": list(input_size),
        "train_split_name": train_split_name,
        "validation_split_name": validation_split_name,
        "sample_count": sample_count,
        "train_sample_count": train_sample_count,
        "validation_sample_count": validation_sample_count,
        "category_names": list(category_names),
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
        "final_metrics": dict(final_metrics),
        "epoch_history": [dict(item) for item in epoch_history],
        "parameter_count": parameter_count,
        "warm_start": dict(warm_start_summary),
    }


def _extract_prefixed_history(
    epoch_history: list[dict[str, object]],
    *,
    prefix: str,
) -> list[dict[str, object]]:
    """从合并后的 epoch_history 中提取指定前缀的指标轨迹。"""

    extracted_history: list[dict[str, object]] = []
    for epoch_metrics in epoch_history:
        extracted_metrics: dict[str, object] = {}
        epoch_value = epoch_metrics.get("epoch")
        if isinstance(epoch_value, int):
            extracted_metrics["epoch"] = epoch_value
        for key, value in epoch_metrics.items():
            if key.startswith(prefix):
                extracted_metrics[key.removeprefix(prefix)] = value
        if len(extracted_metrics) > 1:
            extracted_history.append(extracted_metrics)
    return extracted_history


def _build_optimizer(*, imports: _YoloXTrainingImports, model: Any, batch_size: int):
    """按 YOLOX 的最小参数分组规则创建优化器。"""

    learning_rate = (0.01 / 64.0) * batch_size
    pg0: list[object] = []
    pg1: list[object] = []
    pg2: list[object] = []
    for module_name, module in model.named_modules():
        if hasattr(module, "bias") and isinstance(module.bias, imports.torch.nn.Parameter):
            pg2.append(module.bias)
        if isinstance(module, imports.torch.nn.BatchNorm2d) or "bn" in module_name:
            pg0.append(module.weight)
        elif hasattr(module, "weight") and isinstance(module.weight, imports.torch.nn.Parameter):
            pg1.append(module.weight)

    optimizer = imports.torch.optim.SGD(pg0, lr=learning_rate, momentum=0.9, nesterov=True)
    optimizer.add_param_group({"params": pg1, "weight_decay": 5e-4})
    optimizer.add_param_group({"params": pg2})
    return optimizer


def _convert_training_outputs(outputs: dict[str, object]) -> dict[str, float]:
    """把 YOLOX forward 输出转换为可序列化的标量字典。"""

    scalar_outputs: dict[str, float] = {}
    for key, value in outputs.items():
        if hasattr(value, "detach"):
            scalar_outputs[key] = float(value.detach().cpu().item())
        elif isinstance(value, int | float):
            scalar_outputs[key] = float(value)
    return scalar_outputs