# YOLOX Training 接口文档

## 文档目的

本文档用于说明当前已经公开的 YOLOX training 创建、列表、详情、训练控制和训练输出读取接口，以及 DatasetExport 在训练创建链路中的输入边界语义。

当前这一版已经公开训练后全链路，并把训练输出文件目录、训练摘要、验证结果、评估结果、转换结果和部署推理接口作为正式查询面。

## 适用范围

- YOLOX training 任务创建接口
- YOLOX training 列表、详情与训练控制接口
- 训练指标、验证指标和统一输出文件读取接口
- dataset_export_id 与 manifest_object_key 的解析规则
- 训练后验证、评估、转换、部署与推理链路
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
- 已完成任务，或已经在 `save` / `pause` 的 epoch 边界成功落盘 latest checkpoint 的任务，会在顶层直接返回 model_version_id，前端可以据此跳转模型详情、人工验证或转换链路。
- 如果任务已经完成且同时存在 latest checkpoint 版本，顶层 `model_version_id` 表示自动登记的 best checkpoint 版本，`latest_checkpoint_model_version_id` 表示 latest checkpoint 的固定版本；validation-sessions 应优先使用后者。
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
- latest_checkpoint_model_version_id：latest checkpoint 自动或手动登记得到的固定 ModelVersion id
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
- 当 save 或 pause 在 epoch 边界真正生效时，服务会和 latest checkpoint 一起写出 labels.txt，这样自动生成的 latest checkpoint 版本可以直接进入 validation-sessions。
- 如果需要在训练尚未完成时直接拿 latest checkpoint 进入后续验证链路，可以按 `pause 或 save -> 等待 latest_checkpoint_model_version_id 可用 -> create validation session` 的顺序调用；用于 validation-sessions 的 id 优先取 `latest_checkpoint_model_version_id`。
- 每个 epoch 完成后都会追加一条 progress 事件，并同步更新 task.progress。
- 当前 progress 负载会带 stage、percent、epoch、max_epochs、evaluation_interval、validation_ran、evaluated_epochs、current_metric_name、current_metric_value、best_metric_name、best_metric_value、train_metrics、validation_metrics。
- 当 validation_ran=true 时，validation_metrics 当前会同时携带 total_loss、iou_loss、conf_loss、cls_loss、map50、map50_95；当本轮未执行评估时，validation_metrics 会为空对象。

### POST /api/v1/models/yolox/training-tasks/{task_id}/save

为 running 状态的训练任务追加一次手动保存请求。

#### 当前用途

- 训练继续执行，但会在下一个 epoch 边界把 latest checkpoint 写到磁盘。
- 同一个保存边界还会补齐 labels.txt，并自动更新 latest checkpoint 的固定 ModelVersion。
- 当前接口只负责登记 save 请求；真正的落盘发生在 worker 处理到下一轮完成时。

#### 当前返回语义

- 当前接口返回训练任务详情，而不是单独的动作回执对象。
- 调用成功后，任务通常仍处于 `running`，因为真正的保存动作要等到下一个 epoch 边界。
- 前端不应把 200 直接解释为“latest checkpoint 已经写盘完成”，而应继续观察：
  - detail 响应中的 `metadata.training_control.save_requested=true`
  - 后续 `yolox training checkpoint saved` 事件
  - `latest-checkpoint` 输出文件进入 `ready`

### POST /api/v1/models/yolox/training-tasks/{task_id}/pause

为 running 状态的训练任务请求暂停。

#### 当前用途

- 服务会在下一个 epoch 边界先保存 latest checkpoint，再把任务状态切到 `paused`。
- 同一个暂停边界也会补齐 labels.txt，并自动更新 latest checkpoint 的固定 ModelVersion。
- `paused` 后可以基于 latest checkpoint 做人工验证或外部推理，再决定是否继续训练。

#### 当前返回语义

- 当前接口返回训练任务详情，而不是单独的动作回执对象。
- 调用成功后，任务通常仍处于 `running`，因为 pause 也是在下一个 epoch 边界才真正生效。
- 前端不应把 200 直接解释为“任务已经暂停”，而应继续观察：
  - detail 响应中的 `metadata.training_control.pause_requested=true`
  - 后续 `yolox training checkpoint saved` 事件
  - 后续 `yolox training paused` 事件
  - detail 顶层 `state` 最终切到 `paused`

### POST /api/v1/models/yolox/training-tasks/{task_id}/resume

把一个 `paused` 状态的训练任务重新入队。

#### 当前用途

- 当前接口会复用同一个 task_id，并基于暂停时保存的 latest checkpoint 恢复 optimizer、已完成 epoch 和最佳指标状态。
- 成功返回后任务状态会回到 `queued`，等待 worker 继续执行剩余 epoch。

#### 当前返回语义

