# 当前实现状态

## 文档目的

本文档用于同步当前主干已经落地的整体框架、主要代码落点、YOLOX 端到端能力范围和下一步收敛重点。

本文档补充 [system-overview.md](system-overview.md) 的长期架构视角，重点回答“当前代码已经做到哪里”。

## 适用范围

- backend-service、BackgroundTaskManager、deployment process supervisor 的当前装配方式
- YOLOX 训练、人工验证、评估、转换、部署和推理的已落地链路
- 当前公开 REST / WebSocket 资源面与主要运行时矩阵
- 下一步优先补强事项

## 当前结论

- 以 YOLOX 为中心的训练 -> 人工验证 -> 数据集级评估 -> 转换 -> DeploymentInstance 发布 -> 同步 / 异步推理接口闭环已经打通。
- backend-service 当前承担 REST / WebSocket 控制面和 deployment process supervisor，全部队列消费者已经收敛到独立 worker profile。
- 当前公开 REST v1 已覆盖 datasets、dataset-exports、models、yolox training tasks、validation-sessions、conversion-tasks、evaluation-tasks、deployment-instances、inference-tasks、projects 目录与对象读取、workflow runtime 资源和 tasks。
- workflow 公开资源面已经拆成 preview-runs、execution-policies、app-runtimes、runs 和 trigger-sources；当前开始把状态集合、snapshot 路径和 preview cleanup 规则收敛到共享 contracts 语义，避免 route、service、maintenance 和文档继续各写一份。
- 当前公开 WebSocket 已覆盖 system、tasks、workflows.preview-runs、workflows.runs、workflows.app-runtimes、deployments 和 projects 七类资源流；统一的路由分层、重连规则和项目级聚合流边界已整理到 [websocket-architecture.md](websocket-architecture.md)。
- backend-service 当前已经补齐本地前端接入所需的 CORS、hybrid auth、Project 目录接口和 Project 内对象读取接口；主要工作台列表接口已经统一到 offset/limit + 响应头分页规则。
- 当前代码形态仍然是“模块化单体 + 本地队列 + 本地对象存储 + 独立 deployment 子进程”。下一步重点应转向拓扑收敛、运行时硬化和平台泛化，而不是继续补 YOLOX 基础闭环缺口。

## 当前整体框架

### backend-service 控制面

- FastAPI 应用入口位于 `backend/service/api/app.py`，负责装配 settings、数据库会话、本地对象存储、本地队列、中间件、异常处理、REST 路由和 WebSocket 路由。
- backend-service settings 位于 `backend/service/settings.py`，当前已经统一管理 CORS、auth mode、静态 token 和 Project 目录配置。
- 启动编排位于 `backend/service/api/bootstrap.py`，负责在应用生命周期内初始化 SessionFactory、LocalDatasetStorage、LocalFileQueueBackend 和 deployment process supervisor。
- REST v1 路由汇总位于 `backend/service/api/rest/v1/router.py`，当前已经挂载 system、projects、workflows、workflow runtime、datasets、dataset-exports、models、yolox-training-tasks、validation-sessions、conversion-tasks、evaluation-tasks、deployment-instances、inference-tasks 和 tasks。
- REST v1 列表分页辅助函数位于 `backend/service/api/rest/v1/pagination.py`，当前用于 projects、workflow templates、template versions、applications、execution-policies、preview-runs、app-runtimes 和 trigger-sources。
- WebSocket 路由位于 `backend/service/api/ws/router.py`，当前已经公开 system、tasks、workflow preview-runs、workflow runs、workflow app-runtimes、deployments 和 projects 聚合流入口。

### 后台执行与 runtime 面

- 队列消费者分别落在 `backend/workers/datasets/`、`backend/workers/training/`、`backend/workers/conversion/`、`backend/workers/evaluation/` 和 `backend/workers/inference/`。
- 当前独立 worker 已经支持通过 `config/backend-worker.json` 的 `task_manager.enabled_consumer_kinds` 统一装配六类消费者，也支持通过 `runtimes/manifests/worker-profiles/*.json` 以单一职责 profile 启动独立 worker。
- deployment 运行时位于 `backend/service/application/runtime/`，当前由 `yolox_deployment_process_supervisor.py` 管理父进程监督、由 `yolox_deployment_process_worker.py` 管理子进程内模型会话、warmup、keep_warm 和健康状态。
- runtime 适配与统一预测入口位于 `yolox_predictor.py`、`model_runtime.py`、`yolox_inference_runtime_pool.py` 和 `yolox_runtime_target.py`，用于把 pytorch、onnxruntime、openvino、tensorrt 收敛为统一推理契约。

### 关键对象与执行边界

