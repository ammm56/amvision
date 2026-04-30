# 当前公开 API 总览

## 文档目的

本文档用于汇总当前仓库已经公开的 REST API、WebSocket 入口、最小鉴权头规则，以及 DatasetImport、DatasetExport 与 TaskRecord 之间的公开关系。

本文档只描述当前真实实现，不展开未来接口规划。

## 统一请求头

当前公开接口通过请求头传入主体和 scope 信息。

### 最小请求头

- x-amvision-principal-id：调用主体 id
- x-amvision-project-ids：当前主体可访问的 Project id 列表，多个值用逗号分隔；为空时表示不按 Project 做可见性裁剪
- x-amvision-scopes：当前主体持有的 scope 列表，多个值用逗号分隔

### 当前公开 scope

- datasets:read
- datasets:write
- models:read
- tasks:read
- tasks:write
- system:read

## 当前公开 REST API

| 方法 | 路径 | scope | 说明 |
| --- | --- | --- | --- |
| GET | /api/v1/system/health | 无 | 返回最小健康状态和 request_id。 |
| GET | /api/v1/system/me | 仅需主体 | 返回当前主体、project_ids 和 scopes。 |
| GET | /api/v1/system/database | system:read | 返回数据库连通性检查结果。 |
| POST | /api/v1/datasets/imports | datasets:write | 上传 zip，创建 DatasetImport 和关联 TaskRecord，并提交到本地队列。 |
| GET | /api/v1/datasets/imports/{dataset_import_id} | datasets:read | 查询单条导入记录详情、校验报告和关联 DatasetVersion。 |
| GET | /api/v1/datasets/{dataset_id}/imports | datasets:read | 查询某个 Dataset 下的导入记录列表。 |
| POST | /api/v1/datasets/exports | datasets:write | 为指定 DatasetVersion 创建 DatasetExport 资源和关联 TaskRecord，并提交到本地队列。 |
| GET | /api/v1/datasets/exports/{dataset_export_id} | datasets:read | 查询单条导出记录详情，包括 manifest_object_key、export_path 和样本摘要。 |
| GET | /api/v1/datasets/{dataset_id}/versions/{dataset_version_id}/exports | datasets:read | 查询某个 DatasetVersion 下的导出记录列表。 |
| POST | /api/v1/datasets/exports/{dataset_export_id}/package | datasets:write | 为已完成的 DatasetExport 生成可下载 zip 包。 |
| GET | /api/v1/datasets/exports/{dataset_export_id}/download | datasets:read | 下载 DatasetExport 的 zip 包；当下载包不存在时会同步生成。 |
| GET | /api/v1/datasets/exports/{dataset_export_id}/manifest | datasets:read | 下载 DatasetExport 的 manifest 文件。 |
| POST | /api/v1/models/yolox/training-tasks | datasets:read + tasks:write | 以 DatasetExport 为唯一输入边界创建 YOLOX 训练任务。 |
| GET | /api/v1/models/platform-base | models:read | 列出平台基础模型及其可用 ModelVersion 摘要。 |
| GET | /api/v1/models/platform-base/{model_id} | models:read | 查询单个平台基础模型详情、版本文件和构建文件。 |
| GET | /api/v1/models/yolox/training-tasks | tasks:read | 按 Project、DatasetExport 边界和状态列出 YOLOX 训练任务。 |
| GET | /api/v1/models/yolox/training-tasks/{task_id} | tasks:read | 查询单条 YOLOX 训练任务详情和事件流。 |
| POST | /api/v1/tasks | tasks:write | 创建公开任务记录，立即返回任务详情。 |
| GET | /api/v1/tasks | tasks:read | 按公开筛选字段查询任务列表。 |
| GET | /api/v1/tasks/{task_id} | tasks:read | 查询单条任务详情；默认同时返回 events。 |
| GET | /api/v1/tasks/{task_id}/events | tasks:read | 按任务查询事件流快照。 |
| POST | /api/v1/tasks/{task_id}/cancel | tasks:write | 取消一条尚未结束的任务。 |