- 当前接口返回的是重新入队提交结果，不是训练任务详情。
- 调用成功后，前端应立即重新获取训练任务详情或列表，不能只依赖 resume 接口返回体更新页面。
- 当前 resume 的失败存在两层：
  - 接口层失败：例如任务不处于 `paused`、latest checkpoint 缺失、latest checkpoint 文件不存在。这类错误会直接返回 400。
  - worker 执行层失败：例如 latest checkpoint 损坏、resume checkpoint 内容与当前任务配置不一致。这类错误会先返回 200 并进入 `queued`，随后任务会在 worker 执行阶段进入 `failed`，并在 detail 的 `error_message` 中给出失败原因。

### POST /api/v1/models/yolox/training-tasks/{task_id}/register-model-version

把当前训练任务已经落盘的 latest checkpoint 手动重登记为可复用的 ModelVersion。

#### 当前用途

- 当前接口主要用于调试或验证，不再是 save/pause 后进入 validation-sessions 的必经步骤。
- 正常调用顺序是：先 `save` 或 `pause`，等待 latest checkpoint 写盘并自动生成 `latest_checkpoint_model_version_id`，然后直接创建 validation-sessions。
- 同一个训练任务只维护一个固定 latest checkpoint 版本：首次自动或手动登记创建，后续再次登记会更新已有版本，而不是新增多个版本。
- 当前自动完成态登记仍然使用训练最佳 checkpoint；latest checkpoint 则维护成另一条独立版本线。训练完成后，best checkpoint 仍通过顶层 `model_version_id` 表示，latest checkpoint 通过 `latest_checkpoint_model_version_id` 表示。

#### 当前返回语义

- 当前接口返回训练任务详情，而不是单独的动作回执对象。
- 调用成功后，未完成任务会把详情顶层 `model_version_id` 和 `training_summary.model_version_id` 回填成 latest checkpoint 的固定版本 id。
- 如果任务已经完成，顶层 `model_version_id` 会继续保持自动 best checkpoint 版本；latest checkpoint 的版本 id 通过 `latest_checkpoint_model_version_id` 和 `training_summary.latest_checkpoint_model_version_id` 暴露。
- 当前训练任务顶层 `checkpoint_object_key` 仍然保持“最佳 checkpoint”语义，不会被 latest checkpoint 覆盖；真正被登记到新 ModelVersion 的 checkpoint 来源是 `latest_checkpoint_object_key`。

## 前端交互定义

本节用于约束后续浏览器前端接入当前训练控制接口时的状态判断、轮询策略和按钮行为，避免把 save、pause、resume 误解成同步完成动作。

### 任务状态机

- `queued`：任务已创建或 resume 后已重新入队，尚未被 worker 执行。
- `running`：worker 已经开始训练。
- `paused`：任务已经在 epoch 边界完成一次保存并停止继续训练。
- `succeeded`：训练完成并已登记输出模型版本。
- `failed`：训练执行失败，失败原因写在 detail 的 `error_message`。

#### 当前控制动作对应的真实阶段

- `save`：只登记一次保存请求，真正写盘要等到下一个 epoch 边界。
- `pause`：先登记暂停请求，真正暂停也要等到下一个 epoch 边界，并且会先写 latest checkpoint。
- `resume`：把 paused 任务重新放回队列；真正恢复执行要等 worker 再次开始处理。

### 前端应读取的关键字段

- detail 顶层字段：
  - `available_actions`
  - `control_status.status`
  - `control_status.pending_action`
  - `control_status.requested_at`
  - `control_status.requested_by`
  - `control_status.last_save_at`
  - `control_status.last_save_epoch`
  - `control_status.last_save_reason`
  - `control_status.last_save_by`
  - `control_status.last_resume_at`
  - `control_status.last_resume_by`
  - `control_status.resume_count`
  - `control_status.resume_checkpoint_object_key`
  - `state`
  - `progress.stage`
  - `progress.percent`
  - `error_message`
  - `output_object_prefix`
  - `latest_checkpoint_object_key`
  - `metrics_object_key`
  - `validation_metrics_object_key`
- `metadata.training_control` 继续保留，当前更适合作为排障和事件对照字段，而不是前端主分支判断来源。

#### `available_actions` 当前取值

- `[]`：当前不建议展示训练控制按钮。
- `['save', 'pause']`：任务处于正常 `running`。
- `['pause']`：任务已经登记过一次 save，请求仍未在 epoch 边界生效，此时仍允许升级为 pause。
- `['resume']`：任务处于 `paused` 且已解析到可用的 resume checkpoint object key。

#### `control_status` 当前取值

- `status=idle`：当前没有待生效的控制请求。
- `status=save_requested`：已经登记 save，请等待下一个 epoch 边界。
- `status=pause_requested`：已经登记 pause，请等待下一个 epoch 边界。
- `status=resume_pending`：已经登记 resume，请等待 worker 重新开始执行。

### 按钮启用规则

