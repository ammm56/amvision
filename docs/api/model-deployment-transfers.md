# 模型部署实例导出与导入

单个实例导出为 `.amvision-deployment.zip`，在目标软件的部署页选择“导入部署实例”。包包含固定推理配置、一个 ModelVersion、可选 ModelBuild、实际文件和 SHA-256 清单。导入后的同步、异步通道均停止，启动、预热和推理继续使用现有部署接口。

不包含 Workflow App、Runtime、Trigger、数据集、训练历史、源绝对路径、进程 PID 或共享内存名称。Workflow JSON 仍使用已有导出/导入；冲突副本改变部署 ID 时，需要在目标工作流中重新选择实例。

## API

前缀为 `/api/v1/projects/{project_id}/model-deployment-transfers`。当前接口要求 `models:read`、`models:write` 和目标 Project 可见权限。包不能指定目标 Project 或磁盘路径。

| 方法 / 相对路径 | 行为 |
| --- | --- |
| POST `/exports` | `{ "deployment_instance_id": "…" }`，返回 202；同实例复用已有操作 ID，处理中合并请求 |
| POST `/imports` | multipart 的 `file` 字段接收 ZIP，返回 202；后台分析 |
| GET `/` | 当前项目的短期操作列表 |
| GET `/{operation_id}` | 当前阶段、字节进度、摘要、分析问题和结果 |
| POST `/imports/{operation_id}/analyze` | 修改现场配置后重新分析 |
| POST `/imports/{operation_id}/commit` | 提交 `analysis_revision` 和非空 `idempotency_key` |
| POST `/{operation_id}/cancel` | 协作取消；进入 `importing` 后拒绝取消 |
| GET `/exports/{operation_id}/download` | 下载完整公布的导出包 |
| GET `/deployment/{id}/deletion-preview` | 返回 revision、将删模型和保留模型 |
| GET `/assets/list` | 导入模型版本/Build、来源和当前文件大小 |
| DELETE `/assets/{kind}/{id}` | 删除未被使用的导入产物；kind 为 model-version 或 model-build |

`analyze` 接受 `display_name`、`device_name`、`instance_count`、完整 `runtime_configuration`、`create_copy`。未覆盖的配置保留源值。未知运行配置字段不静默忽略；设备和运行库不满足时列出问题。TensorRT engine 的实际可加载性仍由目标机器的启动/预热确认，不承诺不同 GPU/驱动之间直接通用，不自动转换或降级。

`plan` 包含 `mapping`、`original`、`reused`、`issues`、`can_import`、目标名称/设备/配置。问题包含 code、reason、blocking；ID 冲突还包含资源类型和 ID。失败操作通过 `error` 提供原因。修正选项必须重新分析，不能使用旧摘要提交。

默认保留可用 ID。同项目已有导入模型只有内容、归属、文件和关联关系一致才可复用；现有本地训练或转换模型不会仅凭同 ID 自动合并。不同内容冲突时可显式创建副本，并显示实际映射。相同操作、相同幂等键重复提交回读已有结果，不产生第二个实例。

## 状态与文件生命周期

导出为 `pending_export → exporting → completed`；导入为 `uploading → pending_analysis → analyzing → ready/needs_attention → pending_import → importing → completed`。另有 failed、cancelled、expired。页面刷新后从数据库回读状态。

同实例重复导出使用一个操作目录和一个 `package.zip`，只合并尚在处理中的并发请求。每次新的导出都由 Worker 读取当前完整配置、固定推理语义和源文件，重新生成包含新包 ID 和生成时间的 ZIP；即使内容未变，也不复用旧 ZIP。文件先流式写入 `package.writing`，关闭后回读核对 CRC、文件大小和清单 SHA-256，全部成功后原子替换 `package.zip`。失败保留原文件，但当前操作标记失败，不把旧包作为本次成功结果返回。下载响应使用 `Cache-Control: no-store`，避免相同下载地址缓存旧包。API 请求不执行大文件哈希，回读校验不进入推理和 Trigger 链路。旧实现留下的同实例重复包，在最新包生成成功后按文件锁回收；下载占用的包留待下次导出或到期清理。

部署页在实例的导出按钮显示统一加载动效，完成后紧邻显示下载按钮；错误也显示在对应实例内。导入上传、分析、配置核对均在对话框完成，成功后关闭并刷新实例列表，不在页面顶部保留导入/导出记录。再次打开“导入部署实例”可继续未完成操作或选择新包。

消费者 `model-deployment-transfer` 位于既有 `dataset-export` Worker profile。开发环境更新后需要使该 Worker 载入新消费者；仅运行 Uvicorn 不执行文件打包和导入。发行 full 脚本按 profile 自动启动消费者。

包格式 `amvision.model-deployment.v1`：根文件 `manifest.json`，文件位于 `files/version/…` 与 `files/build/…`。拒绝路径穿越、大小写重复路径、链接、加密 ZIP、清单外文件、大小或摘要不符的文件；OpenVINO 收集 XML/BIN，ONNX 收集 external data。分析不执行模型反序列化。

导入出现 ZIP CRC 完整性错误表示包内字节损坏，不能通过跳过校验继续导入。应在源环境重新导出并下载，再上传新包；必要时比对源包、下载包和上传包的 SHA-256，以定位损坏环节。

磁盘位置相对 ObjectStore 根（默认 `data/files`）：

```text
projects/<project>/models/imported/versions/<version>/files/…
projects/<project>/models/imported/builds/<build>/files/…
projects/<project>/model-deployment-transfers/<operation>/…
```

文件先放专属暂存区；导入记录新路径后移动文件，在同一个事务中登记模型、文件归属、实例和两个 stopped 状态。提交前失败只撤回本次新建文件，复用文件不会回滚删除；提交后清理失败保留有效实例并重试清理。跨进程操作锁、状态锁和项目导入锁分别保护执行、取消/提交和目标文件移动。

`config/backend-service.json`（或对应 local JSON）的 `model_deployment_transfers` 配置：

```json
{
  "max_package_bytes": 34359738368,
  "max_unpacked_bytes": 68719476736,
  "max_manifest_bytes": 8388608,
  "max_entries": 10001,
  "temporary_retention_hours": 24,
  "receipt_retention_days": 7
}
```

Worker 使用同一服务配置段。上述数值均须为正，条目上限至少为 2。默认 24 小时清理未使用包和暂存；完成导出的下载到期后标记 expired；短期回执默认保留 7 天。恢复中的已准备文件清单不参与到期删除。长期模型不依赖操作回执存在。

## 删除与所有权

`imported_model_artifacts` 明确登记导入文件所有权；不会把旧的无训练任务模型自动改判为导入模型。数据库迁移为 `e7a9b1c3d5f8`，保留旧记录；有导入数据或操作回执时拒绝无损不可实现的 downgrade。

删除已停止实例时，同时回收未被其他实例、训练/转换或 Workflow 使用的导入 Build/版本；共享导入模型保留。本地训练、转换产物继续由其原有资源生命周期管理。删除确认显示后端实际清单，并通过已有实例 DELETE 的 `expected_revision` 复核范围，变化后不能静默扩大删除。

模型页可单独删除未被引用的导入产物。项目整体删除也清理导入归属记录、模型目录和传递暂存。文件占用等清理失败继续使用现有资源删除恢复机制。

实际验证环境、组合和边界见 [实现与验收记录](../development/model-deployment-import-export-implementation.md)。
