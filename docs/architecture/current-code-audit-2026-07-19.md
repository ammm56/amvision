# 当前代码与完整链路审计（2026-07-19）

## 结论

当前仓库不是模型或流程骨架，DatasetImport、DatasetExport、训练、评估、转换、deployment、sync/async inference、workflow runtime、custom nodes 和 Vue 3 前端均已有真实实现。YOLOX detection、YOLOv8/YOLO11/YOLO26 五任务、RF-DETR detection/segmentation 都有短链或定向测试记录。

但“短链可运行”不能写成“所有模型、scale、硬件和异常场景已经达到生产长期稳定”。当前更准确的状态是：

- 控制面、对象边界、worker 分离和主调用链已经成立；
- 数据集同名图片覆盖问题已修复，导入、导出与删除回归通过；
- 模型 core 装配、checkpoint/warm start、五任务训练登记和依赖边界回归通过；
- 真实长训练、全 scale checkpoint、GPU 组合、deployment 持续高帧率负载和异常恢复仍需要独立验收；
- segmentation、pose、OBB 的部分评估口径是项目内 COCO-style 实现，不等同于参考仓库完整 validator 的全部统计口径；
- WorkflowRuntimeService 和少数训练编排文件仍然过大，需要继续按职责拆分。

## 审计范围与证据边界

- 对仓库内 127 个 tracked Markdown 文件做了目录、标题和未完成标记盘点，重点逐项核对架构、数据集、任务、模型支持、full-core 清单、workflow、节点、前端和发布文档。
- 检查 `backend/`、`custom_nodes/`、`frontend/`、`sdks/` 和 `tests/` 的运行时代码引用，没有发现运行时代码依赖 `projectsrc/`。
- `projectsrc/ultralytics/ultralytics`、`projectsrc/YOLOX_2026/yolox`、`projectsrc/rf-detr/src/rfdetr` 和 `projectsrc/supervision/src/supervision` 只作为结构、数学行为和输出语义参考，不是项目运行时依赖。
- 真实模型长训练、TensorRT/CUDA 组合和现场常驻运行不适合用默认 pytest 代替。本审计沿用既有真实 smoke 记录，并重新执行受影响的定向回归。

## 分层与调用链

| 层 | 当前职责 | 审计结论 |
| --- | --- | --- |
| FastAPI/API | 鉴权、schema、资源路由、提交任务、查询状态 | 边界成立；业务重任务没有直接塞进请求处理器 |
| application service | 任务状态、UoW、对象存储键、模型/流程编排 | 主链成立；少数 service 文件仍过大 |
| domain | DatasetVersion、Model/Build、Task、Deployment、Workflow 记录和能力矩阵 | 基本清晰；能力声明必须只反映真实可执行格式 |
| infrastructure | SQLAlchemy、SQLite、本地对象存储、本地持久化队列、进程监督 | 本地优先边界成立，并保留数据库/运行时替换面 |
| workers/runtime | 数据集、训练、评估、转换、异步推理、workflow 和 deployment 子进程 | 独立 worker 与长期 deployment 子进程边界成立 |
| model core | 模型结构、data、loss、target、assigner、training、evaluation、export、inference、postprocess | 各模型纵向 core 已建立，不依赖参考仓库运行时 |
| custom nodes | 协议、OpenCV、YOLOE、SAM3、输出集成等扩展 | 符合“特殊能力放 custom node，不膨胀平台 core”的方向 |
| Vue 3 frontend | 数据集、模型、部署、推理、workflow、集成和设置页面 | 主栈统一；类型检查和单元测试可执行 |

## 数据集链路

### 已确认