| 场景 | Save | Pause | Resume | 说明 |
| --- | --- | --- | --- | --- |
| `queued` | 禁用 | 禁用 | 禁用 | 任务尚未进入训练执行。 |
| `running` 且无控制请求 | 启用 | 启用 | 禁用 | 正常训练中。 |
| `running` 且 `control_status.status=save_requested` | 禁用 | 启用 | 禁用 | 已经登记过一次保存请求，但仍允许升级为 pause。 |
| `running` 且 `control_status.status=pause_requested` | 禁用 | 禁用 | 禁用 | 已经登记过一次暂停请求，等待 epoch 边界处理。 |
| `paused` | 禁用 | 禁用 | 启用 | latest checkpoint 已经自动落盘并登记固定版本。 |
| `succeeded` | 禁用 | 禁用 | 禁用 | 训练已完成。 |
| `failed` | 禁用 | 禁用 | 禁用 | 当前没有失败后直接 resume 的正式接口语义。 |

### 页面轮询与事件订阅建议

#### 推荐最小接入方案

- 列表页：轮询 `GET /api/v1/models/yolox/training-tasks?project_id=...`
- 详情页：轮询 `GET /api/v1/models/yolox/training-tasks/{task_id}?include_events=false`
- 指标面板：
  - 只需要训练和验证 JSON 时，优先读 `train-metrics`、`validation-metrics`
  - 需要统一判断文件 readiness 时，优先读 `GET /output-files`

#### 推荐实时方案

- 详情页或日志面板可以额外建立 `GET /ws/tasks/events?task_id=...` 对应的 WebSocket 订阅。
- 当前推荐策略：
  - 详情基础状态仍然走 HTTP 轮询
  - 日志流和动作完成提示走 `/ws/tasks/events`
- 当前 WebSocket 支持的查询参数：
  - `task_id`：必填
  - `event_type`：可选
  - `after_created_at`：可选
  - `limit`：可选，默认 100，最大 500

#### 当前轮询注意点

- 详情接口的 `include_events` 默认值是 `true`。
- 前端如果把 detail 接口直接当成高频轮询接口，必须显式传 `include_events=false`，否则返回体会随着事件累积不断变大。
- 如果页面需要展示事件流，应优先使用 `/ws/tasks/events` 或通用任务事件接口，而不是在高频轮询里反复拉完整 `events` 数组。

### 前端交互建议流程

#### Save

1. 点击 Save。
2. 调用 `POST /save`。
3. 若返回 200，页面保持 `running`，按钮切到“保存已请求”。
4. 等待 `latest-checkpoint` 进入 `ready` 或出现 `yolox training checkpoint saved` 事件。

#### Pause

1. 点击 Pause。
2. 调用 `POST /pause`。
3. 若返回 200，页面保持 `running`，按钮切到“暂停中”。
4. 等待 `yolox training checkpoint saved`。
5. 等待 `state=paused` 或 `yolox training paused` 事件。

#### Resume

1. 在 `paused` 状态点击 Resume。
2. 调用 `POST /resume`。
3. 若返回 200，立即刷新 detail 或列表，页面应切回 `queued`。
4. 等待 `yolox training resumed` 事件后再切到 `running`。
5. 如果任务后续进入 `failed`，应直接显示 detail 中的 `error_message`。

## 当前前端接入缺口与后续优化建议

当前接口已经够前端实现训练控制，但仍有几项值得后续补齐的地方。

- 当前 detail 响应已经正式公开 `available_actions` 和 `control_status`，前端不必再直接依赖 `metadata.training_control` 做主分支判断。
- `metadata.training_control` 仍然保留；后续如果要进一步收口，可以只在 detail 中保留 `control_status`，把原始 metadata 控制字段降级为调试信息。
- `resume` 当前返回 submission，而不是 detail；这并不错误，但会让前端必须补一次 detail/list 刷新。后续如要减少页面跳变，可以考虑给 resume 返回更完整的 queued 态摘要。
- 当前还没有专门面向 latest checkpoint 的“人工验证”接口；暂停后的人工验证仍需外部系统直接消费输出文件或后续新增验证接口。
- 当前也没有“停止训练 / 终止任务”接口；如果后续产品需要硬停止语义，应单独定义停止后的 checkpoint 与状态流转规则。

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

## 训练后全链路：验证、评估、转换、部署与推理

当前训练链已经不只是“最小真实闭环”，而是已经打通训练后验证、评估、转换、DeploymentInstance 发布和同步 / 异步推理接口。训练详情和输出文件接口已经能稳定公开 `model_version_id`、`best/latest checkpoint`、`labels.txt`、`training-summary.json`、`train-metrics.json` 和 `validation-metrics.json`，后续链路不再依赖临时脚本或裸模型路径拼接。

### 当前已完成的基础衔接

- 训练详情已经公开 `model_version_id`，可以把训练输出正式衔接到后续模型发布、部署或验证链路。
- 训练输出资源组已经公开 `best-checkpoint`、`latest-checkpoint`、`summary`、`labels`、`train-metrics` 和 `validation-metrics` 的统一读取状态。
- backend 已经存在推理任务规格、runtime predict contract 和 inference runner contract；当前已经公开最小可用的 validation-sessions REST API，用于训练完成后，或 save/pause 自动登记 latest checkpoint 后的单图人工验证。
- 当前在线推理设计更偏向 `deployment_instance_id + input_file_id/input_uri` 模式，而不是让推理接口直接读取 DatasetVersion。

### 当前接口边界保持拆分

