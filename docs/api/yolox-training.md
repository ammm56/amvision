# YOLOX Training 接口文档

## 文档目的

本文档用于说明当前已经公开的 YOLOX training 创建、列表和详情接口，以及 DatasetExport 在训练创建链路中的输入边界语义。

当前这一版已经公开最小真实训练执行链，并把训练输出文件目录、训练摘要和验证结果文件作为当前阶段的正式查询面。

## 适用范围

- YOLOX training 任务创建接口
- YOLOX training 列表与详情接口
- dataset_export_id 与 manifest_object_key 的解析规则
- 当前 scope 要求
- 当前能力边界

## 接口入口

- FastAPI Swagger UI：/docs
- FastAPI OpenAPI JSON：/openapi.json
- 版本前缀：/api/v1
- 资源分组：/models

## 鉴权规则

### 最小请求头

- x-amvision-principal-id：调用主体 id
- x-amvision-project-ids：当前主体可访问的 Project id 列表，多个值用逗号分隔；为空时表示不按 Project 做可见性裁剪
- x-amvision-scopes：当前主体持有的 scope 列表，多个值用逗号分隔

### scope 要求

- datasets:read
- tasks:read
- tasks:write
- 如需先查询可用 warm start 来源，还需要 models:read 访问平台基础模型接口

## 接口清单

### POST /api/v1/models/yolox/training-tasks

创建一个以 DatasetExport 为唯一输入边界的 YOLOX 训练任务，并提交到 yolox-trainings 队列。

#### Content-Type

- application/json

#### 请求体字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | string | 是 | 所属 Project id。 |
| dataset_export_id | string \| null | 否 | 训练输入使用的 DatasetExport id。 |
| dataset_export_manifest_key | string \| null | 否 | 训练输入使用的导出 manifest object key。 |
| recipe_id | string | 是 | 训练 recipe id。 |
| model_scale | string | 是 | 训练目标的模型 scale。 |
| output_model_name | string | 是 | 训练完成后要登记的模型名。 |
| warm_start_model_version_id | string \| null | 否 | warm start 使用的 ModelVersion id；当前会真实沿 ModelVersion -> ModelFile -> checkpoint 链路加载来源权重。该 ModelVersion 可以来自历史训练产出，也可以来自平台级预训练模型目录。 |
| evaluation_interval | integer \| null | 否 | 每隔多少轮执行一次真实验证评估，默认 5；最后一轮会强制补做一次评估。 |
| max_epochs | integer \| null | 否 | 最大训练轮数。 |
| batch_size | integer \| null | 否 | batch size。 |
| gpu_count | integer \| null | 否 | 请求参与训练的 GPU 数量；需要是正整数。未指定时按运行环境自动解析，无可用 GPU 时会回退到 CPU 训练。 |
| precision | string \| null | 否 | 请求使用的训练 precision；当前接口字段只接受 fp16、fp32。未指定时默认 fp32。 |
| input_size | array[integer] \| null | 否 | 训练输入尺寸；未指定时默认使用 [640, 640]。 |
| extra_options | object | 否 | 附加训练选项。 |
| display_name | string | 否 | 可选的任务展示名称。 |

#### warm_start_model_version_id 说明

- warm start 表示本次训练不会从随机初始化开始，而是先加载一个已有 ModelVersion 对应的 checkpoint，再基于当前 DatasetExport 继续训练。
- warm_start_model_version_id 表示这次训练要使用哪一个已有 ModelVersion 作为初始权重来源。
- 当前项目里使用 warm start 的主要目的有三类：
  - 以平台基础预训练模型作为训练底座，再针对当前数据集做微调。
  - 以历史训练产出的 ModelVersion 作为起点，继续追加训练、补数据重训或阶段性迭代。
  - 为训练结果保留清晰的版本血缘，明确当前产出是从哪个旧版本继续演化出来的。
- 当前服务会按 ModelVersion -> ModelFile -> checkpoint 的链路解析这个参数，并把对应 checkpoint 真实加载到训练模型中。
- 当前可用来源分两类：
  - 当前 Project 自己已有的历史训练产出。
  - 平台基础模型目录中登记的 pretrained-reference ModelVersion。
- 当使用平台基础模型做 warm start 时，推荐先调用 GET /api/v1/models/platform-base 或 GET /api/v1/models/platform-base/{model_id}，再把 available_versions[].model_version_id 填入这个字段。

#### evaluation_interval 说明

- evaluation_interval 表示“每隔多少个 epoch 才做一次真实验证评估”，默认值为 5。
- 真实验证评估会在验证集上计算 validation loss，并额外执行一次 COCO mAP 评估，当前会回写 map50 与 map50_95。
- 即使当前 epoch 不满足整除条件，最后一轮也会强制执行一次评估，确保训练结束时一定产出最新验证结果。

