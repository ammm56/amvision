# 当前实现状态

本文只描述当前主干已经成立的系统能力和运行边界，不记录修复批次、历史缺口或下一阶段任务。

## 产品定位

AMVision 是本地优先的工业视觉服务平台。平台负责数据集、训练、评估、转换、模型部署、推理、Workflow 编排、Trigger 和外部协议集成，不直接承担相机、PLC 或设备控制器的核心职责。特殊硬件和行业能力通过 Custom Node 或协议 adapter 扩展。

## 运行拓扑

```text
Vue Web UI / SDK / external system
                 │
          backend-service
      REST / WebSocket / control
        │        │          │
 ObjectStore  Workflow    QueueBackend
                Runtime       │
        isolated process      ├─ dataset-import
                              ├─ dataset-export
 inference daemon             ├─ training
   └─ Deployment process      ├─ conversion
                              ├─ evaluation
 LocalBuffer / mmap / ZMQ     └─ inference
```

- `backend-service` 是控制面，不嵌入后台任务消费者。
- inference daemon 是 DeploymentInstance 进程和推理数据面的唯一常驻所有者。
- full Supervisor 是完整发行拓扑的唯一启动、健康、恢复和停止入口。
- 六个 Worker Profile 使用严格 manifest、Topology generation/epoch、单 Profile 锁和心跳。
- Workflow Runtime 使用独立进程，但可信 Core/Custom Node 在该 Runtime 进程内直接执行，不为每个节点新建隔离进程。

## 数据集链路

已实现统一 DatasetImport、DatasetVersion、DatasetExport、Task 和文件引用链路。公开格式由格式注册表驱动，不登记不可执行的占位格式。

当前主要任务类型：

- classification
- detection
- segmentation
- pose
- obb

格式细节见 [模型数据集格式](model-dataset-format-contract.md) 和各 `classification-*`、`coco-*`、`voc-*`、`yolo-*`、`dota-*` 文档。

## 模型链路

YOLOX、YOLOv8、YOLO11、YOLO26 和 RF-DETR 按各自模型边界接入本项目的训练、评估、转换、部署和推理层。运行时代码不直接依赖 `projectsrc/` 参考仓库。

转换目标：

- ONNX
- OpenVINO IR
- TensorRT engine

模型与任务的准确组合以 [模型支持矩阵](model-support-matrix.md) 为准；训练输入、checkpoint、验证/test 隔离和来源追踪分别见 [输入尺寸规则](model-training-input-size-rules.md)、[训练与评估契约](model-training-evaluation-contract.md) 和 [模型产物来源](model-artifact-provenance.md)。

RF-DETR 训练与转换复用同一 `input_size` 模型构建入口，position embeddings 按训练时 divisor 对齐后的 resolution 重建；导出和部署继续使用严格权重加载，不通过忽略 mismatch 绕过错误。

## Deployment 与推理

- DeploymentInstance 保存期望状态和运行时配置。
- inference daemon 负责启动、预热、停止、恢复和健康状态。
- 同步调用容量不足时直接返回错误，不在服务内引入隐藏排队或自动重试。
- OpenVINO CPU 有效线程按当前 Deployment 自身的实例数、运行策略和主机能力计算，不按仓库中全部 Deployment 数量静态限制。
- 本机高性能图片数据面使用 LocalBufferBroker、mmap mailbox 和 ZeroMQ；大图片不以 Base64 JSON 在进程间重复复制。
- `image-ref.v1` 支持 ObjectStore 相对路径与显式磁盘绝对路径；调用方必须提供与实际内容一致的 `media_type`。

## Workflow