- 单图或少量样本的人工验证继续独立于面向正式 deployment 的在线推理任务。
- 数据集级别的回归验证、benchmark 或评估继续独立为评估任务，并显式绑定 `DatasetVersion`、`DatasetExport` 或专门的评估输入包。
- 正式在线推理继续保持和 `DeploymentInstance` 绑定，不直接暴露裸 checkpoint 路径。

### 当前人工验证接口

这一步的目标不是上线正式部署，而是让训练完成后的模型能被快速抽样验证，优先解决“这版模型看起来对不对”。当前已经公开以下资源组：

- 资源组：`/api/v1/models/yolox/validation-sessions`
- 创建接口：`POST /api/v1/models/yolox/validation-sessions`
- 详情接口：`GET /api/v1/models/yolox/validation-sessions/{session_id}`
- 预测接口：`POST /api/v1/models/yolox/validation-sessions/{session_id}/predict`

#### 当前最短联调顺序

- 训练尚未完成时：先 `pause` 或 `save`
- 轮询训练详情，确认 `latest_checkpoint_object_key` 和 `latest_checkpoint_model_version_id` 已可用
- 读取详情里的 `latest_checkpoint_model_version_id`；如果当前任务尚未完成，这个值会与顶层 `model_version_id` 相同
- 调用 `POST /api/v1/models/yolox/validation-sessions` 创建人工验证 session

#### 当前创建请求字段

- `project_id`
- `model_version_id`
- `runtime_profile_id`
- `runtime_backend`
- `device_name`
- `score_threshold`
- `save_result_image`
- `extra_options`

#### 当前详情响应重点

- `session_id`
- `status`
- `model_version_id`
- `model_name`
- `model_scale`
- `input_size`
- `labels`
- `checkpoint_storage_uri`
- `last_prediction`

#### 当前预测请求字段

- `input_uri`
- `input_file_id`
- `score_threshold`
- `save_result_image`
- `extra_options`

#### 当前预测响应重点

- `detections`
- `preview_image_uri`
- `raw_result_uri`
- `latency_ms`
- `runtime_session_info`
- `labels`

#### 当前实现边界

- 当前 runtime_backend 只支持 `pytorch`
- 当前只支持本地 `input_uri` 或本地 object key，不支持远程 URL
- `input_file_id` 当前只是保留字段，调用时会返回 `invalid_request`
- `runtime_profile_id` 当前仅作为创建参数和详情回传字段，不参与实际模型加载
- session 状态和预测结果默认写到 `runtime/validation-sessions/{session_id}/...` 下，便于先把人工验证闭环跑通

这组接口更接近现有 runtime predict contract，适合先把人工验证闭环跑通，也避免为了验证刚训练出来的模型，先被 `DeploymentInstance` 的正式发布流程卡住。

### 当前离线批量评估接口

这一步的目标是解决“这版模型相对上一版到底提升还是退化了”，它和在线推理解耦，当前已经公开以下资源组：

- 资源组：`/api/v1/models/yolox/evaluation-tasks`
- 创建接口：`POST /api/v1/models/yolox/evaluation-tasks`
- 列表接口：`GET /api/v1/models/yolox/evaluation-tasks`
- 详情接口：`GET /api/v1/models/yolox/evaluation-tasks/{task_id}`
- 报告接口：`GET /api/v1/models/yolox/evaluation-tasks/{task_id}/report`
- 输出文件接口：`GET /api/v1/models/yolox/evaluation-tasks/{task_id}/output-files`

#### 当前创建请求字段

- `project_id`
- `model_version_id`
- `dataset_export_id`
- `dataset_export_manifest_key`
- `score_threshold`
- `nms_threshold`
- `save_result_package`
- `extra_options`

#### 当前列表 / 详情响应重点

- `map50`
- `map50_95`
- `per_class_metrics`
- `report_object_key`
- `detections_object_key`
- `result_package_object_key`

#### 当前 report 响应重点

- `file_status`
- `task_state`
- `object_key`
- `payload.map50`
- `payload.map50_95`
- `payload.per_class_metrics`

#### 当前 output-files 资源组

- `report`
- `detections`
- `result-package`

#### 当前实现边界

- 当前最小评估链只支持 `coco-detection-v1` 导出输入
- 当前评估执行复用本地 PyTorch checkpoint 和 YOLOX 最小 COCO mAP 评估逻辑
- 当前 `per_class_metrics` 提供 `category_id`、`class_index`、`class_name`、`ground_truth_count`、`detection_count`、`ap50` 和 `ap50_95`
- 当前 `result-package` 为 zip 文件，包含 `report.json` 和 `detections.json`
- 当前 `save_result_package=false` 时仍会生成 report 和 detections，但不会写 zip 结果包
- 当前设备、precision、split_name 等高级运行选项仍通过 `extra_options` 传入，尚未提升为正式顶层字段

这一层应该显式绑定 `DatasetVersion` 或导出的评估输入，而不是复用在线 inference task 去跑整套回归测试。

### 当前 conversion task 接口