#### 当前默认训练配置

- input_size 未显式指定时，真实训练默认使用 [640, 640]。
- precision 未显式指定时，默认使用 fp32。
- 当前训练支持 CPU 执行；当环境没有可用 GPU 或未分配 GPU 时，会回退到 CPU 训练。这个模式主要用于最小硬件支持和开发环境验证，训练速度会明显变慢。

#### 输入边界规则

- dataset_export_id 和 dataset_export_manifest_key 至少需要提供一个。
- 如果两者都提供，服务会校验它们是否解析到同一个 DatasetExport。
- 训练创建只接受 completed 状态且具备 manifest_object_key 的 DatasetExport。

#### 成功响应

- 状态码：202 Accepted

```json
{
  "task_id": "task-5b6b31a7f8de",
  "status": "queued",
  "queue_name": "yolox-trainings",
  "queue_task_id": "queue-task-07ac50f4c978",
  "dataset_export_id": "dataset-export-553f95f566af",
  "dataset_export_manifest_key": "projects/project-1/datasets/dataset-1/exports/dataset-export-553f95f566af/manifest.json",
  "dataset_version_id": "dataset-version-1",
  "format_id": "coco-detection-v1"
}
```

### GET /api/v1/models/yolox/training-tasks

按 Project 和 DatasetExport 边界列出当前可见的 YOLOX 训练任务。

#### 查询参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | string \| null | 条件必填 | 当请求头没有 project_ids 时必须显式提供。 |
| state | string \| null | 否 | 训练任务状态。 |
| created_by | string \| null | 否 | 提交主体 id。 |
| dataset_export_id | string \| null | 否 | 按 DatasetExport id 过滤。 |
| dataset_export_manifest_key | string \| null | 否 | 按 manifest object key 过滤。 |
| limit | integer | 否 | 最大返回数量，默认 100。 |

#### 列表场景

- DatasetExport 详情页拿到 dataset_export_id 后，可以直接调用这个接口查询关联训练任务。
- 前端任务面板可以按 state 或 created_by 继续做局部过滤。
- 已完成任务会在顶层直接返回 model_version_id，前端可以据此跳转模型详情或转换链路。
- 列表响应当前还会直接公开 gpu_count、precision、output_object_prefix、checkpoint_object_key、latest_checkpoint_object_key、metrics_object_key、validation_metrics_object_key、summary_object_key，便于训练卡片直接显示配置和输出文件入口。
- output_object_prefix 在 running 阶段就会进入顶层响应，不再只存在于 metadata。

### GET /api/v1/models/yolox/training-tasks/{task_id}

返回一条 YOLOX 训练任务详情。

#### 查询参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| include_events | boolean | 否 | 是否返回任务事件列表，默认 true。 |

#### 当前详情重点字段

- task_spec：训练请求规格快照
- dataset_export_id：平台资源边界
- dataset_export_manifest_key：执行文件边界
- model_version_id：训练输出登记后的顶层 ModelVersion id
- output_object_prefix：当前训练输出目录前缀
- checkpoint_object_key：当前训练最佳 checkpoint 文件
- latest_checkpoint_object_key：当前训练结束时的最新 checkpoint
- metrics_object_key：当前训练指标文件
- validation_metrics_object_key：当前训练验证指标文件
- summary_object_key：当前训练摘要文件
- training_summary：当前训练摘要
- events：任务事件流

#### 当前运行期进度回写

- 任务进入 running 后，顶层 output_object_prefix 会立即可见，前端可以直接定位当前训练目录。
- running 阶段会提前公开 output_object_prefix、checkpoint_object_key、latest_checkpoint_object_key、metrics_object_key、validation_metrics_object_key 和 summary_object_key。
- 训练过程会继续按 epoch 增量写 train-metrics.json；当当前轮执行了真实验证评估时，也会同步刷新 validation-metrics.json。
- 当前运行期的实时指标仍会同步回写到 task.progress；如果需要把 checkpoint 落盘用于人工验证，应调用手动保存或暂停接口。
- 每个 epoch 完成后都会追加一条 progress 事件，并同步更新 task.progress。
- 当前 progress 负载会带 stage、percent、epoch、max_epochs、evaluation_interval、validation_ran、evaluated_epochs、current_metric_name、current_metric_value、best_metric_name、best_metric_value、train_metrics、validation_metrics。
- 当 validation_ran=true 时，validation_metrics 当前会同时携带 total_loss、iou_loss、conf_loss、cls_loss、map50、map50_95；当本轮未执行评估时，validation_metrics 会为空对象。

### POST /api/v1/models/yolox/training-tasks/{task_id}/save

为 running 状态的训练任务追加一次手动保存请求。