- DatasetExport 是训练和评估的正式执行边界，不直接让训练或评估逻辑读取原始 DatasetVersion 目录结构。
- TrainingTask 负责把训练结果登记为 ModelVersion，并关联 checkpoint、summary、metrics、labels 等输出文件。
- ValidationSession 用于训练后的单图人工验证，解决“模型看起来是否正确”的快速抽样检查。
- EvaluationTask 负责基于 DatasetExport 做数据集级回归评估，输出 report、detections 和可选 result-package。
- ConversionTask 负责把 ModelVersion 转成一个或多个 ModelBuild，形成正式部署输入。
- DeploymentInstance 负责把 ModelVersion 或 ModelBuild 绑定到 runtime backend、device、precision 和 deployment metadata。
- InferenceTask 与同步 `/infer` 都只绑定 DeploymentInstance，不直接暴露 checkpoint 路径。

## 当前运行时与发布矩阵

### 训练、验证与评估

- 当前真实训练链路基于 PyTorch checkpoint，训练期 validation 已在训练任务内部接通。
- 当前 `validation-sessions` 用于训练后的人工单图验证，沿用 PyTorch 模型版本和统一预测结果结构。
- 当前 `evaluation-tasks` 用于数据集级回归评估，最小执行边界为 `coco-detection-v1` DatasetExport。

### 转换输出

- 当前 conversion 已真实接通 `onnx`、`onnx-optimized`、`openvino-ir` 和 `tensorrt-engine` 四类目标。
- 当前 OpenVINO IR 创建接口按 `fp32` / `fp16` 拆分。
- 当前 TensorRT engine 创建接口按 `fp32` / `fp16` 拆分，并把 build precision 与 TensorRT 版本回写到 `ModelBuild.metadata`。

### 部署运行时

- 当前 deployment 已真实接通 `pytorch fp32/fp16 cpu/cuda`。
- 当前 deployment 已真实接通 `onnxruntime fp32 cpu`。
- 当前 deployment 已真实接通 `openvino fp32 auto/cpu/gpu/npu + fp16 gpu/npu`。
- 当前 deployment 已真实接通 `tensorrt fp32/fp16 cuda`。
- 当前每个 DeploymentInstance 在 sync 和 async 两个通道上各自拥有独立的 deployment 子进程监督单元，不共享会话池。

## 当前实现细节中需要明确的事实

- 当前公开的 sync / async deployment 控制面已经包含 `start`、`status`、`stop`、`warmup`、`health` 和 `reset`，并公开 keep_warm、pinned output buffer、restart_count safe counter 等长期运行观测字段。
- 当前 keep_warm 成功次数、失败次数和 deployment restart_count 都采用 JavaScript 安全整数窗口值加 rollover_count 的公开语义，避免长时间运行后的前端数值精度丢失。
- 当前 `backend/workers/main.py` 已经以统一 registry 装配 dataset import、dataset export、training、conversion、evaluation 和 inference 六类消费者；backend-service 不再托管任何队列消费者。
- 当前 preview run snapshot 根目录已经稳定到 `workflows/runtime/preview-runs/{preview_run_id}/`，并继续通过显式 maintenance 命令 `cleanup-preview-runs` 清理；当前清理顺序仍是“先删数据库记录，再删 snapshot 目录”，还没有做到跨存储原子提交。
- 当前 app runtime snapshot 根目录已经稳定到 `workflows/runtime/app-runtimes/{workflow_runtime_id}/`；application、template 和 execution-policy snapshot 都按这个根目录组织，供 runtime worker 和后续发布形态复用。
- 当前仓库已经提供 `backend.maintenance.main`、Python launchers、bat/sh wrapper、worker profile manifest，以及 `assemble-release` 命令来生成单一 `full` 发行目录。
- 当前 release 组装会复制完整项目代码和仓库根目录的 `requirements.txt`，不做源码裁剪，也不再维护多套运行时依赖配置。
- 当前真正还未落地的是 bundled Python 二进制和 site-packages 本体；发行目录里的 `python/` 只会被创建为空目录，后续由手工复制填充。

## 下一步建议

### 1. 补强独立 worker 的运行时约束

- 明确不同部署形态下各 worker profile 的并发上限、资源绑定和故障隔离规则，避免只完成“职责拆分”而没有补齐运维边界。
- 为 inference、conversion、training 三类 profile 补充更细的现场部署建议和监控项。

### 2. 补强运行时回归与 benchmark

- 为 pytorch、onnxruntime、openvino、tensorrt 的已支持组合补齐最小 smoke test、精度回归和时延基线。
- 把 conversion report、evaluation report 与 deployment benchmark 的字段进一步收敛成可比较、可回滚的统一结构。

### 3. 从 YOLOX 闭环走向平台能力

- 以现有 YOLOX 链路为样板，继续抽象 `ModelRuntime`、`TrainingBackend`、`ConversionBackend` 和节点扩展边界，让 YOLOX 成为平台里的第一个完整实现，而不是唯一实现。
- 把更多 runtime 相关差异从具体路由和 YOLOX 细节里继续抽离到稳定接口。

### 4. 完成工程化交付面

- 把同目录 Python 运行时、前端构建产物和 `custom_nodes` 资产真正纳入 `assemble-release`，让 `release/full/` 能直接成为完整可交付目录。
- 补充运行日志、指标、排障和部署手册，让已完成的链路能够稳定交付给 `full` 发布目录及其后续手工派生变体。