当前已经公开 conversion-tasks 资源，转换链路固定为 `ModelVersion -> ConversionTask -> ModelBuild`，当前先以 ONNX 主链打通最小可执行闭环，不把转换逻辑混进 training 或 deployment。

#### 当前 conversion 资源组

- 资源组：`/api/v1/models/yolox/conversion-tasks`
- 创建 ONNX 接口：`POST /api/v1/models/yolox/conversion-tasks/onnx`
- 创建 optimized ONNX 接口：`POST /api/v1/models/yolox/conversion-tasks/onnx-optimized`
- 创建 OpenVINO IR FP32 接口：`POST /api/v1/models/yolox/conversion-tasks/openvino-ir-fp32`
- 创建 OpenVINO IR FP16 接口：`POST /api/v1/models/yolox/conversion-tasks/openvino-ir-fp16`
- 创建 TensorRT Engine FP32 接口：`POST /api/v1/models/yolox/conversion-tasks/tensorrt-engine-fp32`
- 创建 TensorRT Engine FP16 接口：`POST /api/v1/models/yolox/conversion-tasks/tensorrt-engine-fp16`
- 列表接口：`GET /api/v1/models/yolox/conversion-tasks`
- 详情接口：`GET /api/v1/models/yolox/conversion-tasks/{task_id}`
- 结果接口：`GET /api/v1/models/yolox/conversion-tasks/{task_id}/result`

#### 当前 conversion 创建请求字段

- 每个创建接口都固定一种目标格式，不再通过单个接口混合 `target_formats`
- `project_id`
- `source_model_version_id`
- `runtime_profile_id`
- `extra_options`
- `display_name`

#### 当前 conversion 列表 / 详情响应重点

- `source_model_version_id`
- `target_formats`
- `requested_target_formats`
- `produced_formats`
- `plan_object_key`
- `report_object_key`
- `builds`
- `report_summary`

#### 当前 conversion result 响应重点

- `file_status`
- `task_state`
- `object_key`
- `payload.phase`
- `payload.planned_target_formats`
- `payload.conversion_options`
- `payload.executed_step_kinds`
- `payload.validation_summary`
- `payload.outputs`
- `payload.builds`

#### 当前实现边界

- 当前 ONNX 主链继续使用旧版 `torch.onnx.export`
- 当前已真实可执行步骤是 `export-onnx -> validate-onnx -> optimize-onnx`，以及面向 `openvino-ir` 的追加步骤 `build-openvino-ir` 与面向 `tensorrt-engine` 的追加步骤 `build-tensorrt-engine`
- 当前已真实可执行目标支持 `onnx`、`onnx-optimized`、`openvino-ir` 与 `tensorrt-engine`
- 当前 `openvino-ir` 创建接口已拆成 `fp32` 与 `fp16` 两种构建策略；两者都会把 optimized ONNX 交给隔离子进程执行 OpenVINO `convert_model/save_model`，避免当前 Windows/conda 环境里的 torch/OpenVINO 同进程冲突
- 当前 `openvino-ir` 构建元数据会回写 `build_precision` 与 `compress_to_fp16`，结果报告会额外公开 `conversion_options.openvino_ir_precision`
- 当前 `tensorrt-engine` 创建接口已拆成 `fp32` 与 `fp16` 两种构建策略；两者都会先消费 optimized ONNX，再通过 TensorRT Python API 生成 engine，并把 `build_precision` 与 `tensorrt_version` 回写到 `ModelBuild.metadata`
- 当前 ONNX 校验包含两层：`onnx.checker` 合法性校验，以及 PyTorch 与 ONNXRuntime 的最小数值对齐校验
- 当前 ONNX 优化使用 `onnxsim`，并把 optimized 产物登记为独立 `ModelBuild`
- 当前转换 runner 默认使用 CPU 和本地文件存储，适合先把离线 build 链闭环跑通

### 当前 DeploymentInstance 与正式 inference task 接口

当前已经公开 DeploymentInstance 资源和正式 inference-tasks 资源，推理请求继续绑定 `DeploymentInstance`，不直接读取 `DatasetVersion`，也不直接暴露 checkpoint 路径。

#### 当前 deployment 资源组

- 资源组：`/api/v1/models/yolox/deployment-instances`
- 创建接口：`POST /api/v1/models/yolox/deployment-instances`
- 列表接口：`GET /api/v1/models/yolox/deployment-instances`
- 详情接口：`GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}`

#### 当前 deployment 创建请求字段

- `project_id`
- `model_version_id`
- `model_build_id`
- `runtime_profile_id`
- `runtime_backend`
- `runtime_precision`
- `device_name`
- `instance_count`
- `display_name`
- `metadata`

#### 当前 deployment metadata 覆盖字段

