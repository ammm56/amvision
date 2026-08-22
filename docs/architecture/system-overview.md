# 平台总览

## 产品定位

AMVision 是本地优先的工业视觉服务平台，覆盖数据集、训练、评估、模型转换、部署推理、Workflow 编排、Trigger 与现场系统协议集成。平台不是相机、PLC、机械臂或 IO 控制器；硬件直连和行业特化能力通过外部系统或显式安装的 Node Pack 接入。

目标部署形态为 standalone、workstation 和 edge，本地运行不依赖云对象存储、外部 Redis/MQ、系统 Python、系统 Node.js 或在线 CDN。

## 当前拓扑

```text
Browser / SDK / HMI / MES / PLC gateway
                  │ REST / WebSocket / ZeroMQ
                  ▼
            backend-service
        ┌─────────┼──────────┐
        │         │          │
        ▼         ▼          ▼
 Database +   Outbox       LocalBufferBroker
 ObjectStore  Dispatcher    (mmap data plane)
                  │
                  ▼
             QueueBackend
                  │
                  ▼
          six Worker Profiles

 backend-service ──control──> inference daemon
        │                         │
        │                         └─ Deployment processes
        └─ Workflow manager
              ├─ Workflow Runtime processes
              └─ Trigger Source adapters
```

完整发行由 full Supervisor 统一拥有：先执行 Alembic migration，再启动 inference daemon、backend-service 和六类 Worker Profile，并管理健康、日志、Profile 恢复和停止。

## 模块职责

### Web UI

Vue 3 + TypeScript + Vite 前端，提供 Project、Task、Dataset、Model、Deployment、Inference、Workflow、Trigger、Custom Node 和 Settings 工作台。前端只通过版本化 API、WebSocket 和公开协议访问后端，不 import 后端内部实现。

### backend-service

FastAPI 控制面，负责：

- 本地鉴权、Project scope 和公开 API；
- 数据集、任务、模型、部署、Workflow 与 Trigger 资源；
- 同一事务写 Task/事件/Outbox，由 Dispatcher 可靠提交 QueueBackend，并提供状态查询；
- inference daemon 与 Workflow Runtime 控制；
- ObjectStore、LocalBuffer 和事件流装配；
- 版本发布、恢复、归档、回滚和 mutation fence。

它不消费后台任务队列，也不在 HTTP handler 中运行长时训练、转换或正式 Workflow。

### Worker Profiles

独立 Profile 分别消费 dataset-import、dataset-export、training、conversion、evaluation 和 batch-inference。持久任务先按 `task_id + attempt_no` 原子领取 TaskAttempt，再执行 Runner 并回写 Task/Attempt/Event；重复投递或失去 lease 的旧执行者不能重复副作用或覆盖终态。Worker 不拥有公开 API。

### inference daemon 与 Deployment

inference daemon 是 DeploymentInstance 进程的唯一控制 owner。模型通过 PyTorch、ONNXRuntime、OpenVINO 或 TensorRT predictor 长期加载，支持 sync/async、warmup、health、reset、stop 和进程恢复。

Training/CUDA Conversion 使用跨进程独占 GPU/MIG lease，CUDA Deployment 在实例生命周期持有共享 reservation；单次 inference 请求不获取 OS 锁。

Deployment 数量表示已发布实例，不等于同时调用数。OpenVINO CPU effective thread 只按当前 deployment 自身 instance_count 和主机能力计算；不同空闲 deployment 不静态瓜分全部物理核心。

### Workflow Runtime 与 Trigger

Workflow App 草稿发布为不可变 Version。稳定 Runtime id 通过 revision/generation 选择版本，Trigger 和第三方 SDK 始终绑定 Runtime。切版和回滚不改变第三方调用地址。

Preview 在 backend-service 进程内直接执行；生产 Workflow 在独立常驻进程执行。请求固定 version/revision/generation/fingerprint/worker epoch，旧进程事件不能污染当前状态。

### LocalBufferBroker

同机大图片和视频帧使用 mmap 与 BufferRef/FrameRef 传输。JSON/ZeroMQ 控制消息不复制整张图片。需要持久化的输入输出使用 ObjectStore 或显式磁盘保存位置。

### Node Pack

核心节点位于 `backend/nodes/`，行业规则、协议、硬件桥接、YOLOE、SAM3 等扩展位于 `custom_nodes/`。每个包必须有 manifest、version、capabilities、schema、timeout 和启用边界。

## 端到端链路

### 数据集

```text
zip upload
  -> DatasetImport + Task
  -> safe extract / format validation
  -> immutable DatasetVersion
  -> DatasetExport
```

导入、导出和训练只接受格式注册表中已实现的组合；准确范围见 [数据格式参考](../reference/datasets/README.md)。训练读取经过校验的 DatasetVersion / DatasetExport，不直接读取原始 zip。

### 模型

```text
DatasetExport
  -> TrainingTask
  -> checkpoint + ModelVersion
  -> Validation / Evaluation
  -> ONNX / OpenVINO / TensorRT ModelBuild
  -> DeploymentInstance
  -> sync / async inference
```

模型和任务组合以运行时注册表与 [模型支持矩阵](../reference/models/support-matrix.md) 为准，架构文档不复制第二份静态矩阵。

### Workflow

```text
edit graph + application
  -> Preview
  -> publish immutable App Version
  -> create/select stable Runtime revision
  -> start worker
  -> bind Trigger Source
  -> sync/async/trigger invoke
  -> Workflow Run provenance
```

Workflow 节点可调用已发布 Deployment，也可执行 OpenCV、逻辑、协议和自定义节点。模型 session 不嵌入 Workflow JSON；图只保存稳定资源引用和节点参数。

### 外部系统

当前公开入口包括 REST、WebSocket、ZeroMQ Trigger、Modbus TCP polling、directory-poll 与 directory-watch。未实现的 MQTT、gRPC、其他 PLC driver 或相机直连不进入 capability；需要时通过新的 Trigger adapter 或 Node Pack 实现。

## 数据与追溯

- Database 保存元数据、状态、版本和引用关系；
- ObjectStore 保存平台托管文件；
- LocalBuffer 保存执行期共享内存数据；
- Task/Attempt/Event 追溯后台任务；
- ModelVersion/Build 追溯训练和转换产物；
- App Version/Runtime Revision/Run 追溯 Workflow；
- manifest、fingerprint、generation、operation id 和 worker instance id 提供并发 fence。

历史资源不可通过更新“伪装成新版本”。发布、回滚、重试和恢复都创建或保留可审计记录。

## 稳定性原则

- 重任务与长期模型/Workflow 进程和 API 控制面分离；
- 满载立即返回明确冲突，不引入隐藏排队和重试；
- 控制面使用短事务 CAS，文件 I/O 和进程启动不持长事务；
- heartbeat/health 使用精确 topology、revision 和 epoch；
- 日志按 `YYYYMMDD` 每日文件追加；
- schema 只由 Alembic 演进；
- 发行目录由 assemble-release 生成，不手工修改；
- `projectsrc/` 只用于参考审计，不进入运行时。

## 文档入口

- [项目结构](project-structure.md)
- [Backend Service](platform/backend-service.md)
- [任务系统](platform/task-system.md)
- [模型工作流边界](models/workflow-boundaries.md)
- [Workflow Runtime](workflows/runtime.md)
- [数据与文件](platform/data-and-files.md)
- [部署指南](../deployment/README.md)
- [API 与集成](../api/README.md)
