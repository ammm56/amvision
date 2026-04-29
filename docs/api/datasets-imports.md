# DatasetImport 接口文档

## 文档目的

本文档用于说明当前已经公开的 DatasetImport REST 接口，包括 zip 上传导入、导入详情查询和导入列表查询三组能力。

当前导入提交已经正式关联 TaskRecord。提交响应、详情响应和列表响应都会公开 task_id，后续可以配合 tasks API 或 /ws/tasks/events 观察后台处理状态。

本文档聚焦对外接口规则、字段定义、错误语义和当前实现边界，不展开内部 repository 或持久化实现细节。

## 适用范围

- Dataset zip 导入接口
- DatasetImport 详情查询接口
- Dataset 下的导入记录列表接口
- 请求头鉴权规则
- 常见错误码和调试方式

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

- 导入接口需要 datasets:write
- 查询接口需要 datasets:read

## 接口清单

### POST /api/v1/datasets/imports

上传 zip 数据集压缩包，登记一条 received 状态的 DatasetImport 并提交到本地队列；worker 后续再解析并生成 DatasetVersion。

#### Content-Type

- multipart/form-data

#### multipart 表单字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | string | 是 | 所属 Project id。接口会用它做权限可见性校验。 |
| dataset_id | string | 是 | 所属 Dataset id。当前导入记录和生成的 DatasetVersion 都挂到这个 Dataset 下。 |
| package | file | 是 | zip 压缩包文件。当前接口只接受 zip。 |
| format_type | string \| null | 否 | 显式指定数据集格式。当前支持 coco、voc。为空时自动识别。 |
| task_type | string | 否 | 任务类型。默认 detection。当前实现只支持 detection。 |
| split_strategy | string \| null | 否 | 显式 split 策略。允许值为 auto、train、val、test。auto 表示按数据集结构自动识别；train、val、test 表示强制把全部样本归到对应 split。 |
| class_map_json | string \| null | 否 | JSON 对象字符串。键和值都会被转成 string，用于覆盖导入时识别到的类别映射。 |

#### curl 示例

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/datasets/imports" \
  -H "x-amvision-principal-id: user-1" \
  -H "x-amvision-project-ids: project-1" \
  -H "x-amvision-scopes: datasets:write" \
  -F "project_id=project-1" \
  -F "dataset_id=dataset-1" \
  -F "task_type=detection" \
  -F "package=@barcodeqrcode.zip"
