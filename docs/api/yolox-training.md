# YOLOX Training 接口文档

## 文档目的

本文档用于说明当前已经公开的 YOLOX training 创建接口，以及 DatasetExport 在训练创建链路中的输入边界语义。

当前这一版只公开训练任务创建，不把完整训练执行 worker 和训练输出登记作为稳定外部接口承诺。

## 适用范围

- YOLOX training 任务创建接口
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
- tasks:write

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
| warm_start_model_version_id | string \| null | 否 | warm start 使用的 ModelVersion id。 |
| max_epochs | integer \| null | 否 | 最大训练轮数。 |
| batch_size | integer \| null | 否 | batch size。 |
| input_size | array[integer] \| null | 否 | 训练输入尺寸。 |
| extra_options | object | 否 | 附加训练选项。 |
| display_name | string | 否 | 可选的任务展示名称。 |

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

- 当前只公开训练任务创建。
- 当前训练创建只做输入边界解析、TaskRecord 创建和队列提交。
- 当前训练执行 worker 还没有作为完整公开能力落地，因此创建后任务会进入 queued，后续执行链路单独推进。