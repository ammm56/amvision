# DatasetExport 接口文档

## 文档目的

本文档用于说明当前已经公开的 DatasetExport REST 接口，包括导出创建、导出详情查询和按 DatasetVersion 列表查询三组能力。

当前导出提交已经正式关联 TaskRecord。提交响应、详情响应和列表响应都会公开 task_id，后续可以配合 tasks API 或 /ws/tasks/events 观察后台处理状态。

本文档聚焦对外接口规则、字段定义、错误语义和当前实现边界，不展开内部 repository 或持久化实现细节。

## 适用范围

- DatasetExport 创建接口
- DatasetExport 详情查询接口
- DatasetVersion 下的导出记录列表接口
- 请求头鉴权规则
- 当前已实现导出格式与 training 输入边界

## 接口入口

- FastAPI Swagger UI：/docs
- FastAPI OpenAPI JSON：/openapi.json
- 版本前缀：/api/v1
- 资源分组：/datasets

## 鉴权规则

当前接口通过请求头传入主体信息与 scope。

### 最小请求头

- x-amvision-principal-id：调用主体 id
- x-amvision-project-ids：当前主体可访问的 Project id 列表，多个值用逗号分隔；为空时表示不按 Project 做可见性裁剪
- x-amvision-scopes：当前主体持有的 scope 列表，多个值用逗号分隔

### scope 要求

- 创建接口需要 datasets:write
- 查询接口需要 datasets:read

## 当前实现边界

- 当前只支持 detection 类型 DatasetVersion
- 当前已经正式实现并对外开放的 format_id：
  - coco-detection-v1
  - voc-detection-v1
- 当前还没有单独的下载 API；这一版先稳定 export file 资源、manifest_object_key 和 training 输入边界
- training 前置步骤应消费 manifest_object_key，而不是直接读取 DatasetVersion 内部目录结构

## 接口清单

### POST /api/v1/datasets/exports

为指定 DatasetVersion 创建一条 DatasetExport 资源，并把导出任务提交到本地持久化队列。

#### Content-Type

- application/json

#### 请求体字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | string | 是 | 所属 Project id。接口会用它做权限可见性校验。 |
| dataset_id | string | 是 | 所属 Dataset id。接口会校验该 DatasetVersion 是否属于这个 Dataset。 |
| dataset_version_id | string | 是 | 导出来源的 DatasetVersion id。 |
| format_id | string | 是 | 目标导出格式 id。当前允许值为 coco-detection-v1、voc-detection-v1。 |
| display_name | string | 否 | 可选的 TaskRecord 展示名称。 |
| output_object_prefix | string | 否 | 可选的导出目录前缀。为空时默认落到 projects/{project_id}/datasets/{dataset_id}/exports/{dataset_export_id}。 |
| category_names | array[string] | 否 | 可选的导出类别名列表。为空时使用 DatasetVersion 中的类别定义。 |
| include_test_split | boolean | 否 | 是否包含 test split。默认 true。 |

#### curl 示例

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/datasets/exports" \
  -H "Content-Type: application/json" \
  -H "x-amvision-principal-id: user-1" \
  -H "x-amvision-project-ids: project-1" \
  -H "x-amvision-scopes: datasets:write" \
  -d '{
    "project_id": "project-1",
    "dataset_id": "dataset-1",
    "dataset_version_id": "dataset-version-1",
    "format_id": "voc-detection-v1",
    "include_test_split": false
  }'
```

#### 成功响应

- 状态码：202 Accepted

```json
{
  "dataset_export_id": "dataset-export-9f027b0e6317",
  "task_id": "task-41465ef2df80",
  "status": "queued",
  "dataset_version_id": "dataset-version-1",
  "format_id": "voc-detection-v1",
  "queue_name": "dataset-exports",
  "queue_task_id": "queue-task-6dc2b8d83588"
}
```

#### 成功响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| dataset_export_id | string | 新创建的导出记录 id。后续详情查询和轮询都使用这个值。 |
| task_id | string | 关联的正式 TaskRecord id。 |
| status | string | 导出记录当前状态。提交成功后立即返回 queued。 |
| dataset_version_id | string | 导出来源的 DatasetVersion id。 |
| format_id | string | 实际请求的导出格式 id。 |
| queue_name | string | 提交到的队列名称。当前固定为 dataset-exports。 |
| queue_task_id | string | 当前导出对应的队列任务 id。 |

#### 失败响应

- 400：请求字段不完整、project_id 或 dataset_id 与 DatasetVersion 不一致
- 401：缺少主体信息
- 403：主体没有 datasets:write scope，或 project_id 不在可访问范围内
- 404：dataset_version_id 不存在
- 422：当前导出格式不支持，或当前 DatasetVersion 任务类型不支持
- 503：持久化或数据库操作失败

### GET /api/v1/datasets/exports/{dataset_export_id}

按 DatasetExport id 查询导出记录详情，返回导出状态、产物路径和导出摘要。

#### 路径参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| dataset_export_id | string | 是 | 要查询的 DatasetExport id。 |

#### 成功响应要点

- 状态码：200 OK
- 当前公开字段包括：
  - dataset_export_id
  - task_id
  - dataset_id
  - project_id
  - dataset_version_id
  - format_id
  - task_type
  - status
  - created_at
  - include_test_split
  - export_path
  - manifest_object_key
  - split_names
  - sample_count
  - category_names
  - queue_task_id
  - error_message
  - metadata

#### 状态语义

- queued：导出资源已创建，任务已入队
- running：worker 正在执行导出
- completed：导出完成，manifest_object_key 与 export_path 可用
- failed：导出失败，error_message 可用

### GET /api/v1/datasets/{dataset_id}/versions/{dataset_version_id}/exports

按 DatasetVersion 查询导出记录列表，便于前端在训练前选择已有 export file 或复用最近一次成功导出。

#### 路径参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| dataset_id | string | 是 | 所属 Dataset id。 |
| dataset_version_id | string | 是 | 要查询的 DatasetVersion id。 |

#### 返回规则

- 状态码：200 OK
- 返回当前 DatasetVersion 下可见的导出记录摘要列表
- 列表按 created_at 倒序返回

## 导出目录语义

当请求不显式提供 output_object_prefix 时，导出文件默认写到：

- projects/{project_id}/datasets/{dataset_id}/exports/{dataset_export_id}

当前实现会在该根目录下写出：

- manifest.json：统一导出 manifest，training 应消费它的 object key
- COCO detection：annotations/instances_{split}.json、images/{split}/...
- VOC detection：Annotations/*.xml、JPEGImages/*、ImageSets/Main/{split}.txt

## 调试建议

- 资源视角：GET /api/v1/datasets/exports/{dataset_export_id}
- 任务视角：GET /api/v1/tasks/{task_id}、GET /api/v1/tasks/{task_id}/events、/ws/tasks/events?task_id=...
- 当状态为 completed 时，优先检查 manifest_object_key 和 export_path 是否符合预期，再进入 training 前置步骤