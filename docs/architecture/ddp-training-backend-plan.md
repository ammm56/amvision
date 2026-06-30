# DDP TrainingBackend 实现计划

## 文档目的

本文档固定多 GPU 训练的目标边界、当前状态、实现顺序和验收规则。

本文档不把单机单进程 `DataParallel` 视为完整多 GPU 训练。生产级多卡训练统一以多进程 DDP 或模型参考实现等价机制为准。

## 当前状态

当前只实现 Windows 原生单机多 GPU 训练。DDP 进程全部运行在同一台电脑上，`MASTER_ADDR` 固定使用 `127.0.0.1`，不实现多机训练、跨主机 rendezvous 或 Linux / NCCL 训练路径。

| 模型 | 当前多 GPU 行为 | 结论 |
| --- | --- | --- |
| YOLOX detection | `gpu_count > 1` 已走 DDP 子进程；同步训练入口拒绝 `DataParallel`；rank0 写任务事件和产物，rank>0 只参与训练 | 代码链路已接入；Windows 单机目标路径是 DDP + Gloo，双卡 smoke 需要确认本机 Gloo rendezvous 配置 |
| YOLOv8 / YOLO11 / YOLO26 detection | `gpu_count > 1` 已进入普通 YOLO detection DDP 启动入口；各自 core 已接入 per-rank batch、`DistributedSampler`、`DistributedDataParallel`、rank0 validation/checkpoint 和控制广播 | 代码链路已接入；Windows 单机目标路径是 DDP + Gloo，双卡 smoke 需要确认本机 Gloo rendezvous 配置 |
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

当前实现不选择 NCCL。即使 PyTorch 环境报告 NCCL 可用，平台训练入口仍固定使用 Gloo，直到项目明确进入 Linux / NCCL 生产训练阶段。

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

2026-06-30 在 Windows 双 RTX 4070 机器上执行 YOLOX detection DDP smoke。YOLOX 参考实现使用 DDP 子进程、`DistributedSampler` 和 `DistributedDataParallel`；工程落地到 Windows 时固定使用 DDP + Gloo。旧 PyTorch 2.8.0+cu128 环境会在 Gloo 进程组初始化阶段失败，错误为 `makeDeviceForHostname(): unsupported gloo device` 或 `makeDeviceForInterface(): unsupported gloo device`，失败发生在 `ProcessGroupGloo` 创建阶段，不是 YOLOX core 训练逻辑失败，也不是多机网络训练需求。当前项目基线已更新为 PyTorch 2.12.1+cu126；本地单 rank 与双 rank Gloo 探针均已通过 `TCPStore(use_libuv=False)` 和 `all_reduce`。worker 默认启用 native rank launcher，并在子 rank 中写入 `AMVISION_DDP_DISABLE_LIBUV=1`；torchrun 路径仍保留 `USE_LIBUV=0` 和 `--rdzv_conf use_libuv=0`，只作为显式关闭 native rank launcher 后的备用路径。`config/backend-worker.json` 提供 `distributed_training.gloo_socket_ifname`，只用于 Windows Gloo 在本机多网卡环境下选错 socket device 时兜底。

普通 YOLO detection 已新增：

- `backend/service/application/models/yolo_core_common/training/ddp.py`
- `backend/workers/training/yolo_detection_ddp_entry.py`
- `backend/workers/training/yolo_detection_ddp_runner.py`

当前普通 YOLO detection 已完成第一阶段：

- YOLOv8 / YOLO11 / YOLO26 worker 会在 `gpu_count > 1` 时启动 torchrun 子进程。
- torchrun 子进程会解析 `rank / local_rank / world_size / backend`，并进入对应模型 detection service。
- 单进程训练资源解析不再构建 `torch.nn.DataParallel`，直接提示必须使用 DDP TrainingBackend。

YOLOv8 / YOLO11 / YOLO26 detection 已接入真实 core rank 训练语义：

- 前端 / API `batch_size` 仍按总 batch size 解释，DDP rank 内按 `world_size` 拆成 per-rank batch，不能整除时明确拒绝。
- 训练样本通过 `torch.utils.data.distributed.DistributedSampler` 按 rank 分片。
- 训练模型使用 `torch.nn.parallel.DistributedDataParallel` 包装，不再经过 `DataParallel`。
- rank0 执行 validation、checkpoint、任务事件、对象存储写入和 task result 回写。
- rank0 读取 pause / save / terminate 控制状态，并广播给其他 rank。
- rank>0 只参与训练和 collective，不写数据库、不写对象存储、不发送任务事件。

普通 YOLO detection 仍需在真实 2 GPU 硬件上补 smoke：

- 短训练、pause / save / terminate、resume。
- validation、rank0-only checkpoint 和 task result 回写。
- conversion 与 deployment 回归。
- 吞吐、日志、失败诊断和 rank 退出状态记录。

