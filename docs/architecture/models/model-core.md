# 模型 Core 架构

本文说明 YOLOX、YOLOv8、YOLO11、YOLO26 和 RF-DETR 在 AMVision 内的当前实现边界。

## 原则

- 每个模型系列拥有独立 Core，不以一个大分支运行时模拟不同代际。
- 任务编排、数据库、ObjectStore、Task 和 API 留在平台层；网络、loss、decode、validator、export 和 runtime 语义留在模型 Core。
- 只共享与模型代际无关的基础组件，例如通用 layer、geometry 和权重读取工具。
- 参考仓库用于算法和 checkpoint 对照，`projectsrc/` 不进入 import、API 字段或发行包。
- 权重加载保持严格。shape mismatch、missing 或 unexpected key 必须显式处理和测试，不能全局关闭 strict。

## 目录

```text
backend/service/application/models/
├─ yolox_core/
│  ├─ cfg/ data/ evaluators/ export/ models/ postprocess/ training/ utils/
├─ yolov8_core/
│  ├─ assigners/ cfg/ data/ decode/ evaluation/ export/
│  └─ inference/ losses/ nn/ postprocess/ targets/ training/
├─ yolo11_core/
│  └─ 与本代模型契约对应的独立 task 模块
├─ yolo26_core/
│  └─ 独立 end-to-end/task/export 语义
├─ rfdetr_core/
│  ├─ assets/ datasets/ evaluation/ export/ models/ training/ utilities/ visualize/
├─ yolo_core_common/
│  └─ 不包含代际判断的基础 layer/geometry/weights
├─ training/ evaluation/ export/ inference/ postprocess/
│  └─ 平台任务编排与 adapter
└─ registry/ catalog/ support/
   └─ 平台模型登记与公共值对象
```

## 分层职责

### API 与应用服务

- 校验 Project、DatasetVersion、Model、ModelVersion 和 Task。
- 解析可序列化训练/转换参数。
- 建立队列任务和状态事件。
- 登记训练、评估与转换产物。
- 不实现网络 forward、loss 或模型专用 decode。

### Worker

- 按严格 `task_type × model_type` 路由到模型 Core。
- 准备 ObjectStore 输入与输出目录。
- 驱动训练、评估和转换执行。
- 回写 Task 终态；未知组合直接失败，不回退到另一模型。

### 模型 Core

- config 与模型构建
- dataset/dataloader 与增强
- head、assigner、target、loss 和 decode
- optimizer、scheduler、AMP 和 checkpoint
- validator/evaluator adapter
- ONNX export graph 与模型专用后处理
- runtime input/output 语义

### Runtime adapter

- 加载 PyTorch、ONNXRuntime、OpenVINO 或 TensorRT artifact。
- 将平台 image payload 转为模型输入。
- 调用模型 Core 后处理并输出统一 detection/category/segment/pose/OBB payload。
- 管理 session 生命周期、预热、buffer 和设备资源。

## 模型边界

### YOLOX

- 只公开 detection。
- 保留 YOLOX 自己的 data、Exp/config、head、SimOTA/loss、evaluator、export 与 postprocess。
- 不复用三代 Ultralytics YOLO task head。

### YOLOv8 / YOLO11 / YOLO26

- 各自公开 detection、classification、segmentation、pose 和 OBB。
- 三代分别保存 parser、head、loss、assigner、decode、export 和 runtime 语义。
- YOLO26 end-to-end processed output 与 raw PyTorch output 由本代 adapter 显式区分。
- non-detection 任务不通过 detection helper 偷换字段或指标。

### RF-DETR

- 公开 detection 与 segmentation。
- factory、训练和 export 共用同一 `input_size` 模型构建入口。
- 输入高宽必须为正并满足 patch/window divisor；不在 export 中静默对齐。
- 训练使用方形 resolution 时，非方形输入按同一规则取 `max(height, width)` 构建 position embeddings。
- checkpoint strict load 在 ONNX/OpenVINO/TensorRT 前完成；不能插值或忽略 position embedding mismatch。

## Checkpoint 与来源

- 平台预训练模型按 manifest 登记磁盘引用，不提供隐式下载。
- 训练输出登记 ModelVersion、ModelFile、parent version 和 artifact provenance。
- warm start 与 resume 是不同契约：warm start 只加载允许的模型权重，resume 恢复 optimizer/scheduler/scaler/epoch 等完整状态。
- best 与 latest checkpoint 分开登记。
- 训练、转换和部署都核对模型类型、任务、scale、输入尺寸、class/keypoint schema 和 artifact format。

## 转换

```text
ModelVersion/Build
  → model-specific export context
  → strict checkpoint load
  → ONNX
  → optional simplify/validation
  → OpenVINO IR or TensorRT engine
  → artifact registration
  → real runtime load/predict smoke
```

转换失败必须保留阶段和真实错误，不生成看似成功但不可加载的 artifact。

## 评估与准确率

- validation/test split 不混用。
- 数据类别和模型输出索引使用明确 mapping。
- segmentation、pose、OBB 使用各自几何和指标，不退化为 bbox AP。
- 任何弃用 API 替换必须比较数值、shape、dtype 和后处理，不以“警告消失”作为正确性证据。
- 日志频率可以提高可观测性，但需要通过长训练评估磁盘、TensorBoard/CSV I/O 和吞吐影响。

## 验收

每个公开组合至少覆盖：

1. 配置与 checkpoint strict load。
2. DatasetImport/Export 往返。
3. 短训练、validation 和 checkpoint 产出。
4. dataset evaluation。
5. ONNX、OpenVINO、TensorRT 转换。
6. artifact 实际加载与单次推理。
7. Deployment sync/async、warmup、reset 和 stop。
8. Workflow 模型节点。
9. 错误和资源清理。

状态见 [模型支持矩阵](../../reference/models/support-matrix.md)，具体门禁见 [模型 full core 验收](../../development/model-validation.md)。
