# 资源删除实现与验收边界

## 当前状态

[ADR-0012](../decisions/ADR-0012-resource-deletion.md) 的统一删除链路已实现。数据集、导入、导出、训练、转换、评估、批量推理和公开部署删除统一处理数据库、受管文件和队列；前端提供删除、依赖提示、清理状态和失败重试。公开语义见[资源删除 API](../api/resource-deletions.md)。

实现覆盖已登记资源的生命周期删除，不以清空 `data/` 或重置数据库代替资源删除。测试中的模型文件可以是隔离夹具；通过删除测试不代表重新训练或执行了全部模型、GPU 与转换后端组合。

## 模块与状态

| 模块 | 职责 |
| --- | --- |
| [删除模型](../../backend/service/domain/resource_deletion.py) | 资源、文件清单和操作状态，使用 Pydantic 序列化 JSON |
| [清单编译](../../backend/service/application/resource_deletion_plan.py) | 归属、产物登记、依赖、固定目录、任务尝试和队列引用 |
| [删除服务](../../backend/service/application/resource_deletion.py) | Project 互斥、持久清单、暂存、事务、恢复、重试 |
| [Repository](../../backend/service/infrastructure/persistence/resource_deletion_repository.py) | ORM 查询与删除、恢复清单和短期回执，由 UoW 提交 |
| [LocalDatasetStorage](../../backend/service/infrastructure/object_store/local_dataset_storage.py) | 根目录和重解析点校验、同卷原子改名、严格删除 |
| [清理消费者](../../backend/workers/resource_cleanup.py) | 既有 dataset-export Worker profile 中的独立消费者，退避重试及回执整理 |
| [资源文件响应](../../backend/service/api/resource_file_response.py) | 下载整个发送期间持有占用，失败或断连后释放 |
| [前端清理面板](../../frontend/web-ui/src/shared/ui/components/ResourceCleanupPanel.vue) | 按 Project 查询未完成状态，支持刷新和重试 |

```text
取得 Project 删除操作权 → 检查依赖 → 持久化 prepared 清单
  → 原子改名暂存 → 同一事务删除业务记录并写 committed
  → 清理终态队列 → 删除暂存文件 → completed
```

提交前失败恢复原目录和记录；提交后失败保留 committed 清单及错误，不恢复半套业务记录。API 启动恢复未完成清单，API 重试与 Worker 使用相同操作互斥。活动任务、租约、发布保留和外部依赖在删除前阻塞。

同步删除完成后移除恢复记录。异步完成后仅保留精简回执，不保留文件清单；回执最多一天、最近 1000 项，由消费者整理。未完成清单不会因过期被删除。

## 删除范围

| 目标 | 一并删除 | 保留或阻塞边界 |
| --- | --- | --- |
| 导入记录 | 上传包、解压暂存、日志、导入 Task、attempts/events、Outbox 和终态消息 | 保留独立 DatasetVersion |
| 导出记录 | 导出目录、manifest、下载包、导出 Task 及附属记录 | 保留源版本；训练、评估、打包、下载占用阻塞 |
| 数据集版本 | 版本图片、类别、样本、标注及所属导入、导出 | 保留其他版本；外部任务、模型引用阻塞 |
| 数据集 | 所有版本及所属导入、导出，包括失败导入 | 不自动删除外部训练、转换和部署 |
| 训练任务 | 全部尝试、checkpoint、日志、指标、未使用 ModelVersion / ModelFile，以及无剩余版本和 build 的空 Model | 保留预置权重和输入；转换、部署、其他训练及 Workflow 引用阻塞 |
| 转换任务 | 所属 ModelBuild / ModelFile、尝试和发布文件、Task 及附属记录 | 保留源模型；仍被使用的 build 阻塞 |
| 评估、批量推理 | 受管结果、报告、预测、输入副本、Task 及附属记录 | 保留输入模型、数据集及其他资源 |
| 部署实例 | 实例、运行状态、事件目录、专属 async transfer 目录和终态消息 | sync / async 均须停止；保留模型；外部引用阻塞 |

部署 Reconciler 清除数据库中已删除且进程停止的 supervisor 缓存。不能通过删 mmap 文件强行停止活跃进程。Workflow 内部部署删除由既有生命周期服务协调，公开部署 DELETE 使用统一删除服务。

