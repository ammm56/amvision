# 模型支持矩阵

本文是当前模型与任务组合的能力入口，只描述正式代码路径。`projectsrc/` 仅用于开发期参考，不属于运行时、测试或发行包依赖。

## 模型与任务

| model_type | 正式任务 |
| --- | --- |
| `yolox` | `detection` |
| `yolov8` | `detection / classification / segmentation / pose / obb` |
| `yolo11` | `detection / classification / segmentation / pose / obb` |
| `yolo26` | `detection / classification / segmentation / pose / obb` |
| `rfdetr` | `detection / segmentation` |

RF-DETR classification、pose 和 OBB 不属于当前公开能力。YOLOE、SAM3 走 Custom Node/Workflow Runtime，不属于 DeploymentInstance 模型注册主链。

## 状态

- `tested`：公开代码路径已接通，并有自动化或真实 artifact smoke。
- `implemented`：代码路径已接通，仍应按实际数据、设备和目标 runtime 验收。
- `—`：不支持，不能在 API 或 UI 中作为可选能力公开。

## 端到端矩阵

数据集导入导出是任务级能力；部署和推理同时包含 sync/async 控制面；Workflow 表示存在通用模型节点和正式 Runtime 调用面。

| model | task | 导入/导出 | 训练/验证 | 评估 | ONNX/OpenVINO/TensorRT | 部署/推理 | Workflow | 前端 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| YOLOX | detection | tested | tested | tested | tested | tested | tested | implemented |
| YOLOv8 | detection | tested | tested | tested | tested | tested | tested | implemented |
| YOLOv8 | classification | tested | tested | implemented | tested | implemented | tested | implemented |
| YOLOv8 | segmentation | implemented | tested | implemented | tested | implemented | tested | implemented |
| YOLOv8 | pose | implemented | tested | implemented | implemented | tested | tested | implemented |
| YOLOv8 | obb | tested | implemented | implemented | implemented | implemented | tested | implemented |
| YOLO11 | detection | tested | tested | tested | tested | tested | tested | implemented |
| YOLO11 | classification | tested | tested | implemented | implemented | tested | tested | implemented |
| YOLO11 | segmentation | implemented | implemented | implemented | implemented | implemented | tested | implemented |
| YOLO11 | pose | implemented | implemented | implemented | implemented | implemented | tested | implemented |
| YOLO11 | obb | tested | implemented | implemented | implemented | implemented | tested | implemented |
| YOLO26 | detection | tested | tested | tested | tested | tested | tested | implemented |
| YOLO26 | classification | tested | implemented | implemented | implemented | implemented | tested | implemented |
| YOLO26 | segmentation | implemented | tested | implemented | implemented | tested | tested | implemented |
| YOLO26 | pose | implemented | implemented | implemented | implemented | implemented | tested | implemented |
| YOLO26 | obb | tested | tested | implemented | implemented | tested | tested | implemented |
| RF-DETR | detection | tested | tested | tested | tested | tested | tested | implemented |
| RF-DETR | segmentation | implemented | tested | implemented | tested | tested | tested | implemented |

`implemented` 不是精度承诺。模型准确率取决于数据、标注、训练参数、checkpoint、评估口径和目标 runtime；进入现场前必须使用目标数据与硬件验收。

## 数据格式

| task | 导入/导出格式 |
| --- | --- |
| classification | ImageNet directory / `imagenet-classification-v1` |
| detection | COCO、VOC、YOLO / `coco-detection-v1`、`voc-detection-v1`、`yolo-detection-v1` |
| segmentation | COCO、YOLO、VOC indexed mask / `coco-instance-seg-v1`、`yolo-instance-seg-v1`、`voc-instance-seg-v1` |
| pose | COCO Keypoints、YOLO Pose / `coco-keypoints-v1`、`yolo-pose-v1` |
| obb | DOTA、YOLO OBB / `dota-obb-v1`、`yolo-obb-v1` |

完整字段和目录规范见 [模型数据集格式](../datasets/model-contract.md)。公开注册表不保留未实现格式占位。

## 运行时后端

| backend | 当前边界 |
| --- | --- |
| `pytorch` | 训练输出验证、部署和推理 |
| `onnxruntime` | ONNX artifact 加载与推理 |
| `openvino` | CPU/GPU/NPU 取决于设备和 OpenVINO 环境 |
| `tensorrt` | NVIDIA GPU，要求 wheel、DLL、engine 和 driver 版本匹配 |

转换 artifact 必须实际加载和推理，不能只以文件生成成功作为通过。

## 评估边界

平台通用评估使用项目内 COCO-style AP、mask IoU、OKS 和 rotated IoU。它不宣称逐字段等同于 `pycocotools.COCOeval` 或每个参考仓库 validator 的全部 stats、area range、crowd/ignore 语义。训练期 best checkpoint 选择继续使用各模型 Core validator 的明确指标。

RF-DETR 当前不公开 LoRA/PEFT，不接受任意 Python optimizer callable。配置必须可序列化、可复现、可审计。

## 验收入口

统一矩阵入口：

```powershell
python -m tests.integration.model_task_e2e_matrix --start-processes
```

该入口覆盖真实数据导入、导出、短训练、评估、三类转换 artifact、独立进程 sync/async 推理和清理。筛选运行只能证明子集，不能替代完整矩阵。

其他证据：

- `tests/integration/test_non_detection_runtime_backend_smoke_matrix.py`
- `tests/integration/test_yolov8_detection_runtime_backend_smoke.py`
- `tests/test_rfdetr_segmentation_task_smoke.py`
- `tests/test_non_detection_training_model_type_matrix.py`
- `docs/api/postman/` 中的模型与 Workflow collection

长期训练、精度对比和持续负载不放入默认快速 pytest；执行方式见 [full core 验收](../../development/model-validation.md) 和 [完整发行栈排障](../../operations/release-full-troubleshooting.md)。

## 事实来源

- 模型/任务注册表与训练参数 registry
- 数据集格式注册表
- conversion planner 与 runtime backend registry
- Deployment/Workflow 节点 catalog
- OpenAPI 与前端 bootstrap capability

新增组合必须先完成实现和测试，再更新本矩阵；不能先把未实现项写成 `implemented`。