#### 当前用途

- 训练继续执行，但会在下一个 epoch 边界把 latest checkpoint 写到磁盘。
- 当前接口只负责登记 save 请求；真正的落盘发生在 worker 处理到下一轮完成时。

### POST /api/v1/models/yolox/training-tasks/{task_id}/pause

为 running 状态的训练任务请求暂停。

#### 当前用途

- 服务会在下一个 epoch 边界先保存 latest checkpoint，再把任务状态切到 `paused`。
- `paused` 后可以基于 latest checkpoint 做人工验证或外部推理，再决定是否继续训练。

### POST /api/v1/models/yolox/training-tasks/{task_id}/resume

把一个 `paused` 状态的训练任务重新入队。

#### 当前用途

- 当前接口会复用同一个 task_id，并基于暂停时保存的 latest checkpoint 恢复 optimizer、已完成 epoch 和最佳指标状态。
- 成功返回后任务状态会回到 `queued`，等待 worker 继续执行剩余 epoch。

### GET /api/v1/models/yolox/training-tasks/{task_id}/validation-metrics

直接通过 HTTP 返回当前训练任务最新的 validation-metrics.json 内容，而不是要求调用方去磁盘上读取文件。

#### 当前用途

- 训练完成后，前端或 Postman 可以直接轮询这个接口读取完整验证文件。
- 当 training task 已经进入评估轮时，这个接口会返回与 validation-metrics.json 一致的 JSON 内容。
- 当任务还没有产生任何验证快照时，这个接口会返回 `file_status=pending` 和空 `payload`；任务已经结束但文件缺失时仍返回 404。

#### 当前返回重点字段

- file_status：当前值为 `ready` 或 `pending`。
- task_state：当前训练任务状态，例如 `queued`、`running`、`succeeded`。
- object_key：验证指标文件 object key；输出目录尚未确定时可能为空。
- payload：验证指标文件正文；`pending` 时为空对象，`ready` 时内容与 validation-metrics.json 保持一致。

### GET /api/v1/models/yolox/training-tasks/{task_id}/train-metrics

直接通过 HTTP 返回当前训练任务最新的 train-metrics.json 内容，而不是要求调用方去磁盘上读取文件。

#### 当前用途

- 训练完成后，前端或 Postman 可以直接通过这个接口读取完整训练指标摘要和 epoch_history。
- running 或 paused 阶段只要已经完成过至少一轮训练，这个接口就会返回最近一次增量写出的 train-metrics.json。
- 训练尚未生成 train metrics 文件时，这个接口不会返回 404，而是返回 `file_status=pending` 和空 `payload`，便于前端走统一分支。

#### 当前返回重点字段

- file_status：当前值为 `ready` 或 `pending`。
- task_state：当前训练任务状态，例如 `queued`、`running`、`succeeded`。
- object_key：训练指标文件 object key；输出目录尚未确定时可能为空。
- payload：训练指标快照正文；`pending` 时为空对象，`ready` 时内容与 train-metrics.json 保持一致。

### GET /api/v1/models/yolox/training-tasks/{task_id}/output-files

统一列出当前训练任务所有公开的训练输出文件读取入口。

#### 当前用途

- 前端卡片、详情页和调试页面可以只轮询这一个资源组，统一判断每个文件的 `file_status`。
- 当前资源组固定返回 6 项：`train-metrics`、`validation-metrics`、`summary`、`labels`、`best-checkpoint`、`latest-checkpoint`。
- running 或 paused 阶段当前通常会看到 `train-metrics` 已经进入 `ready`；如果当前轮做过真实验证评估，`validation-metrics` 也会进入 `ready`。
- `latest-checkpoint` 仍然只会在手动保存、暂停或训练完成时进入 `ready`。

#### 当前返回重点字段

- file_name：训练输出文件名称。
- file_kind：当前值为 `json`、`text` 或 `checkpoint`。
- file_status：当前值为 `ready` 或 `pending`。
- task_state：当前训练任务状态。
- object_key：对应训练输出文件的 object key。
- size_bytes / updated_at：文件已经写出时返回的元数据。

### GET /api/v1/models/yolox/training-tasks/{task_id}/output-files/{file_name}

读取单个训练输出文件的状态与可读内容。

#### 当前用途

- `summary`、`train-metrics`、`validation-metrics` 会把 JSON 内容放在 `payload`。
- `labels` 会把文本内容放在 `text_content`，并额外返回 `lines`。
- `best-checkpoint` 和 `latest-checkpoint` 当前只返回文件状态与元数据，不直接返回二进制内容。

#### file_name 取值

- `train-metrics`
- `validation-metrics`
- `summary`
- `labels`
- `best-checkpoint`
- `latest-checkpoint`