## system 资源组

### GET /api/v1/system/health

- 无需鉴权 scope
- 返回字段：status、request_id

### GET /api/v1/system/me

- 需要主体请求头
- 返回字段：principal_id、principal_type、project_ids、scopes

### GET /api/v1/system/database

- 需要 system:read
- 返回字段：status、database、scalar、principal_id、request_id

## DatasetImport 资源组

### POST /api/v1/datasets/imports

- Content-Type：multipart/form-data
- 当前只接受 zip 压缩包
- 成功状态码：202 Accepted
- 当前响应会同时返回：
  - dataset_import_id
  - task_id
  - queue_name
  - queue_task_id

这里的 task_id 是正式 TaskRecord id，用于后续任务查询与事件订阅；queue_task_id 只是本地持久化队列里的调度消息 id。

### GET /api/v1/datasets/imports/{dataset_import_id}

- 返回导入详情、识别结果、校验报告、metadata 和关联 DatasetVersion
- 当前详情响应会公开 task_id，便于从导入记录跳转到 tasks API

### GET /api/v1/datasets/{dataset_id}/imports

- 返回当前 Dataset 下的导入记录摘要列表
- 当前列表项也会公开 task_id

## DatasetExport 资源组

### POST /api/v1/datasets/exports

- Content-Type：application/json
- 成功状态码：202 Accepted
- 当前请求体允许显式指定：
  - project_id
  - dataset_id
  - dataset_version_id
  - format_id
  - display_name
  - output_object_prefix
  - category_names
  - include_test_split
- 当前已经正式实现并对外开放的 format_id：
  - coco-detection-v1
  - voc-detection-v1
- 导入阶段可以兼容多种外部目录结构，但导出阶段始终按 format_id 收口为单一标准格式，不沿用原始导入包目录布局
- 当前若 format_id=coco-detection-v1，则固定导出为 images/{split}/ 和 annotations/instances_{split}.json
- 成功响应会同时返回：
  - dataset_export_id
  - task_id
  - queue_name
  - queue_task_id

这里的 dataset_export_id 是正式导出资源 id，task_id 是正式 TaskRecord id。当前导出已经公开 package、download 和 manifest 下载能力，training 创建链路也已经开始以 DatasetExport 为唯一输入边界。

### GET /api/v1/datasets/exports/{dataset_export_id}

- 返回导出详情，包括：
  - task_id
  - status
  - format_id
  - manifest_object_key
  - export_path
  - split_names
  - sample_count
  - category_names
  - error_message
- 当前 status 取值为：queued、running、completed、failed
- training 前置步骤应消费 manifest_object_key，而不是直接读取 DatasetVersion 内部结构

### POST /api/v1/datasets/exports/{dataset_export_id}/package

- 需要 datasets:write
- 为已完成的 DatasetExport 生成 zip 包
- 只会打包当前 export_path，对外下载不会再切换另一种目录结构
- 当前响应返回：
  - dataset_export_id
  - export_path
  - manifest_object_key
  - package_object_key
  - package_file_name
  - package_size
  - packaged_at
- 默认下载包路径：projects/{project_id}/datasets/{dataset_id}/downloads/dataset-exports/{dataset_export_id}.zip

### GET /api/v1/datasets/exports/{dataset_export_id}/download

- 需要 datasets:read
- 返回打包后的 zip 文件
- 当下载包不存在时，当前实现会先同步打包，再直接返回文件响应
- zip 内容与对应 DatasetExport 的 export_path 保持一致

### GET /api/v1/datasets/exports/{dataset_export_id}/manifest

- 需要 datasets:read
- 返回当前 DatasetExport 对应的 manifest.json 文件

### GET /api/v1/datasets/{dataset_id}/versions/{dataset_version_id}/exports