- `metadata.deployment_process.warmup_dummy_inference_count`：覆盖默认 warmup 的 dummy infer 次数
- `metadata.deployment_process.warmup_dummy_image_size`：覆盖 dummy infer 使用的最小输入图片尺寸，格式为 `[width, height]`
- `metadata.deployment_process.keep_warm_enabled`：启用 deployment 子进程内的 keep-warm 后台线程
- `metadata.deployment_process.keep_warm_interval_seconds`：覆盖 keep-warm 连续 dummy infer 的最小间隔秒数
- `metadata.deployment_process.tensorrt_pinned_output_buffer_enabled`：覆盖 TensorRT 输出 host buffer 是否启用 pinned memory
- `metadata.deployment_process.tensorrt_pinned_output_buffer_max_bytes`：覆盖 TensorRT 输出 host buffer 允许使用 pinned memory 的最大字节数

#### 当前 keep-warm 观测字段

- `pinned_output_total_bytes`：当前所有已加载 session 的 pinned output host buffer 总字节数
- `keep_warm.enabled`：当前 deployment 是否启用 keep-warm
- `keep_warm.activated`：keep-warm 是否已经被 warmup 或真实推理激活
- `keep_warm.paused`：keep-warm 当前是否因为控制面动作或真实请求而暂停
- `keep_warm.idle`：当前是否没有 keep-warm dummy infer 正在执行
- `keep_warm.interval_seconds`：当前生效的 keep-warm 间隔秒数
- `keep_warm.yield_timeout_seconds`：真实请求等待 keep-warm 让出的最长秒数
- `keep_warm.success_count`：keep-warm 成功完成的 dummy infer 当前安全整数窗口值
- `keep_warm.success_count_rollover_count`：`success_count` 已发生的 rollover 次数；当 `success_count` 达到 JavaScript 安全整数上限后，下一次成功会把 `success_count` 置为 1，并把这个字段加 1
- `keep_warm.error_count`：keep-warm 失败次数当前安全整数窗口值
- `keep_warm.error_count_rollover_count`：`error_count` 已发生的 rollover 次数；当 `error_count` 达到 JavaScript 安全整数上限后，下一次失败会把 `error_count` 置为 1，并把这个字段加 1
- `keep_warm.last_error`：最近一次 keep-warm 失败错误
- `restart_count`：deployment 子进程自动拉起次数当前安全整数窗口值
- `restart_count_rollover_count`：`restart_count` 已发生的 rollover 次数；当 `restart_count` 达到 JavaScript 安全整数上限后，下一次自动拉起会把 `restart_count` 置为 1，并把这个字段加 1

#### 当前 deployment 发布模板

- PyTorch ModelVersion 发布模板：`model_version_id + runtime_backend=pytorch + device_name=cpu|cuda`
- ONNX ModelBuild 发布模板：`model_build_id={{onnxModelBuildId}}|{{onnxOptimizedModelBuildId}} + runtime_backend=onnxruntime + device_name=cpu`
- OpenVINO ModelBuild 发布模板：`model_build_id={{openvinoIrModelBuildId}} + runtime_backend=openvino + device_name=cpu|auto|gpu|npu + runtime_precision=fp32|fp16`
- TensorRT ModelBuild 发布模板：`model_build_id={{tensorrtEngineModelBuildId}} + runtime_backend=tensorrt + device_name=cuda|cuda:0 + runtime_precision=fp32|fp16`

#### 当前 deployment 运行方式矩阵

- `ModelVersion` 默认走 `pytorch`
- `ModelBuild` 当前已经支持绑定 `onnx`、`onnx-optimized`、`openvino-ir`、`tensorrt-engine`，并自动解析到 `onnxruntime`、`openvino` 或 `tensorrt`
- 当前已真实接通：`pytorch fp32/fp16 cpu/cuda`、`onnxruntime fp32 cpu`、`openvino fp32 auto/cpu/gpu/npu + fp16 gpu/npu`、`tensorrt fp32/fp16 cuda`
- 当前 openvino fp16 只对显式 `device_name=gpu|npu` 开放；`device_name=auto|cpu` 仍要求 `runtime_precision=fp32`
- 当前 TensorRT deployment 会从 engine `build_precision` 推导默认 `runtime_precision`，并要求 `runtime_precision` 与 engine `build_precision` 严格一致；`device_name` 会统一归一化到 `cuda:0`

#### 当前 deployment 响应重点

- `deployment_instance_id`
- `model_version_id`
- `model_build_id`
- `runtime_backend`
- `device_name`
- `runtime_precision`
- `runtime_execution_mode`
- `instance_count`
- `input_size`
- `labels`
- `status`

#### 当前 deployment 进程监督单元语义

- 每个 DeploymentInstance 在 sync 和 async 两个通道上各自对应一个独立的 deployment 进程监督单元
- 每个监督单元管理一个独立子进程；子进程内部再按 `instance_count` 管理多个独立推理线程和模型会话
- 每个 instance 对应一个独立推理线程和模型会话；同一 instance 一次只处理一个请求
- 同步 `/infer` 和异步 `inference-tasks` 已经拆成两个独立 deployment 子进程，不再共用实例会话
- 当前已经公开 sync/async 两组 `start`、`status`、`stop`、`warmup`、`health` 和 `reset` 接口，用于显式启动、停止、预热、查看状态和清空实例池
- `warmup` 会在预热前自动拉起目标子进程，并在模型会话加载后按默认配置或 `metadata.deployment_process` 覆盖值执行 N 次真实 dummy infer
- 当 `metadata.deployment_process.keep_warm_enabled=true` 时，warmup 完成后会激活 keep-warm 后台线程；首次真实推理成功后也会激活同一机制
- `reset` 只对已经启动的子进程生效；reset 后 keep-warm 会回到未激活状态，直到下一次 warmup 或下一次真实推理成功