- 导入格式：COCO、VOC、YOLO、ImageNet classification、DOTA OBB。
- 统一 DatasetVersion 支持 detection、classification、segmentation、pose、obb annotation。
- 导出格式：COCO detection、VOC detection、YOLO detection、COCO instance segmentation、YOLO instance segmentation、COCO keypoints、YOLO pose、ImageNet classification、DOTA OBB。
- 新的图片对象键使用 `images/{split}/{sample_id}/{file_name}`，同 split、同文件名、不同类别或目录的样本不会再覆盖。
- 训练通过 DatasetExport manifest 消费文件，不硬编码旧的 DatasetVersion 图片路径。
- 删除 DatasetImport 只删除导入包、暂存目录、任务和导入记录，保留稳定 DatasetVersion。
- 删除 DatasetExport 会删除导出运行目录、下载包、关联任务和导出记录，不删除 DatasetVersion。

### 本轮修复

- 新增 Project 级 DatasetVersion 列表接口，前端版本选择器直接以稳定 DatasetVersion 为数据源。删除 DatasetImport 后，保留的版本不再变成不可发现的孤立资源。
- 列表使用专用 summary 投影：分别聚合版本、类别数和 split/sample 数，不加载全部 samples 和 annotations，避免大数据集页面查询占用大量内存。
- 新 DatasetVersion metadata 记录 created_at，前端可稳定按来源时间排序；仍保留 source_import_id 和 format_type 用于追踪。

### 仍需实现

- 当前没有显式删除 DatasetVersion 的公开入口。后续如增加，必须先检查 DatasetExport、ModelVersion、训练任务和其他业务引用，禁止无条件级联删除。
- 超大 zip 的分片上传、断点续传和 upload session 仍未实现，当前仍是单次 multipart 上传。

## 模型支持与参考实现核对

| 模型 | 任务 | 当前 core 状态 | 主要参考 |
| --- | --- | --- | --- |
| YOLOX | detection | data augmentation、scheduler、EMA、训练/评估、ONNX/OpenVINO/TensorRT、runtime 已接通 | YOLOX Exp/data/model/evaluator |
| YOLOv8 | detection/classification/segmentation/pose/obb | 五任务专属 core、训练、评估、转换和 runtime 已接通 | Ultralytics v8 task/model/loss/TAL/validator |
| YOLO11 | detection/classification/segmentation/pose/obb | 五任务专属 core 和 backend session 已接通 | Ultralytics 11 配置、head、loss 和导出行为 |
| YOLO26 | detection/classification/segmentation/pose/obb | end2end top-k、任务专属 head/输出和 runtime 已接通 | Ultralytics 26 end2end head/export/postprocess |
| RF-DETR | detection/segmentation | 模型、训练、COCO evaluation、转换和 runtime 已接通 | RF-DETR model/training/export；supervision 仅使用项目内受控子集 |

### 能力声明修复

模型 profile 和 conversion planner 曾把 RKNN 标成支持/可规划目标，但公开 conversion service 实际只执行 ONNX、ONNX optimized、OpenVINO IR 和 TensorRT engine。本轮已从 YOLOX 和三代 YOLO 当前支持矩阵及 planner 中移除 RKNN，避免前端或第三方按虚假能力调用。RKNN 类型和 runtime target 可作为后续 ARM NPU 实现边界保留，但在 converter 真正实现和验收前不属于当前模型支持能力。

### 不能过度声明的部分

- classification 的 top-5 在类别数小于等于 5 时天然可能为 1.0；参考 Ultralytics 的 fitness 也是 top-1/top-5 均值。本项目选择 best checkpoint 使用 top-1，不会因为 top-5 饱和误选权重。
- segmentation mask AP、pose OKS 和 OBB rotated AP 已有项目内实现，但不等于参考仓库完整 validator、pycocotools 和专用 rotated evaluator 的全部输出字段与统计细节。
- RF-DETR LoRA/PEFT 明确未启用；这不是当前 detection/segmentation 主链缺失，但不能对外宣称支持微调模式。
- 全 scale、长 epoch、真实业务数据精度和不同 CUDA/TensorRT 版本组合必须继续用独立验收记录证明。

## 转换、部署与常驻推理