- 返回当前 DatasetVersion 下的导出记录摘要列表
- 列表按 created_at 倒序返回，便于前端优先展示最近一次导出

### dataset_export_id 与 manifest_object_key 的关系

- dataset_export_id：平台资源主键。适合用于前端选择、详情查询、列表展示、权限校验、打包下载、审计追踪和训练任务创建。
- manifest_object_key：导出文件边界。适合用于训练 worker、离线脚本或任何直接消费导出文件的执行侧逻辑。
- 一条完成态 DatasetExport 必须稳定对应一个 manifest_object_key。
- 当前训练创建接口允许传 dataset_export_id 或 manifest_object_key；如果两者同时提供，必须指向同一个 DatasetExport。

## models 资源组

### GET /api/v1/models/platform-base

- 需要 models:read
- 当前支持的查询参数：
  - model_name
  - model_scale
  - task_type
  - limit
- 当前列表只返回 scope_kind=platform-base 的 Model，不混入任何 Project 内模型
- 当前列表项会同时公开：
  - model_id
  - project_id
  - scope_kind
  - model_name
  - model_type
  - task_type
  - model_scale
  - version_count
  - build_count
  - available_versions
- available_versions 当前会直接公开 warm_start 选择最需要的字段：model_version_id、checkpoint_file_id、checkpoint_storage_uri、catalog_manifest_object_key

### GET /api/v1/models/platform-base/{model_id}

- 需要 models:read
- 返回单个平台基础模型详情，包括：
  - 顶层模型身份字段和 metadata
  - available_versions 摘要
  - versions 完整列表
  - builds 完整列表
- versions 当前会继续展开 files，便于前端直接显示 checkpoint、manifest 和其他附属文件来源
- 如果 model_id 对应的是 Project 内模型或不存在，当前接口返回 404

### POST /api/v1/models/yolox/training-tasks

- 需要同时具备 datasets:read 和 tasks:write
- 当前请求体允许显式指定：
  - project_id
  - dataset_export_id
  - dataset_export_manifest_key
  - recipe_id
  - model_scale
  - output_model_name
  - warm_start_model_version_id
  - evaluation_interval
  - max_epochs
  - batch_size
  - gpu_count
  - precision
  - input_size
  - extra_options
  - display_name
- 当前实现会先解析并校验 DatasetExport，再创建 TaskRecord，并提交到 yolox-trainings 队列
- 当前最小真实训练执行器实际支持 fp16、fp32；precision 字段中的 fp8 当前仍保留为接口层枚举值，但执行阶段会拒绝。
- warm_start_model_version_id 表示“本次训练要从哪个已有 ModelVersion 对应的 checkpoint 开始训练”，而不是从随机初始化开始；当前服务会真实沿 ModelVersion -> ModelFile -> checkpoint 链路加载来源权重。
- 当前 warm start 来源既可以是当前 Project 自己已有的历史训练产出，也可以是平台基础模型目录中登记的 pretrained-reference ModelVersion；如需选择平台基础模型来源，可先查询 /api/v1/models/platform-base 或 /api/v1/models/platform-base/{model_id}，再把 available_versions[].model_version_id 传给 warm_start_model_version_id。
- evaluation_interval 表示每隔多少轮执行一次真实验证评估，默认 5；最后一轮会强制补做一次评估，并回写 map50、map50_95。
- 当前响应会返回：
  - task_id
  - status
  - queue_name
  - queue_task_id
  - dataset_export_id
  - dataset_export_manifest_key
  - dataset_version_id
  - format_id

### GET /api/v1/models/yolox/training-tasks

- 需要 tasks:read
- 当前支持的查询参数：
  - project_id
  - state
  - created_by
  - dataset_export_id
  - dataset_export_manifest_key
  - limit
