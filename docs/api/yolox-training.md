# YOLOX Training 接口文档

## 文档目的

本文档用于说明当前已经公开的 YOLOX training 创建、列表和详情接口，以及 DatasetExport 在训练创建链路中的输入边界语义。

当前这一版已经公开最小真实训练执行链，并把训练产物目录、训练摘要和验证结果文件作为当前阶段的正式查询面。

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
| max_epochs | integer \| null | 否 | 最大训练轮数。 |
| batch_size | integer \| null | 否 | batch size。 |
| gpu_count | integer \| null | 否 | 请求参与训练的 GPU 数量；当前公开值为 1、2、3。 |
| precision | string \| null | 否 | 请求使用的训练 precision；当前接口字段接受 fp8、fp16、fp32，其中最小真实训练执行器当前实际支持 fp16、fp32。 |
| input_size | array[integer] \| null | 否 | 训练输入尺寸。 |
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
- 列表响应当前还会直接公开 gpu_count、precision、output_object_prefix、checkpoint_object_key、latest_checkpoint_object_key、metrics_object_key、validation_metrics_object_key、summary_object_key，便于训练卡片直接显示配置和产物入口。
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
- checkpoint_object_key：当前训练产物 checkpoint
- latest_checkpoint_object_key：当前训练结束时的最新 checkpoint
- metrics_object_key：当前训练指标文件
- validation_metrics_object_key：当前训练验证指标文件
- summary_object_key：当前训练摘要文件
- training_summary：当前训练摘要
- events：任务事件流

#### 当前运行期进度回写

- 任务进入 running 后，顶层 output_object_prefix 会立即可见，前端可以直接定位当前训练目录。
- 每个 epoch 完成后都会追加一条 progress 事件，并同步更新 task.progress。
- 当前 progress 负载会带 stage、percent、epoch、max_epochs、current_metric_name、current_metric_value、best_metric_name、best_metric_value、train_metrics、validation_metrics。

#### 当前训练产物目录约定

- 所有当前训练产物都落在 task-runs/training/{task_id}/artifacts 下。
- 当前最小真实训练会写出：
  - checkpoints/best_ckpt.pth：按最佳指标选出的 checkpoint。
  - checkpoints/latest_ckpt.pth：训练完成时的最新 checkpoint。
  - reports/train-metrics.json：训练过程指标和 epoch_history。
  - reports/validation-metrics.json：验证结果摘要和验证 epoch_history。
  - training-summary.json：训练摘要、artifact 路径、运行设备信息和验证摘要。
  - labels.txt：当前训练输出对应的类别文件。

#### 当前 training_summary 重点内容

- implementation_mode：当前训练执行模式，当前值为 yolox-detection-minimal。
- requested_gpu_count / gpu_count：请求的 GPU 数量与实际生效的 GPU 数量。
- requested_precision / precision：请求的 precision 与实际生效的 precision。
- device / device_ids / distributed_mode：训练运行设备信息。
- artifact_locations：各训练产物的 object key。
- validation：验证是否启用、验证 split、样本数、最佳指标和验证指标文件位置。
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
- 当前最小真实训练执行链只支持 coco-detection-v1 输入、单条 detection 训练链路；best metric 默认优先取验证集 val_total_loss，没有验证 split 时退回 train_total_loss。
- 当前 GPU 数量控制采用单机单进程模式；gpu_count 大于 1 时使用 DataParallel，不引入 exp 文件体系或分布式脚本。
- 当前 precision 字段已经纳入公开接口；最小真实训练执行器当前实际支持 fp16、fp32，fp8 暂未进入执行实现。