#### 当前 inference 资源组

- 资源组：`/api/v1/models/yolox/inference-tasks`
- 创建接口：`POST /api/v1/models/yolox/inference-tasks`
- 列表接口：`GET /api/v1/models/yolox/inference-tasks`
- 详情接口：`GET /api/v1/models/yolox/inference-tasks/{task_id}`
- 结果接口：`GET /api/v1/models/yolox/inference-tasks/{task_id}/result`
- 同步直返接口：`POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/infer`
- 同步启动接口：`POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/start`
- 同步状态接口：`GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/status`
- 同步停止接口：`POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/stop`
- 同步预热接口：`POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/warmup`
- 同步健康接口：`GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/health`
- 同步健康响应会额外返回 `pinned_output_total_bytes`、`restart_count_rollover_count` 和 `keep_warm.*`，用于确认当前已加载 session 的 pinned output 总量、长期累计计数是否发生 rollover，以及 keep-warm 是否启用、是否已激活、是否在后台静默失败
- 同步重置接口：`POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/reset`
- 同步重置响应与同步健康接口使用同一组详细 health 字段；可直接观察 `restart_count_rollover_count`、`pinned_output_total_bytes` 和 `keep_warm.*`，并确认 reset 后 `keep_warm.activated=false`
- 异步启动接口：`POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/start`
- 异步状态接口：`GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/status`
- 异步停止接口：`POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/stop`
- 异步预热接口：`POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/warmup`
- 异步健康接口：`GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/health`
- 异步健康响应会额外返回 `pinned_output_total_bytes`、`restart_count_rollover_count` 和 `keep_warm.*`，语义与同步健康接口一致
- 异步重置接口：`POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/reset`
- 异步重置响应与异步健康接口使用同一组详细 health 字段；可直接观察 `restart_count_rollover_count`、`pinned_output_total_bytes` 和 `keep_warm.*`，并确认 reset 后 `keep_warm.activated=false`

#### 当前 inference 创建请求字段

- `project_id`
- `deployment_instance_id`
- `input_file_id`
- `input_uri`
- `image_base64`
- `input_image`（仅 `multipart/form-data` 文件字段）
- `input_transport_mode`（仅同步 `/infer` 使用；支持 `storage`、`memory`）
- `score_threshold`
- `save_result_image`
- `return_preview_image_base64`
- `extra_options`

#### 当前 inference 输入规则

- 当前正式推理支持 `application/json` 和 `multipart/form-data`
- `input_uri`、`image_base64`、`input_image` 三者必须且只能提供一个
- `image_base64` 同时支持纯 base64 内容和 `data:image/...;base64,...` 形式
- `application/json` 场景下，`image_base64` 必须是单行 JSON 字符串；如果把带原始换行的 base64 直接贴进 JSON，请求会在 JSON 解析阶段返回 `请求体不是合法的 JSON`
- `input_file_id` 当前仍是保留字段，会返回 `invalid_request`
- multipart 场景下，`extra_options` 以 JSON 字符串传入
- 服务会在写入临时输入前校验 `image_base64` 与 `input_image` 是否为可读取图片；损坏图片会直接返回 `invalid_request`，不会继续下发到 deployment 推理进程
- 同步 `/infer` 额外支持 `input_transport_mode`：
  - `storage`：保持当前默认行为，Base64 或上传文件会先写入临时输入文件，再按 `input_uri` 进入 deployment 推理进程
  - `memory`：只允许 `image_base64` 或 `input_image`，请求图片不会落到临时目录，会直接以原始字节送入 deployment 推理进程
- 当同步 `/infer` 使用 `input_transport_mode=memory` 时：
  - 响应里的 `input_uri` 会返回 `memory://...` 形式的虚拟 URI，用于标识这次调用没有输入落盘
  - 响应里的 `result_object_key` 为 `null`，因为不会写 `raw-result.json`
  - 如果同时设置 `save_result_image=true`，预览图仍会按现有语义写盘；如果只需要直接返回图像，应使用 `return_preview_image_base64=true`
- 同步 `/infer` 真正执行前，需要先通过 `sync/start` 或 `sync/warmup` 拉起对应 deployment 的 sync 子进程
- 异步 `inference-tasks` 创建前，需要先通过 `async/start` 或 `async/warmup` 拉起对应 deployment 的 async 子进程；未启动时 create 接口会直接返回 `invalid_request`

#### 当前 inference 列表 / 详情响应重点

- `deployment_instance_id`
- `instance_id`
- `model_version_id`
- `model_build_id`
- `input_uri`
- `input_source_kind`
- `score_threshold`
- `save_result_image`
- `result_object_key`
- `preview_image_object_key`
- `detection_count`
- `latency_ms`
- `decode_ms`
- `preprocess_ms`
- `infer_ms`
- `postprocess_ms`
- `serialize_ms`
- `result_summary`