- 当请求头没有 project_ids 时，必须显式传 project_id
- 当前列表响应会同时公开：
  - task_id
  - state
  - dataset_export_id
  - dataset_export_manifest_key
  - recipe_id
  - model_scale
  - evaluation_interval
  - gpu_count
  - precision
  - output_model_name
  - model_version_id
  - output_object_prefix
  - checkpoint_object_key
  - latest_checkpoint_object_key
  - metrics_object_key
  - validation_metrics_object_key
  - summary_object_key
- running 阶段的 output_object_prefix 和 validation_metrics_object_key 都会直接出现在顶层响应，任务推进期间还会逐 epoch 回写 progress。

### GET /api/v1/models/yolox/training-tasks/{task_id}

- 需要 tasks:read
- 默认 include_events=true
- 返回单条 YOLOX 训练任务详情，包括 task_spec、events、训练结果文件 object key、顶层 model_version_id 和 training_summary
- training_summary 当前会同时公开训练运行设备、precision、GPU 数量、evaluation_interval、output_files、validation 摘要和 warm_start 摘要
- 当前 events 会包含逐 epoch 的 progress 事件，task.progress 会同步维护 epoch、max_epochs、evaluation_interval、validation_ran、evaluated_epochs、最佳指标和当前轮指标快照
- 如果 task_id 不属于 YOLOX 训练任务，当前接口返回 404

### GET /api/v1/models/yolox/training-tasks/{task_id}/validation-metrics

- 需要 tasks:read
- 返回当前训练任务最新的 validation-metrics.json 内容
- 当前响应统一为 `file_status`、`task_state`、`object_key` 和 `payload`
- 当验证文件尚未生成时，接口返回 `file_status=pending` 和空 `payload`；任务已经结束但文件缺失时返回 404

### GET /api/v1/models/yolox/training-tasks/{task_id}/train-metrics

- 需要 tasks:read
- 返回当前训练任务最新的 train-metrics.json 内容
- 当前响应统一为 `file_status`、`task_state`、`object_key` 和 `payload`
- 当训练指标文件尚未生成时，当前接口不会返回 404，而是返回 `file_status=pending` 和空 `payload`

### GET /api/v1/models/yolox/training-tasks/{task_id}/output-files

- 需要 tasks:read
- 统一列出 `train-metrics`、`validation-metrics`、`summary`、`labels`、`best-checkpoint`、`latest-checkpoint` 这 6 个训练输出文件
- 每个条目都会返回 `file_name`、`file_kind`、`file_status`、`task_state`、`object_key`、`size_bytes` 和 `updated_at`

### GET /api/v1/models/yolox/training-tasks/{task_id}/output-files/{file_name}

- 需要 tasks:read
- 统一读取单个训练输出文件
- `summary`、`train-metrics`、`validation-metrics` 通过 `payload` 返回 JSON 内容
- `labels` 通过 `text_content` 和 `lines` 返回文本内容
- `best-checkpoint`、`latest-checkpoint` 当前只返回文件元数据，不直接返回二进制内容

## tasks 资源组

### POST /api/v1/tasks

- Content-Type：application/json
- 成功状态码：201 Created
- 请求体字段：
  - project_id
  - task_kind
  - display_name
  - parent_task_id
  - task_spec
  - resource_profile_id
  - worker_pool
  - metadata
- 返回完整任务详情，包括 task_spec 和 events

### GET /api/v1/tasks

- 当前支持的公开筛选字段：
  - project_id
  - task_kind
  - state
  - worker_pool
  - created_by
  - parent_task_id
  - dataset_id
  - source_import_id
  - limit
- 当请求头没有 project_ids 时，必须显式传 project_id

### GET /api/v1/tasks/{task_id}

- 默认 include_events=true
- 返回任务摘要字段、task_spec 和 events

### GET /api/v1/tasks/{task_id}/events

- 当前支持的查询参数：
  - event_type
  - after_created_at
  - limit

### POST /api/v1/tasks/{task_id}/cancel

- 取消尚未结束的任务
- 成功后返回更新后的任务详情和事件列表