```

#### 成功响应

- 状态码：202 Accepted

```json
{
  "dataset_import_id": "dataset-import-fbd01147194e",
  "task_id": "task-22c631b92aef",
  "status": "received",
  "upload_state": "uploaded",
  "processing_state": "queued",
  "package_size": 7538487,
  "package_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-fbd01147194e/package.zip",
  "staging_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-fbd01147194e/staging/extracted",
  "queue_name": "dataset-imports",
  "queue_task_id": "queue-task-0fce7c3131df"
}
```

#### 成功响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| dataset_import_id | string | 新创建的导入记录 id。后续详情查询和轮询都使用这个值。 |
| task_id | string \\| null | 关联的正式 TaskRecord id。后续任务详情、事件查询和 WebSocket 订阅都使用这个值。 |
| status | string | 导入记录当前状态。提交成功后立即返回 received。 |
| upload_state | string | 上传状态。当前成功接收并落盘后返回 uploaded。 |
| processing_state | string | 后台处理状态。当前 accepted 响应固定返回 queued。 |
| package_size | integer | 已保存的原始 zip 文件字节大小。 |
| package_path | string | 原始 zip 包在 data/files 下的相对路径。 |
| staging_path | string | staging/extracted 工作目录在 data/files 下的相对路径。当前实现会在导入成功后清空其中的临时解压内容，并保留空目录作为审计锚点。 |
| queue_name | string | 提交到的队列名称。当前固定为 dataset-imports。 |
| queue_task_id | string | 当前导入对应的队列任务 id。 |

#### 上传成功与处理进度判断

- 当 POST /imports 返回 202 Accepted，且响应中的 upload_state 为 uploaded 时，可以判定 zip 文件已经完整落到 package.zip，上传本身已成功。
- 返回 202 只表示“包已收到并已入队”，不表示解析、校验和版本生成已经完成。
- 后续处理进度通过轮询 GET /api/v1/datasets/imports/{dataset_import_id} 或 GET /api/v1/datasets/{dataset_id}/imports 获得。
- 如果响应中返回了 task_id，也可以调用 GET /api/v1/tasks/{task_id}、GET /api/v1/tasks/{task_id}/events，或订阅 /ws/tasks/events?task_id=... 观察任务状态和事件流。
- 当前 processing_state 与 status 的对应关系为：received -> queued，extracted 或 validated -> running，completed -> completed，failed -> failed。
- 如果需要在 HTTP 请求尚未结束前观察上传字节进度，当前单次 multipart 上传接口本身不提供服务端查询接口，进度应由浏览器或客户端 SDK 的 upload progress 事件自行统计。服务端只有在 POST 返回 202 之后，才会暴露 uploaded 状态。

#### split_strategy 请求与响应语义

- 请求允许值：auto、train、val、test。
- detail 响应中的 split_strategy 返回的是实际生效后的策略标记，而不是原始请求值。
- 当前已落地的响应值包括：manifest-name、image_sets、default-train、forced-train、forced-val、forced-test。
- manifest-name 表示 COCO 通过 manifest 文件名推断 split。
- image_sets 表示 Pascal VOC 通过 ImageSets/Main 下的 split 文件推断 split。
- default-train 表示既没有显式 split，也没有检测到可用 split 信息时，默认全部归到 train。
- forced-* 表示调用方通过请求参数显式覆盖了导入器自动识别出的 split。

#### 失败响应

- 400：请求字段不完整、class_map_json 不是合法 JSON、zip 内容非法
- 401：缺少主体信息
- 403：主体没有 datasets:write scope，或 project_id 不在可访问范围内
- 422：当前数据格式、task_type 或 split_strategy 不支持
- 503：持久化或数据库操作失败

### GET /api/v1/datasets/imports/{dataset_import_id}

按 DatasetImport id 查询导入记录详情，返回导入记录、识别结果、校验报告和关联 DatasetVersion 摘要。

#### 路径参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| dataset_import_id | string | 是 | 要查询的 DatasetImport id。 |

#### 成功响应

- 状态码：200 OK

```json
{
  "dataset_import_id": "dataset-import-fbd01147194e",
  "task_id": "task-22c631b92aef",
  "dataset_id": "dataset-1",
  "project_id": "project-1",
  "format_type": "voc",
  "task_type": "detection",
  "status": "completed",
  "created_at": "2026-04-29T05:57:36.769213+00:00",
  "dataset_version_id": "dataset-version-664536df286f",
  "package_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-fbd01147194e/package.zip",
  "staging_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-fbd01147194e/staging/extracted",
  "version_path": "projects/project-1/datasets/dataset-1/versions/dataset-version-664536df286f",
  "package_size": 7538487,
  "upload_state": "uploaded",
  "processing_state": "completed",
  "queue_task_id": "queue-task-0fce7c3131df",
  "image_root": "JPEGImages",
  "annotation_root": "Annotations",
  "manifest_file": "Annotations/barcode1.xml",
  "split_strategy": "image_sets",
  "class_map": {
    "0": "barcode",
    "1": "qrcode"
  },
  "detected_profile": {
    "detected_candidates": ["voc"],
    "format_type": "voc",
    "task_type": "detection",
    "manifest_files": [
      "Annotations/barcode1.xml"
    ],
    "annotation_root": "Annotations",
    "image_root": "JPEGImages",
    "split_names": [
      "train",
      "test"
    ],
    "split_counts": {
      "train": 6,
      "test": 4
    }
  },
  "validation_report": {
    "status": "ok",
    "format_type": "voc",
    "task_type": "detection",
    "category_count": 2,
    "sample_count": 10,
    "split_counts": {
      "train": 6,
      "test": 4
    },
    "warnings": [],
    "errors": [],
    "error": null
  },
  "error_message": null,
  "metadata": {
    "source_file_name": "barcodeqrcode.zip",
    "package_size": 7538487,
    "principal_id": "user-1",
    "sample_count": 10,
    "category_count": 2,
    "split_counts": {
      "train": 6,
      "test": 4
    }
  },
  "dataset_version": {
    "dataset_version_id": "dataset-version-664536df286f",
    "dataset_id": "dataset-1",
    "project_id": "project-1",
    "task_type": "detection",
    "sample_count": 10,
    "category_count": 2,
    "split_names": [
      "train",
      "test"
    ],
    "metadata": {
      "source_import_id": "dataset-import-fbd01147194e",
      "format_type": "voc",
      "image_root": "JPEGImages",
      "annotation_root": "Annotations",
      "manifest_file": "Annotations/barcode1.xml",
      "split_strategy": "image_sets",
      "split_counts": {
        "train": 6,
        "test": 4
      }
    }
  }
}
```

#### 顶层响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| dataset_import_id | string | 导入记录 id。 |
| task_id | string \| null | 关联的正式 TaskRecord id。 |
| dataset_id | string | 逻辑 Dataset id。 |
| project_id | string | 所属 Project id。 |
| format_type | string \| null | 导入识别出的格式类型。失败或未识别完成时可能为 null。 |
| task_type | string | 当前导入任务类型。 |
| status | string | 当前导入状态，例如 received、completed、failed。 |
| created_at | string | 导入记录创建时间，ISO 8601 格式。 |
| dataset_version_id | string \| null | 成功生成的 DatasetVersion id。失败时通常为 null。 |
| package_path | string | 原始 zip 包在 data/files 下的相对路径。 |
| staging_path | string | staging/extracted 目录在 data/files 下的相对路径。 |
| version_path | string \| null | 正式 DatasetVersion 目录在 data/files 下的相对路径。 |
| package_size | integer \| null | 原始 zip 包大小。 |
| upload_state | string \| null | 上传状态。当前成功落盘后为 uploaded。 |
| processing_state | string | 当前后台处理状态。 |
| queue_task_id | string \| null | 当前导入关联的队列任务 id。 |
| image_root | string \| null | 从原始压缩包中识别出的图片根目录。 |
| annotation_root | string \| null | 从原始压缩包中识别出的标注根目录。 |
| manifest_file | string \| null | 用于识别和导入的代表性 manifest 文件路径。COCO 通常是 json，VOC 通常是首个 xml。 |
| split_strategy | string \| null | 当前导入最终采用的 split 策略标记。返回值见上面的 split_strategy 请求与响应语义。 |
| class_map | object | 归一化后的类别映射。键为归一化后的字符串 category id，值为类别名。 |
| detected_profile | object | 识别阶段输出的格式签名、目录特征和 split 概况。当前接口已经把它收敛成显式响应模型。 |
| validation_report | object | 校验阶段输出的结构化报告。当前接口已经把它收敛成显式响应模型。 |
| error_message | string \| null | 导入失败时的错误消息。成功时通常为 null。 |
| metadata | object | 附加元数据。当前会记录源文件名、包大小、主体 id 和统计信息。 |
| dataset_version | object \| null | 关联 DatasetVersion 的摘要。导入失败或版本未写入时为 null。 |

#### detected_profile 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| detected_candidates | array of string | 导入器在识别阶段命中的候选格式列表。 |
| format_type | string | 最终确认的格式类型。 |
| task_type | string | 最终确认的任务类型。 |
| manifest_files | array of string | 识别阶段收集到的 manifest 文件列表。 |
| annotation_root | string | 原始压缩包中的标注根目录。 |
| image_root | string | 原始压缩包中的图片根目录。 |
| split_names | array of string | 导入器识别出的 split 列表。 |
| split_counts | object | 每个 split 对应的样本数。键为 split 名称，值为样本数。 |

#### validation_report 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| status | string | 校验结果状态。当前成功值为 ok，失败值为 failed。 |
| format_type | string | 校验所针对的格式类型。 |
| task_type | string | 校验所针对的任务类型。 |
| category_count | integer | 校验后类别总数。 |
| sample_count | integer | 校验后样本总数。 |
| split_counts | object | 每个 split 对应的样本数。 |
| warnings | array | 校验阶段的警告列表。当前最小实现通常为空数组。 |
| errors | array | 校验阶段的错误列表。成功时为空数组，失败时可能包含结构化错误信息。 |
| error | object \| null | 失败时的稳定错误对象。当前包含 code、message 和 details。 |

#### metadata 当前标准字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| source_file_name | string | 上传 zip 文件名。 |
| package_size | integer | 原始 zip 文件字节大小。 |
| uploaded_bytes | integer | 当前已保存的上传字节数。单次 multipart 上传完成后与 package_size 相同。 |
| upload_state | string | 上传状态。当前已落盘时为 uploaded。 |
| uploaded_at | string | 上传完成时间，ISO 8601 格式。 |
| task_id | string | 关联的正式 TaskRecord id。 |
| queue_name | string | 当前导入提交到的队列名称。 |
| queue_task_id | string | 当前导入关联的队列任务 id。 |
| principal_id | string | 发起本次导入的主体 id。 |
| sample_count | integer | 导入成功后的样本总数。 |
| category_count | integer | 导入成功后的类别总数。 |
| split_counts | object | 导入成功后的 split 样本分布。 |

#### dataset_version 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| dataset_version_id | string | 关联 DatasetVersion id。 |
| dataset_id | string | 所属 Dataset id。 |
| project_id | string | 所属 Project id。 |
| task_type | string | 版本任务类型。 |
| sample_count | integer | 版本样本总数。 |
| category_count | integer | 版本类别总数。 |
| split_names | array of string | 版本包含的 split 列表。 |
| metadata | object | 版本元数据。当前会记录 source_import_id、format_type、image_root、annotation_root、manifest_file、split_strategy、split_counts。 |

#### 失败响应

- 401：缺少主体信息
- 403：主体没有 datasets:read scope
- 404：找不到指定的 DatasetImport，或当前主体对其所属 Project 不可见
- 503：持久化或数据库操作失败

### GET /api/v1/datasets/{dataset_id}/imports

按 Dataset id 返回当前数据集下的导入记录摘要列表。

#### 路径参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| dataset_id | string | 是 | 要列出导入记录的 Dataset id。 |

#### 成功响应

- 状态码：200 OK

```json
[
  {
    "dataset_import_id": "dataset-import-fbd01147194e",
    "task_id": "task-22c631b92aef",
    "dataset_id": "dataset-1",
    "project_id": "project-1",
    "format_type": "voc",
    "task_type": "detection",
    "status": "completed",
    "created_at": "2026-04-29T05:57:36.769213+00:00",
    "dataset_version_id": "dataset-version-664536df286f",
    "package_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-fbd01147194e/package.zip",
    "staging_path": "projects/project-1/datasets/dataset-1/imports/dataset-import-fbd01147194e/staging/extracted",
    "version_path": "projects/project-1/datasets/dataset-1/versions/dataset-version-664536df286f",
    "package_size": 7538487,
    "upload_state": "uploaded",
    "processing_state": "completed",
    "queue_task_id": "queue-task-0fce7c3131df",
    "validation_status": "ok",
    "error_message": null
  }
]
```

#### 列表项字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| dataset_import_id | string | 导入记录 id。 |
| task_id | string \| null | 关联的正式 TaskRecord id。 |
| dataset_id | string | 所属 Dataset id。 |
| project_id | string | 所属 Project id。 |
| format_type | string \| null | 当前记录的格式类型。 |
| task_type | string | 当前记录的任务类型。 |
| status | string | 导入状态。 |
| created_at | string | 导入记录创建时间，ISO 8601 格式。 |
| dataset_version_id | string \| null | 关联 DatasetVersion id。 |
| package_path | string | 原始 zip 包相对路径。 |
| staging_path | string | 解压目录相对路径。 |
| version_path | string \| null | 版本目录相对路径。 |
| package_size | integer \| null | 原始 zip 包大小。 |
| upload_state | string \| null | 上传状态。 |
| processing_state | string | 当前后台处理状态。 |
| queue_task_id | string \| null | 关联的队列任务 id。 |
| validation_status | string \| null | 从 validation_report 中抽取的状态字段。 |
| error_message | string \| null | 导入失败时的错误消息。 |

#### 失败响应

- 401：缺少主体信息
- 403：主体没有 datasets:read scope
- 503：持久化或数据库操作失败

## 错误响应格式

接口统一返回如下错误结构：

```json
{
  "error": {
    "code": "resource_not_found",
    "message": "找不到指定的 DatasetImport",
    "details": {
      "dataset_import_id": "dataset-import-missing"
    },
    "request_id": "80d2eed6-e094-4f75-8cbf-01e32293a088"
  }
}
```

## 常见错误码

- authentication_required：缺少请求主体
- permission_denied：缺少所需 scope 或 Project 不可访问
- invalid_request：请求字段错误、zip 内容非法、class_map_json 非法
- unsupported_dataset_format：当前数据格式、task_type 或 split_strategy 不支持
- resource_not_found：导入记录不存在或当前主体不可见
- persistence_operation_error：数据库或持久化操作失败

## 当前实现边界

- 当前导入接口只支持 zip 压缩包。
- 当前任务类型只支持 detection。
- 当前自动识别只覆盖 COCO detection 和 Pascal VOC detection。
- 当前上传流程会先把 zip 流式写入 package.zip，再提交一条 received 状态的 DatasetImport、创建关联 TaskRecord 并入队；解析、校验和版本生成由独立 worker 从本地持久化队列异步执行。
- task_id 是正式任务主记录 id，queue_task_id 只是队列里的调度消息 id；两者用途不同。
- 当前导入成功后会清空 staging/extracted 中的临时解压内容；如需重做解析或人工复查，应以 package.zip 为准重新执行处理。
- package_path、staging_path、version_path 都是 data/files 根目录下的相对路径，不是可直接下载的 HTTP URL。
- detected_profile 和 validation_report 已经收敛为显式响应模型；metadata 仍保留为通用 object，并以本文档字段说明为准。
- 当前单次 multipart 上传接口不提供“请求未完成时的服务端上传百分比查询”。如果需要真正的大文件分片上传和可恢复进度，应新增 upload session 或对象存储 multipart 直传接口。

## 调试建议

- 本地调试时优先先调用导入接口，再把响应里的 dataset_import_id 填给详情查询接口。
- 如果导入失败，先看详情接口里的 validation_report 和 error_message。
- 如果需要用 Postman 直接调试，可导入 [docs/api/postman/datasets-imports.postman_collection.json](postman/datasets-imports.postman_collection.json)。