#### 当前训练输出文件目录约定

- 所有当前训练输出文件都落在 task-runs/training/{task_id}/artifacts 下。
- 当前最小真实训练在训练完成时会写出：
  - checkpoints/best_ckpt.pth：按最佳指标选出的 checkpoint。
  - checkpoints/latest_ckpt.pth：训练完成时的最新 checkpoint。
  - reports/train-metrics.json：训练过程指标和 epoch_history。
  - reports/validation-metrics.json：真实验证评估摘要、evaluated_epochs 和验证 epoch_history。
  - training-summary.json：训练摘要、output_files、运行设备信息和验证摘要。
  - labels.txt：当前训练输出对应的类别文件。
- 如果运行中调用手动保存或暂停，服务会提前写出 checkpoints/latest_ckpt.pth；当时 best checkpoint 是否 ready 取决于当前是否已经产生 best 指标。

#### 当前 training_summary 重点内容

- implementation_mode：当前训练执行模式，当前值为 yolox-detection-minimal。
- requested_gpu_count / gpu_count：请求的 GPU 数量与实际生效的 GPU 数量。
- requested_precision / precision：请求的 precision 与实际生效的 precision。
- device / device_ids / distributed_mode：训练运行设备信息。
- evaluation_interval：当前真实验证评估周期。
- output_files：各训练输出文件的 object key。
- validation：验证是否启用、验证 split、样本数、评估周期、已评估 epoch 列表、最佳指标、最终 map50/map50_95 摘要和验证指标文件位置。
- warm_start：warm start 来源 ModelVersion、checkpoint 存储位置和实际加载摘要。

## 预训练模型磁盘目录约定

- 当前 backend-service 启动时会自动扫描 data/files/models/pretrained/yolox 下的 manifest.json。
- 推荐目录层次为 data/files/models/pretrained/yolox/{model_scale}/{entry_name}。
- manifest.json 中的 model_version_id 是 warm_start_model_version_id 的稳定来源。
- 预训练目录是平台级基础资产，不绑定具体 Project，也不应放数据集 labels 文件。
- checkpoint_path 采用相对 manifest.json 的路径写法，服务启动时会自动登记为 ModelFile 引用。
- 当前也可以通过 GET /api/v1/models/platform-base 与 GET /api/v1/models/platform-base/{model_id} 查询这些平台基础模型及其 available_versions。

## dataset_export_id 与 manifest_object_key 的作用划分

- dataset_export_id：平台资源层标识。
  - 用于前端选择某个导出结果。
  - 用于详情查询、列表查询、下载、权限校验和审计。
  - 用于训练创建时表达“用哪一个导出资源作为输入”。

- manifest_object_key：执行层文件边界。
  - 用于训练 worker 直接定位导出 manifest 文件。
  - 用于脚本、批处理、离线训练器等直接消费导出文件的场景。
  - 用于把平台资源层和文件消费层解耦。

- 两者关系：
  - dataset_export_id 是资源 id。
  - manifest_object_key 是该资源在文件存储里的核心入口文件。
  - 一条完成态 DatasetExport 应稳定映射到一个 manifest_object_key。

## 场景建议

- 前端或业务 API 侧：优先传 dataset_export_id。
- worker、训练执行器或文件级脚本：优先消费 manifest_object_key。
- 当外部系统已经只持有 manifest_object_key 时，可以直接用 manifest_object_key 创建训练任务；服务会反查回对应的 DatasetExport。

## 当前能力边界

- 当前已经公开训练任务创建、列表和详情。
- 当前训练 worker 会把任务从 queued 推进到 running 和 succeeded，并写出 best/latest checkpoint、训练指标、验证指标、summary 和 labels 文件。
- 当前 running 阶段已经会回写 output_object_prefix 和逐 epoch progress 事件，前端可以直接显示真实训练进度。
- 当前 warm_start_model_version_id 已经接通真实 checkpoint 加载；可使用已有训练产出的 ModelVersion，也可使用预训练目录 manifest 中声明的 model_version_id。
- 当前最小真实训练执行链只支持 coco-detection-v1 输入、单条 detection 训练链路；有验证 split 时默认每 5 轮执行一次真实评估，并以验证集 val_map50_95 作为 best metric，没有验证 split 时退回 train_total_loss。
- 当前 GPU 数量控制采用单机单进程模式；gpu_count 大于 1 时使用 DataParallel，不引入 exp 文件体系或分布式脚本。
- 当前 precision 字段已经纳入公开接口；当前公开值为 fp16、fp32，未指定时默认 fp32。
- 当前 input_size 未显式指定时，真实训练默认使用 [640, 640]。
- 当前没有可用 GPU 时会回退到 CPU 训练，用于最小硬件支持和开发环境验证。