- 编辑态 Preview 与正式 WorkflowAppRuntime 共享节点执行语义和 LocalBuffer 图片链。
- Preview 事件使用逐条 append 的事件文件；页面可显示阶段耗时和节点最近一次执行耗时。
- 正式 Runtime 固定不可变 Workflow App 版本，Trigger 绑定稳定 Runtime id。
- Runtime 切换通过 revision generation 完成，第三方调用 id 不变化。
- 请求开始时固定 revision、generation、snapshot fingerprint 和 worker instance；迟到的旧 epoch 响应不能污染新版本。
- sync、async、Trigger 与取消路径保留 Run 的版本和 worker 来源；活动 Run 会阻止删除或切换。
- Workflow App 草稿保存采用 Application + Template bundle、持久 journal 和 lifecycle CAS，避免发布读到撕裂草稿。

完整契约见 [Workflow 运行时](workflow-runtime.md) 和 [Workflow App 版本管理](workflow-app-versioning.md)。

## 节点系统

- Core Node 保存平台通用数据、逻辑、模型和 Workflow 原语。
- Custom Node 保存 OpenCV、相机、PLC、条码、YOLOE、SAM3 等可插拔能力。
- Node Pack 必须提供 manifest、版本、capability、参数 schema、timeout 和禁用机制。
- Core/Custom Node 都由使用者显式启用和导入，当前 Runtime 进程内直接调用，避免逐节点跨进程开销。
- 图片输出参数统一使用 `save_location`，支持 ObjectStore 相对位置和磁盘绝对位置。

## 前端

前端统一使用 Vue 3、TypeScript、Vite、Pinia 和 Vue Router，覆盖数据集、任务、模型、部署、Workflow、Trigger、设置和诊断页面。Workflow 编辑器已实现节点组、图片交互取参、Preview 输入、节点耗时、版本发布、Runtime 选版、归档/恢复和稳定 Trigger 管理。

## 持久化与迁移

- SQLAlchemy 2 Repository + Unit of Work 是业务持久化入口。
- SQLite 是默认数据库，Alembic revision 必须保持 MySQL/PostgreSQL 可迁移性。
- full Supervisor 在其他常驻组件前执行 `upgrade head`；开发态必须显式迁移。
- Project、Workflow Application/Template、版本发布和 Runtime 控制使用持久 lifecycle/CAS 边界，避免删除与并发写产生孤儿资源。
- Workflow Run 持久化 revision、version、generation、snapshot fingerprint 和 `worker_instance_id`，历史记录不会随 Runtime 切换改写。

## 发布与运维

已实现 Windows x64 CPU 与 Windows x64 NVIDIA 完整发行 profile。发行目录包含后端源码副本、前端静态资源、配置、manifest、launcher、Custom Node 和目标 runtime 资产；`python/` 由发布人员维护并随目录交付。

默认日志位于 `logs/full-stack/`，按本地日期写入：

- `database-migration-YYYYMMDD.log`
- `inference-daemon-YYYYMMDD.log`
- `backend-service-YYYYMMDD.log`
- `backend-worker-<profile>-YYYYMMDD.log`

启动、首次部署和排障分别见 [开发环境启动](../deployment/development-environment.md)、[首次部署清单](../deployment/full-first-deploy-checklist.md) 和 [运维文档](../operations/README.md)。

## 事实来源

| 范围 | 权威来源 |
| --- | --- |
| API | OpenAPI、`backend/contracts/`、[API 文档](../api/README.md) |
| 模型能力 | 模型/任务注册表与 [支持矩阵](model-support-matrix.md) |
| 数据格式 | 格式注册表与 [格式规范](model-dataset-format-contract.md) |
| Worker | `runtimes/manifests/worker-profiles/` 与 `backend/workers/contracts.py` |
| 发布 | `runtimes/manifests/release-profiles/` 与 `backend/maintenance/release_assembly.py` |
| Workflow 版本 | Alembic、Workflow repository/service 与 [版本契约](workflow-app-versioning.md) |
| 前端命令 | `frontend/web-ui/package.json` |

文档与事实来源冲突时，以当前代码、迁移和通过的自动化测试为准，并在同一修复中更新文档。