## 当前公开 WebSocket

| 路径 | scope | 说明 |
| --- | --- | --- |
| /ws/events | 无 | 最小系统连接探针，返回 system.connected 后关闭。 |
| /ws/tasks/events | tasks:read | 按 task_id 订阅任务事件。 |

### /ws/tasks/events

请求头沿用 REST 的主体和 scope 规则。

当前支持的 query 参数：

- task_id：必填
- event_type：可选
- after_created_at：可选
- limit：可选，默认 100，最大 500

连接成功后会先收到一条 tasks.connected 事件，随后按当前筛选条件持续推送任务事件。

当前实现使用最小数据库轮询方式推送任务事件，目标是先稳定公开协议，而不是先引入复杂消息总线。

## DatasetImport、DatasetExport 与 TaskRecord 的公开关系

当前 DatasetImport 提交流程已经正式挂接 TaskRecord：

1. POST /api/v1/datasets/imports 接收 zip 并保存 package.zip
2. 同时创建一条正式 TaskRecord
3. 响应返回 dataset_import_id 和 task_id
4. backend-service 生命周期托管的 DatasetImport worker 从本地持久化队列消费任务
5. worker 在处理过程中更新 TaskRecord、追加 TaskEvent，并把结果写回 DatasetImport 和 DatasetVersion

因此，导入状态有两条公开观察路径：

- 资源视角：GET /api/v1/datasets/imports/{dataset_import_id}
- 任务视角：GET /api/v1/tasks/{task_id}、GET /api/v1/tasks/{task_id}/events、/ws/tasks/events?task_id=...

当前 DatasetExport 提交流程也已经正式挂接 TaskRecord：

1. POST /api/v1/datasets/exports 为指定 DatasetVersion 创建正式 DatasetExport 资源
2. 同时创建一条正式 TaskRecord
3. 响应返回 dataset_export_id 和 task_id
4. backend-service 生命周期托管的 DatasetExport worker 从本地持久化队列消费任务
5. worker 在处理过程中更新 TaskRecord、追加 TaskEvent，并把 manifest_object_key、export_path、split_names、sample_count 等结果写回 DatasetExport

因此，导出状态同样有两条公开观察路径：

- 资源视角：GET /api/v1/datasets/exports/{dataset_export_id}、GET /api/v1/datasets/{dataset_id}/versions/{dataset_version_id}/exports
- 任务视角：GET /api/v1/tasks/{task_id}、GET /api/v1/tasks/{task_id}/events、/ws/tasks/events?task_id=...

当前 YOLOX training 创建流程也已经开始正式挂接 DatasetExport：

1. POST /api/v1/models/yolox/training-tasks 接收 dataset_export_id 或 dataset_export_manifest_key
2. 服务先把它们解析到同一个完成态 DatasetExport
3. 再把 manifest_object_key 写入训练任务的 task_spec
4. 最终创建 TaskRecord 并入队到 yolox-trainings
5. backend-service 生命周期托管的 training worker 或独立 backend-worker 会消费该任务，并把状态推进到 running 和 succeeded

因此，当前训练创建链路的唯一输入边界不再是 DatasetVersion id，而是 DatasetExport 资源及其 manifest 文件。

## 当前未公开的资源面

- 更通用的训练、验证、转换任务规格尚未公开为稳定 API
- 更通用的训练、验证、转换任务规格尚未公开为稳定 API
- 当前公开的是最小真实 YOLOX detection 训练闭环；平台级多模型训练、统一验证任务和更通用的训练编排仍未展开

## 相关文档

- [docs/api/datasets-imports.md](datasets-imports.md)
- [docs/api/datasets-exports.md](datasets-exports.md)
- [docs/api/yolox-training.md](yolox-training.md)
- [docs/architecture/task-system.md](../architecture/task-system.md)
- [docs/architecture/backend-service.md](../architecture/backend-service.md)