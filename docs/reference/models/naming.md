# 模型与任务命名边界

## 核心规则

- 面向调用方的控制面按 `task_type` 命名。
- 承载算法和执行差异的内部实现按 `model_type` 命名。
- 只有同一模型系列真正共享的实现才按系列名命名。
- 只有与模型和任务都无关的值对象或工具才使用中性通用名。
- 模型 Core 外层按 `model_type`，内部按 `task_type` 组织。

这组规则避免“公开 API 已统一”被误解为“所有模型内部实现相同”。

## 分层命名

| 层 | 命名 | 示例 |
|---|---|---|
| REST/API/UI | `task_type` | `detection_training_tasks/`、`pose-evaluation` |
| Task kind / Queue consumer | 实际执行模型或共享范围 | `yolox-training`、`rfdetr-conversion`、`detection-inference` |
| 模型 Core | `model_type` + 内部 `task_type` | `yolo11_core/losses/pose.py` |
| 系列共享层 | 明确系列名 | `yolo_core_common`、`yolo_conversion_*` |
| 通用领域对象 | 中性名 | `TaskRecord`、`ModelVersion`、`ModelBuild` |

## 公开控制面

路由、OpenAPI、前端导航和 Workflow service node 以 detection、classification、segmentation、pose、obb 等任务类型组织。调用方选择 `model_type` 作为请求字段，不进入模型专属路由。

例如 detection 训练公开入口可以同时接收 YOLOX、YOLOv8、YOLO11、YOLO26 和 RF-DETR，但应用服务必须按支持矩阵分发到各自 runner，不能用一个 YOLOX service 冒充通用 detection 实现。

## 内部执行层

以下内容按模型类型隔离：

- 模型构建、head、loss、assigner、matcher、decode；
- 训练 runner、checkpoint 和 optimizer/scheduler；
- exporter 与 checkpoint mapping；
- predictor/session 与模型专用 postprocess；
- 仅某一模型使用的 Task service 和 Queue consumer。

只有实现已经真正共享时，task kind 才可使用 `detection-inference`、`segmentation-evaluation` 等任务级名称。名字必须与实际 dispatch 边界一致。

## Core 目录

```text
models/
├─ yolox_core/
├─ yolov8_core/
├─ yolo11_core/
├─ yolo26_core/
├─ rfdetr_core/
└─ yolo_core_common/
```

- `yolo_core_common` 只能包含不判断 `model_type` 的 layer、geometry、tensor 和权重工具；
- 需要判断模型代际的代码放回对应 Core；
- 需要判断任务类型的大函数优先拆为 detection/classification/segmentation/pose/obb 文件；
- `backend/service/application/runtime/` 只保存 deployment session 和 adapter，不保存模型 Core。

## 判断顺序

新增文件、类、常量或 task kind 前依次确认：

1. 这是公开控制面还是内部执行实现？
2. 差异来自 `task_type` 还是 `model_type`？
3. 共享范围是全平台、单模型系列，还是单个模型？
4. 去掉模型名后，名称是否会错误暗示全平台共享？
5. 当前支持矩阵和 dispatch 测试是否证明该名称真实？

## 禁止模式

- 把只服务 YOLOX 的类命名为通用 `DetectionTrainer`；
- 在 `yolo_core_common` 中使用大段 `if model_type == ...`；
- 让公开路由直接 import 模型 Core；
- 为了目录整齐合并不同代际 checkpoint/export 规则；
- 用旧别名薄壳长期转发到新实现；
- task kind 与实际 Worker consumer 不一致。

相关文档：[模型 Core 架构](../../architecture/models/model-core.md)、[模型支持矩阵](support-matrix.md)、[模型工作流边界](../../architecture/models/workflow-boundaries.md)。