#### 当前 inference result 响应重点

- `file_status`
- `task_state`
- `object_key`
- `payload.request_id`
- `payload.instance_id`
- `payload.input_source_kind`
- `payload.detections`
- `payload.latency_ms`
- `payload.decode_ms`
- `payload.preprocess_ms`
- `payload.infer_ms`
- `payload.postprocess_ms`
- `payload.serialize_ms`
- `payload.runtime_session_info`
- `payload.preview_image_uri`
- `payload.preview_image_base64`

#### 当前实现边界

- 当前 deployment create 允许绑定 `ModelVersion` 或 `ModelBuild`；其中 `pytorch`、`onnxruntime`、`openvino`、`tensorrt` 已接通真实 runtime
- 当前 inference 执行通过 DeploymentInstance 解析运行时快照，并在 deployment 子进程内部复用常驻会话
- 当前同步 `/infer` 与异步 `inference-tasks` 使用同一套结果载荷字段
- 当前同步 `/infer` 已支持 `input_transport_mode=memory`，用于 Base64 与 multipart 上传图片的高速内存直通；异步 `inference-tasks` 仍保持 storage 模式
- 当前 inference 响应已经拆出 `decode_ms`、`preprocess_ms`、`infer_ms`、`postprocess_ms`、`serialize_ms`；其中 `latency_ms` 表示前四段总耗时，不包含 `serialize_ms`
- 当前 `preview_image_base64` 仅在 `return_preview_image_base64=true` 时生成
- 当前 `preview_image_object_key` 仅在 `save_result_image=true` 时生成
- 当前 sync 和 async 已经提升为独立 deployment 进程监督单元；如果启动多个 backend-service 或 worker 进程，每个父进程仍只负责自己装配出来的监督器与子进程
- 当前 formal inference 已经对外隐藏 checkpoint 路径，并已接通 `onnxruntime` 对 `onnx-optimized` ModelBuild、`openvino` 对 `openvino-ir` ModelBuild、`tensorrt` 对 `tensorrt-engine` ModelBuild 的真实消费

### 当前下一步建议

1. 基于现有 `validation-sessions`、`evaluation-tasks` 和 deployment health 接口补齐前端 / 工作站的验证、评估和运维视图。
2. 为当前已支持的 pytorch、onnxruntime、openvino、tensorrt 组合补齐 smoke test、精度回归和 benchmark 基线。
3. 把独立 worker profile、release 组装流程和 bundled Python 目录一起打磨到交付级，避免训练/评估/推理链路虽然可用但发布方式仍依赖人工拼装。
4. 在现有闭环稳定后，再继续扩展 RKNN 等新增目标格式或非 YOLOX 模型类型。

## 当前能力边界

- 当前已经公开训练任务创建、列表和详情。
- 当前训练 worker 会把任务从 queued 推进到 running 和 succeeded，并写出 best/latest checkpoint、训练指标、验证指标、summary 和 labels 文件。
- 当前 running 阶段已经会回写 output_object_prefix 和逐 epoch progress 事件，前端可以直接显示真实训练进度。
- 当前 warm_start_model_version_id 已经接通真实 checkpoint 加载；可使用已有训练产出的 ModelVersion，也可使用预训练目录 manifest 中声明的 model_version_id。
- 当前已经公开最小 validation-sessions create/detail/predict 接口，可直接用训练产出的 ModelVersion 做单图人工验证。
- 当前已经公开按目标格式拆分的 conversion-tasks create/list/detail/result 接口，可直接把训练产出的 source ModelVersion 转成 ONNX、optimized ONNX、OpenVINO IR 或 TensorRT engine，并登记为独立 ModelBuild。
- 当前已经公开最小 evaluation-tasks create/list/detail/report/output-files 接口，可直接用训练产出的 ModelVersion 对 DatasetExport 做数据集级回归验证。
- 当前已经公开最小 deployment-instances create/list/detail 与 inference-tasks create/list/detail/result 接口，可通过 deployment_instance_id 承接正式推理请求，并真实消费 `tensorrt-engine` ModelBuild。
- 当前最小真实训练执行链只支持 coco-detection-v1 输入、单条 detection 训练链路；验证 split 选择顺序是 val、valid、validation，缺失时回退 test，再缺失时才退回无验证模式。只要存在非训练验证 split，就默认每 5 轮执行一次真实评估，并以验证集 val_map50_95 作为 best metric；没有任何可用验证 split 时退回 train_total_loss。
- 当前 GPU 数量控制采用单机单进程模式；gpu_count 大于 1 时使用 DataParallel，不引入 exp 文件体系或分布式脚本。
- 当前 precision 字段已经纳入公开接口；当前公开值为 fp16、fp32，未指定时默认 fp32。
- 当前 input_size 未显式指定时，真实训练默认使用 [640, 640]。
- 当前没有可用 GPU 时会回退到 CPU 训练，用于最小硬件支持和开发环境验证。