- 当前可执行转换目标为 ONNX、ONNX optimized、OpenVINO IR、TensorRT engine。
- deployment 按 task type 使用独立 service、runtime target resolver 和长期子进程 supervisor。
- sync 直接调用常驻 deployment；async 通过持久化任务和 inference worker 调用 deployment，不重复在 API 进程加载模型。
- runtime backend 已覆盖 PyTorch、ONNX Runtime、OpenVINO、TensorRT 的任务专属 session。
- 当前短链记录覆盖 start、warmup、sync/async inference、stop/reset；这只能证明控制链和产物可用。
- Workflow runtime worker 冷启动此前错误复用普通请求超时，并硬截断为最多 15 秒；Windows 冷启动加载节点包时会误报 504。本轮已改为使用独立的 `startup_timeout_seconds`，默认 180 秒，不再破坏 deployment 配置的启动语义。

仍需补齐的生产验收：

- Windows x64 CPU/NVIDIA 两种发布包的多小时/多天持续推理；
- 不同图片尺寸、批量、高帧率和错误输入下的 RSS、显存、句柄、线程和临时文件趋势；
- worker/deployment crash、backend-service restart、队列重放、超时和取消后的恢复；
- TensorRT engine 与目标 GPU、driver、CUDA/TensorRT 版本的绑定检查和现场错误提示；
- Ubuntu x64 CPU/NVIDIA 位置已规划但按当前阶段暂不实现，不能写成已支持。

## Workflow、节点和前端

- Workflow template/application/runtime、preview、sync invoke、async run、事件、trigger source 和 snapshot 边界已实现。
- core node 负责稳定原子能力，协议/硬件桥接和行业流程放 custom node，符合项目范围。
- `projectsrc/supervision` 不作为依赖；RF-DETR 的 `supervision_compat` 是当前调用所需的受控子集，不是完整 supervision 替代包。
- Barcode/QR 节点的源 payload contract 已支持本地 buffer/frame 引用，但 checked-in catalog 曾未重新生成；本轮已同步生成。OpenCV `rotated-rects.v1` 已由 custom 提升到 core，测试也已改为按真实所有权分别校验。
- 前端使用 Vue 3 + TypeScript + Vite，没有发现并行框架。
- 数据集页面本轮已同步 DatasetVersion 独立生命周期，删除导入记录后仍能选择版本、显示来源摘要并继续导出。

## 大文件与边界

本轮 AST 统计确认仍需继续拆分：

- `workflows/runtime_service.py`：原 2196 行、53 个方法；本轮把时间、诊断和 metadata helper 移到 `runtime/metadata.py`，服务文件降到约 1975 行。
- `yolov8_core/training/detection_execution.py`：约 2302 行，混有 DTO、resume 校验、epoch 主循环、评估适配和 augmentation option 解析。
- `models/training/yolox_detection_task_service.py`：约 1558 行，process、登记、控制和训练 adapter 仍在一个 service。

后续拆分顺序：先拆无状态 DTO/options/checkpoint/evaluation adapter，再拆事务 service；不为行数直接搬动模型数学代码，也不重新建立跨模型的 primary 大文件。

## 本轮验证

- 数据集导入、全部导出格式、导出交付、删除、segmentation/pose manifest 和模型依赖边界：55 passed。
- 同名 classification 图片导入/导出、DatasetExport 删除和下载包交付定向回归：4 passed。
- 模型 core entrypoints、checkpoint/warm start、五任务训练登记、模型 profile、转换 planner、import smoke：1017 passed。
- deployment detection 与 classification/segmentation/pose/obb sync/async 控制面和 task-native 结果：28 passed。
- YOLOX memory/storage、multipart/base64、sync/async inference API：13 passed。
- Workflow metadata、正式示例和 runtime 基础定向回归：33 passed；冷启动与图片异常返回追加回归：3 passed。
- Workflow runtime invoke、raw result、持久化回退、坏图恢复和事件文件完整回归：14 passed。
- Barcode/OpenCV 等 custom node catalog 与 loader 回归：26 passed。
- 前端最终结果：`vue-tsc --noEmit` 通过，Vitest 9 files / 32 tests passed。

以上结果验证的是代码与短链回归，不替代真实 GPU 转换、长训练和长期常驻负载验收。
