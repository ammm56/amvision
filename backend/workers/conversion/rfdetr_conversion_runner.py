"""RF-DETR 转换执行器（项目内实现）。"""

from __future__ import annotations

import torch

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.errors import ServiceError
from backend.service.application.models.rfdetr_model import build_rfdetr_model
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


# RF-DETR 转换输出文件类型
RFDETR_ONNX_FILE = "rfdetr-onnx-model"
RFDETR_ONNX_OPTIMIZED_FILE = "rfdetr-onnx-optimized-model"


class LocalRfdetrConversionRunner(ConversionBackend):
    """本地 RF-DETR 转换执行器。

    实现 ConversionBackend 协议，支持 RF-DETR 模型的 ONNX 导出。
    """

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化 RF-DETR 转换执行器。

        参数：
        - dataset_storage：本地文件存储服务。
        """
        self.dataset_storage = dataset_storage

    def run_conversion(self, request: ConversionBackendRunRequest) -> ConversionBackendRunResult:
        """执行 RF-DETR 模型转换。

        参数：
        - request：转换执行请求，metadata 中需包含：
          - checkpoint_object_key：checkpoint 文件路径
          - model_scale：模型 scale（默认 nano）
          - num_classes：类别数（默认 80）
          - input_size：输入尺寸（默认 [384, 384]）

        返回：
        - ConversionBackendRunResult：转换结果，包含输出文件列表。
        """
        metadata = dict(request.metadata or {})

        checkpoint_key = metadata.get("checkpoint_object_key")
        if not checkpoint_key:
            raise ServiceError("RF-DETR 转换缺少 checkpoint_object_key")

        target_format = metadata.get("target_format", "onnx")
        precision = metadata.get("precision", "fp32")
        model_scale = metadata.get("model_scale", "nano")
        num_classes = int(metadata.get("num_classes", 80))
        input_size = metadata.get("input_size", [384, 384])

        if isinstance(input_size, (list, tuple)) and len(input_size) == 2:
            input_h, input_w = int(input_size[0]), int(input_size[1])
        else:
            input_h, input_w = 384, 384

        # 加载 checkpoint
        checkpoint_path = self.dataset_storage.resolve(checkpoint_key)
        if not checkpoint_path.is_file():
            raise ServiceError(f"checkpoint 文件不存在: {checkpoint_key}")

        checkpoint = torch.load(str(checkpoint_path), map_location="cpu", weights_only=False)
        state_dict = checkpoint.get("model_state_dict", checkpoint)

        # 构建模型
        model = build_rfdetr_model(model_scale=model_scale, num_classes=num_classes)
        model.load_state_dict(state_dict, strict=False)
        model.eval()

        outputs: list[ConversionBackendOutput] = []

        if target_format in ("onnx", "onnx-optimized"):
            onnx_key = f"{request.output_object_prefix}/artifacts/builds/rfdetr-{model_scale}.onnx"
            onnx_path = self.dataset_storage.resolve(onnx_key)
            onnx_path.parent.mkdir(parents=True, exist_ok=True)

            dummy_input = torch.randn(1, 3, input_h, input_w)
            torch.onnx.export(
                model,
                dummy_input,
                str(onnx_path),
                opset_version=17,
                input_names=["image"],
                output_names=["pred_logits", "pred_boxes"],
                dynamic_axes={
                    "image": {0: "batch"},
                    "pred_logits": {0: "batch"},
                    "pred_boxes": {0: "batch"},
                },
            )

            file_type = RFDETR_ONNX_OPTIMIZED_FILE if target_format == "onnx-optimized" else RFDETR_ONNX_FILE
            outputs.append(ConversionBackendOutput(
                target_format=target_format,
                object_uri=onnx_key,
                file_type=file_type,
                metadata={
                    "precision": precision,
                    "model_scale": model_scale,
                    "num_classes": num_classes,
                    "input_size": [input_h, input_w],
                },
            ))
        else:
            raise ServiceError(f"RF-DETR 暂不支持转换格式: {target_format}")

        # 写入转换报告
        report_key = f"{request.output_object_prefix}/artifacts/conversion-report.json"
        report = {
            "conversion_task_id": request.conversion_task_id,
            "model_type": "rfdetr",
            "model_scale": model_scale,
            "num_classes": num_classes,
            "input_size": [input_h, input_w],
            "outputs": [
                {"target_format": o.target_format, "object_uri": o.object_uri, "file_type": o.file_type}
                for o in outputs
            ],
        }
        self.dataset_storage.write_json(report_key, report)

        return ConversionBackendRunResult(
            conversion_task_id=request.conversion_task_id,
            outputs=tuple(outputs),
            metadata={
                "report_object_key": report_key,
                "produced_formats": [o.target_format for o in outputs],
            },
        )
