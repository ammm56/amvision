# DatasetExport 接口文档

## 文档目的

本文档用于说明当前已经公开的 DatasetExport REST 接口，包括导出创建、导出详情查询和按 DatasetVersion 列表查询三组能力。

当前导出提交已经正式关联 TaskRecord。提交响应、详情响应和列表响应都会公开 task_id，后续可以配合 tasks API 或 /ws/v1/tasks/events 观察后台处理状态。当前导出也已经公开打包和下载接口，export file 不再只是内部 worker 使用的中间结果。

本文档聚焦对外接口规则、字段定义、错误语义和当前实现边界，不展开内部 repository 或持久化实现细节。

## 适用范围

- DatasetExport 创建接口
- DatasetExport 详情查询接口
- DatasetVersion 下的导出记录列表接口
- DatasetExport 打包与下载接口
- 请求头鉴权规则
- 当前已实现导出格式与 training 输入边界

## 接口入口

- FastAPI Swagger UI：/docs
- FastAPI OpenAPI JSON：/openapi.json
- 版本前缀：/api/v1
- 资源分组：/datasets

## 鉴权规则

当前接口通过 `Authorization: Bearer <token>` 鉴权。`scopes` 和 `project_ids` 从 Bearer token 对应的本地用户或静态 token 配置中解析。

### 最小请求头

- Authorization: Bearer <token>
- 使用当前环境实际 Bearer token

### scope 要求

- 创建接口需要 datasets:write
- 查询和下载接口需要 datasets:read
- 打包接口需要 datasets:write

## 当前实现边界

- 当前只支持 detection 类型 DatasetVersion
- 当前已经正式实现并对外开放的 format_id：
  - coco-detection-v1
  - voc-detection-v1
- DatasetImport 可以兼容多种外部目录结构与命名方式，但 DatasetExport 不保留原始导入包的目录结构；导出阶段始终按 format_id 收口为单一标准格式
- 当前如果 format_id=coco-detection-v1，则目录结构固定为 images/{split}/ 和 annotations/instances_{split}.json，不再区分传统 annotations 目录、年份后缀命名或 Roboflow split-local manifest 这类导入变体
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

#### format_id 语义

- format_id 控制的是导出目标标准格式，不是导入阶段识别到的原始目录变体
- 当前若请求 coco-detection-v1，服务会统一生成 COCO 标准导出目录：images/{split}/、annotations/instances_{split}.json、manifest.json
- 当前若请求 voc-detection-v1，服务会统一生成 Pascal VOC 标准导出目录：Annotations/、JPEGImages/、ImageSets/Main/、manifest.json
- 当前接口没有再提供“导出成哪一种 COCO 原始目录变体”的额外参数；如果后续需要新的 COCO 导出布局，应新增独立 format_id，而不是复用 coco-detection-v1

#### curl 示例

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/datasets/exports" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
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

### POST /api/v1/datasets/exports/{dataset_export_id}/package

为指定 DatasetExport 生成 zip 下载包。当前接口会把下载包信息写回 DatasetExport.metadata，并在详情接口中同步公开。

这个步骤不会重新渲染另一套导出目录结构，只会把当前 DatasetExport 已经生成好的 export_path 原样打包为 zip。

#### 路径参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| dataset_export_id | string | 是 | 要打包的 DatasetExport id。 |

#### 成功响应要点

- 状态码：200 OK
- 返回字段包括：
  - dataset_export_id
  - export_path
  - manifest_object_key
  - package_object_key
  - package_file_name
  - package_size
  - packaged_at

#### 默认打包位置

- projects/{project_id}/datasets/{dataset_id}/downloads/dataset-exports/{dataset_export_id}.zip

### GET /api/v1/datasets/exports/{dataset_export_id}/download

下载指定 DatasetExport 的 zip 包。

#### 返回规则

- 状态码：200 OK
- 返回 application/zip 文件响应
- 当下载包不存在时，当前实现会先同步打包，再直接返回下载结果
- 下载内容与对应 DatasetExport 的 export_path 保持一致，不会在下载阶段再切换为另一种 COCO 目录结构

### GET /api/v1/datasets/exports/{dataset_export_id}/manifest

下载指定 DatasetExport 的 manifest 文件。

#### 返回规则

- 状态码：200 OK
- 返回 application/json 文件响应
- 返回内容就是 manifest_object_key 对应的 manifest.json

## dataset_export_id 与 manifest_object_key 的关系

- dataset_export_id：平台资源主键。用于详情查询、列表展示、前端选择、打包下载、权限控制、审计和训练任务创建。
- manifest_object_key：导出文件边界。用于训练 worker、脚本、离线执行器或其他直接消费导出文件的逻辑。
- 一个完成态 DatasetExport 必须稳定对应一个 manifest_object_key。
- 当前训练创建接口允许传 dataset_export_id 或 manifest_object_key；如果同时传两者，服务会验证它们是否属于同一个 DatasetExport。
- 实践上：面向用户和平台资源管理时优先传 dataset_export_id，面向执行器和文件消费侧时优先用 manifest_object_key。

## 导出目录语义

当请求不显式提供 output_object_prefix 时，导出文件默认写到：

- projects/{project_id}/datasets/{dataset_id}/exports/{dataset_export_id}

当前实现会在该根目录下写出：

- manifest.json：统一导出 manifest，training 应消费它的 object key
- COCO detection：annotations/instances_{split}.json、images/{split}/...
- VOC detection：Annotations/*.xml、JPEGImages/*、ImageSets/Main/{split}.txt

这里的“统一导出”含义是：无论原始导入包是传统 annotations 目录、年份后缀 COCO，还是 Roboflow 风格 split-local manifest，只要导出目标 format_id 相同，最后写出的目录结构就相同。

打包接口不会把 zip 文件写到 export_path 目录内部，而是写到 Dataset 级下载目录，避免导出目录与下载包互相递归嵌套。

## 调试建议

- 资源视角：GET /api/v1/datasets/exports/{dataset_export_id}
- 下载视角：POST /api/v1/datasets/exports/{dataset_export_id}/package、GET /api/v1/datasets/exports/{dataset_export_id}/download、GET /api/v1/datasets/exports/{dataset_export_id}/manifest
- 任务视角：GET /api/v1/tasks/{task_id}、GET /api/v1/tasks/{task_id}/events、/ws/v1/tasks/events?task_id=...
- 当状态为 completed 时，优先检查 manifest_object_key 和 export_path 是否符合预期，再进入 training 前置步骤