Project 删除补齐 Outbox 清理，存在未完成资源删除时阻止 Project 删除，避免丢失恢复凭据。Project 与 Workflow 原有暂存和恢复入口保留，存储层采用相同严格错误语义。

## 路径与并发

- 客户端仅提交资源类型、Project 和 id，不能提交路径或表名。
- 清单结合固定目录、TaskAttempt、登记和发布状态，不只依赖最终 Task.result。
- 拒绝存储根、公共父目录、越界、symlink / junction 及共享资源重叠路径。外部 URI、无法确认归属的自定义导出路径返回明确错误并保留记录。
- Windows 占用导致原子改名失败时保留原路径，禁止 shutil.move 回退为复制并部分删除。暂存要求同卷。
- Project 删除操作权阻止并发创建、恢复、发布、打包、下载和部署启动；数据库事务完成后释放，由清理操作权保护重试。
- Workflow 检查当前持久字段和可读取快照中的显式引用，不能推断自定义节点任意字符串或外部系统文件的所有权。

## 存量与数据库维护

当前维护命令扫描 Project 数据集目录中缺少主记录的 imports / exports / versions；清理时再次检查引用、路径和队列，不依赖旧扫描结论。

```powershell
conda activate amvision
python -m backend.maintenance.resource_cleanup scan --project-id <project-id>
python -m backend.maintenance.resource_cleanup delete-orphan --project-id <project-id> --dataset-id <dataset-id> --kind dataset-import --resource-id <import-id>
python -m backend.maintenance.resource_cleanup retry --operation-id <operation-id>
```

无法从现存记录确认 Project 的旧任务目录、存储根外的旧 conversion control 目录不自动删除。新的 conversion control 文件位于所属 attempt 目录，后续任务删除可一并清理。全局混合服务日志、外部系统副本和数据库备份不属于单资源删除范围。

SQLite 删除释放可复用页，数据库文件不一定立即缩小。停止写入服务后，在维护窗口执行：

```powershell
conda activate amvision
python -m backend.maintenance.database_compaction
```

命令校验文件、空间和写入占用，保存一致性备份后执行 VACUUM，输出前后字节数与空闲页；不会自行停止服务。备份按维护保留策略管理。MySQL / PostgreSQL 使用各自维护工具，业务删除继续走 ORM / UoW。

## 迁移与运行

迁移 c5e7f9a1b3d6 增加 resource_deletions。曾由开发初始化生成但缺少 updated_at 的表会补列和索引并保留原清单，不能以删表代替迁移。

开发使用 conda 环境 Python，发行使用包内 python/python.exe 与 app/ 源码。更新后重新 assemble-release，不能手改发行源码。前端保持 Vue 3 与本地静态分发，不增加在线依赖。

手动运行的 Worker Supervisor 和 inference daemon 不随 Uvicorn 热重载更新；消费者及缓存清理更新后须正常重启这些进程。无消费者时清单仍持久可见并支持手动重试，不能宣称自动清理完成。

## 验收证据入口

- [事务与恢复](../../tests/test_resource_deletion_service.py)、[Windows 占用、下载中断和重复容量](../../tests/test_resource_deletion_faults.py)。
- [数据集](../../tests/test_dataset_resource_deletion.py)、[训练产物](../../tests/test_training_resource_deletion.py)、[部署文件与模型保留](../../tests/test_deployment_resource_deletion.py)。
- [HTTP 与权限隔离](../../tests/test_resource_deletion_api.py)、[Worker](../../tests/test_resource_cleanup_worker.py)、[维护](../../tests/test_resource_maintenance.py)、[迁移](../../tests/test_resource_deletion_migration.py)。
- [前端确认与重试](../../tests/frontend/resources/test_resource_deletion.ts)、[独立进程浏览器验收](../../tests/test_resource_deletion_acceptance_server.py)。
- [完整发行循环](../../tests/test_resource_deletion_full_acceptance.py)：真实 full 服务中的导入、导出、打包下载、分项删除、数据集整体删除和 Project 清理；仅允许专用验收发行目录。
- 既有导入、导出、训练、转换、评估、Deployment、Project、Workflow 恢复测试继续作为回归门禁。

发行验收须确认后端从包内 app/ 加载，分别使用 CPU / NVIDIA 包内 Python；磁盘、数据库、Outbox、队列与清理暂存独立核对。独立清理进程的隔离 API 验收不等同于真实 GPU 训练、全服务拓扑或长期故障耐久验收。