2026-06-30 在同一台 Windows 双 RTX 4070 机器上分别执行 YOLOv8、YOLO11、YOLO26 detection DDP smoke。Ultralytics 参考实现使用标准 `torch.distributed.run` 启动临时 DDP 脚本，并在 rank 内执行 `dist.init_process_group(...)`。本项目当前只实现 Windows 单机 Gloo 路径，默认 DDP 启动方式使用本机 native rank 子进程，避免 torchrun static rendezvous 在部分 Windows PyTorch 发行版中无法显式传入 `use_libuv=False` 的问题。如果 Gloo 仍因为 hostname / socket device 选择失败，可在 `config/backend-worker.json` 的 `distributed_training.gloo_socket_ifname` 中指定本机实际可用接口，再复跑 YOLOv8 / YOLO11 / YOLO26 detection 的短训练、validation、checkpoint、conversion 和 deployment smoke。

2026-06-30 使用正式 full-chain smoke 入口在 Windows 双 RTX 4070 机器上执行 `gpu_count=2` 验收：

- YOLOX：`ddp-yolox-full-20260630-01`
- YOLOv8：`ddp-yolov8-full-20260630-01`
- YOLO11：`ddp-yolo11-full-20260630-01`
- YOLO26：`ddp-yolo26-full-20260630-01`

四个 run 在旧 PyTorch 2.8.0+cu128 环境下均完成 DatasetImport 和 DatasetExport，并在训练任务进入 DDP 子 rank 后失败。worker 日志显示失败点一致，均为 `initialize_torch_distributed -> dist.init_process_group(backend='gloo') -> ProcessGroupGloo`，底层错误为 `makeDeviceForHostname(): unsupported gloo device`。独立最小 Gloo 探针也在同一位置失败；显式设置 `GLOO_SOCKET_IFNAME` 为 `以太网`、`vEthernet (Default Switch)`、`Loopback Pseudo-Interface 1`、`lo` 等候选时会变为 `makeDeviceForInterface(): unsupported gloo device`。因此旧环境本轮未进入 validation / checkpoint / ModelVersion / ONNX / OpenVINO / TensorRT / deployment sync-async / inference / workflow 阶段，阻塞属于 PyTorch 2.8 Windows Gloo 进程组设备创建问题，不是四个 detection 模型 core 的训练逻辑失败。升级到 PyTorch 2.12.1+cu126 后，需要在双 GPU 目标机重新执行 YOLOX / YOLOv8 / YOLO11 / YOLO26 detection 的完整 DDP full-chain smoke。

现有 `tests.integration.yolo_model_full_chain_smoke` 和 `tests.integration.yolox_model_full_chain_smoke` 已覆盖 DatasetImport、DatasetExport、训练、独立 evaluation、conversion、deployment sync / async、inference 和 workflow 参数化入口，但尚未自动覆盖 save / pause / terminate / resume 控制流。DDP 初始化修复后，需要补一个训练控制 smoke，至少在 YOLOv8 detection 上完成 save、pause、resume、terminate，再复用到 YOLOX / YOLO11 / YOLO26。

## Windows / Gloo 配置

YOLOX 和普通 YOLO 多 GPU 训练当前固定为单机 PyTorch DDP + Gloo。所有 rank 都在本机进程内启动，`MASTER_ADDR` 使用 `127.0.0.1`，不做多机通信训练。

Gloo 即使用于单机，也会创建本机 TCP 通道。正常情况下不需要配置网卡；只有当 Windows 环境存在 VPN、虚拟交换机、Hyper-V 或多个 socket device，且 Gloo 自动选择失败时，才需要配置 `gloo_socket_ifname`。

backend-worker 提供以下正式配置：

```json
{
  "distributed_training": {
    "gloo_socket_ifname": null,
    "disable_libuv": true,
    "use_native_rank_launch": true
  }
}
```

- `gloo_socket_ifname`：Gloo 要绑定的网卡名称。默认 `null` 表示交给 PyTorch 自动选择；Windows 双卡 smoke 如出现 `makeDeviceForHostname(): unsupported gloo device`，应填入当前机器实际可用的本地网卡名称。
- `disable_libuv`：默认 `true`。native rank launcher 会在子 rank 中写入 `AMVISION_DDP_DISABLE_LIBUV=1`，由项目初始化逻辑显式创建 `TCPStore(use_libuv=False)`；torchrun 兼容路径会写入 `--rdzv_conf use_libuv=0` 和 `USE_LIBUV=0`。
- `use_native_rank_launch`：默认 `true`，表示 Windows / Gloo 路径优先使用本项目的本机 rank 子进程 launcher。只有需要复现 Ultralytics 原生 torchrun 行为时，才显式关闭该选项。
