# DDP TrainingBackend 实现计划

## 文档目的

本文档固定多 GPU 训练的目标边界、当前状态、实现顺序和验收规则。

本文档不把单机单进程 `DataParallel` 视为完整多 GPU 训练。生产级多卡训练统一以多进程 DDP 或模型参考实现等价机制为准。

## 当前状态

| 模型 | 当前多 GPU 行为 | 结论 |
| --- | --- | --- |
| YOLOX detection | `gpu_count > 1` 已走 torchrun DDP 子进程；同步训练入口拒绝 `DataParallel`；rank0 写任务事件和产物，rank>0 只参与训练 | 代码链路已接入，仍需真实多 GPU 硬件 smoke |
| YOLOv8 / YOLO11 / YOLO26 detection | `gpu_count > 1` 当前走单进程 `torch.nn.DataParallel` | 过渡实现，需要替换为普通 YOLO core 内 DDP |
| YOLOv8 / YOLO11 / YOLO26 classification / segmentation / pose / obb | 当前没有公开顶层 `gpu_count`，主要按单设备训练 | 需要按任务逐项补 DDP |
| RF-DETR detection / segmentation | core 内已接近 Lightning DDP 的 `devices / strategy` 语义 | 需要统一平台 TrainingBackend 字段、事件和产物规则 |

## 目标边界

### 平台 worker

- 领取训练任务。
- 根据 `gpu_count` 和运行环境选择单 GPU 或 DDP TrainingBackend。
- 启动 DDP 子进程并等待完成。
- 汇总失败诊断。
- 只接受 rank0 产物登记结果。

worker 不实现模型结构、loss、assigner、target、数据增强、validator、postprocess 或 checkpoint 语义。

### 模型 core

各模型 core 负责真实训练细节：

- 模型构建和权重加载
- Dataset / Dataloader / DistributedSampler
- loss / assigner / target
- optimizer / scheduler / AMP / EMA
- validation / evaluation
- checkpoint save / resume
- export 前可复用的 inference checkpoint 生成

DDP 下所有 rank 都参与训练和 collective；只有 rank0 写任务事件、对象存储、checkpoint、summary 和 ModelVersion。

### 平台通用 DDP support

通用 DDP support 放在：

`backend/service/application/models/support/distributed_training/`

该目录只放通用值对象和工具：

- `DdpTrainingContext`
- backend 选择
- `torch.distributed.run` 本机启动配置
- rank0-only reporter
- world size / GPU 数量校验

该目录不得依赖数据库、队列、对象存储、FastAPI route 或具体模型 core。

## batch size 规则

前端和 API 中的 `batch_size` 统一解释为总 batch size。

DDP 后端按 `world_size` 拆成 per-rank batch。不能整除时应明确拒绝或显式记录实际 per-rank 分配规则，不能静默改变训练语义。

学习率、warmup、scheduler 按对应参考实现处理：

- YOLOX 对齐 `YOLOX_2026/yolox/core/launch.py` 和 trainer DDP 语义
- YOLOv8 / YOLO11 / YOLO26 对齐 Ultralytics `engine/trainer.py` 的 DDP 语义
- RF-DETR 对齐 `rf-detr` Lightning 训练语义

## 控制和产物规则

- pause / save / terminate 由 rank0 读取平台控制状态，再 broadcast 给其他 rank。
- checkpoint 只允许 rank0 写。
- latest checkpoint 可包含 optimizer / scaler / EMA / resume state。
- ModelVersion 登记必须使用 stripped / inference checkpoint，不使用完整 resume checkpoint。
- validation 必须 gather 全 rank 结果，不能只评估 rank0 的数据 shard。
- rank>0 不写数据库、不写对象存储、不发 WebSocket 任务事件。

## 实现顺序

1. 建立通用 DDP support。
2. YOLOX detection DDP。
3. 普通 YOLO detection DDP。
4. 普通 YOLO 非 detection DDP。
5. RF-DETR DDP 平台字段收口。
6. 前端和 API 收口。

## 验收标准

### 通用标准

- 单 GPU 训练结果不回退。
- DDP 任务启动后 rank 数正确。
- 每个 rank 的数据 shard 正确。
- rank0 事件不重复。
- rank>0 不写平台产物。
- pause / save / terminate 能正确广播并退出。
- resume 后 epoch / optimizer / scaler / EMA 状态可恢复。

### 模型标准

- YOLOX detection：短训练、validation、checkpoint resume、ONNX/OpenVINO/TensorRT conversion、deployment smoke。
- YOLOv8 / YOLO11 / YOLO26 detection：短训练、validation、checkpoint resume、conversion、deployment smoke。
- YOLOv8 / YOLO11 / YOLO26 classification / segmentation / pose / obb：按任务分别完成短训练、validation/evaluation、conversion、deployment smoke。
- RF-DETR detection / segmentation：Lightning DDP 事件、产物、失败路径和平台字段一致。

## 当前落地状态

已新增通用 DDP support：

- `backend/service/application/models/support/distributed_training/context.py`
- `backend/service/application/models/support/distributed_training/launcher.py`
- `backend/service/application/models/support/distributed_training/reporter.py`

YOLOX detection 已删除同步训练入口中的 `DataParallel` wrapper，并新增：

- `backend/service/application/models/yolox_core/training/ddp.py`
- `backend/workers/training/yolox_ddp_entry.py`

当前 YOLOX DDP 已接入：

- worker 父进程根据 `gpu_count` 启动 torchrun 子进程。
- 每个 rank 从 torchrun 环境变量解析 `rank / local_rank / world_size / device`。
- 训练数据按 rank 使用 `DistributedSampler` 或 YOLOX `InfiniteSampler` 分片。
- 训练模型使用 `torch.nn.parallel.DistributedDataParallel` 包装。
- rank0 执行 validation、checkpoint、任务事件、对象存储写入和 task result 回写。
- rank0 读取 pause / save / terminate 控制状态，并广播给其他 rank。
- rank>0 不写数据库、不写对象存储、不发送任务事件。

YOLOX DDP 仍需在真实多 GPU 机器上补硬件 smoke：短训练、pause / save / terminate、resume、validation、checkpoint、conversion 和 deployment 回归。

当前单 GPU 开发机已验证：当训练请求 `gpu_count > 1` 且机器 GPU 数量不足时，YOLOX worker 会明确拒绝 DDP 启动，不会静默回退到单 GPU 或 `DataParallel`。真实 2 GPU 机器上的吞吐、collective、checkpoint resume 和 deployment smoke 仍需单独记录。

YOLOv8 / YOLO11 / YOLO26 的 `gpu_count > 1` 仍是待替换的过渡行为。
