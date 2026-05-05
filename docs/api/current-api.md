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
| POST | /api/v1/models/yolox/training-tasks/{task_id}/save | tasks:write | 为 running 的 YOLOX 训练任务登记一次手动保存请求。 |
| POST | /api/v1/models/yolox/training-tasks/{task_id}/pause | tasks:write | 为 running 的 YOLOX 训练任务请求暂停，并在下一轮边界先保存 latest checkpoint。 |
| POST | /api/v1/models/yolox/training-tasks/{task_id}/resume | tasks:write | 把 paused 的 YOLOX 训练任务重新入队，并基于 latest checkpoint 恢复训练。 |
| POST | /api/v1/models/yolox/training-tasks/{task_id}/register-model-version | tasks:write + models:write | 调试时手动重登记当前 latest checkpoint 对应的固定 latest ModelVersion，并回写到训练详情。 |
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

### POST /api/v1/models/yolox/evaluation-tasks

- 需要同时具备 datasets:read、models:read 和 tasks:write
- 当前请求体允许显式指定：
  - project_id
  - model_version_id
  - dataset_export_id
  - dataset_export_manifest_key
  - score_threshold
  - nms_threshold
  - save_result_package
  - extra_options
  - display_name
- 当前实现会先解析 DatasetExport，再校验 ModelVersion 到 checkpoint、labels 的本地可读性，然后把任务放入 `yolox-evaluations` 队列
- 当前最小评估链只支持 `coco-detection-v1` 导出输入
- 当前响应会返回：
  - task_id
  - status
  - queue_name
  - queue_task_id
  - dataset_export_id
  - dataset_export_manifest_key
  - dataset_version_id
  - format_id
  - model_version_id

### GET /api/v1/models/yolox/evaluation-tasks

- 需要 tasks:read
- 当前支持的查询参数：
  - project_id
  - state
  - created_by
  - dataset_export_id
  - dataset_export_manifest_key
  - model_version_id
  - limit
- 当前列表响应会同时公开：
  - task_id
  - state
  - dataset_export_id
  - dataset_export_manifest_key
  - dataset_version_id
  - format_id
  - model_version_id
  - score_threshold
  - nms_threshold
  - save_result_package
  - output_object_prefix
  - report_object_key
  - detections_object_key
  - result_package_object_key
  - map50
  - map50_95
  - report_summary

### GET /api/v1/models/yolox/evaluation-tasks/{task_id}

- 需要 tasks:read
- 默认 include_events=true
- 返回单条 YOLOX 评估任务详情，包括 task_spec、events、report_summary 和结果文件 object key
- 当前 progress 会在执行期回写 `stage` 和 `percent`

### GET /api/v1/models/yolox/evaluation-tasks/{task_id}/report

- 需要 tasks:read
- 返回当前评估任务最新的 evaluation-report.json 内容
- 当前响应统一为 `file_status`、`task_state`、`object_key` 和 `payload`
- 当评估文件尚未生成时，接口返回 `file_status=pending` 和空 `payload`
- 当任务已经结束但 report 文件缺失时，接口返回 404

### GET /api/v1/models/yolox/evaluation-tasks/{task_id}/output-files

- 需要 tasks:read
- 当前统一列出 `report`、`detections` 和 `result-package` 这 3 个评估输出文件
- `save_result_package=false` 且任务完成时，`result-package` 会以 `file_status=skipped` 返回
- 每个条目都会返回 `file_name`、`file_kind`、`file_status`、`task_state`、`object_key`、`size_bytes` 和 `updated_at`

### POST /api/v1/models/yolox/deployment-instances

- 需要 models:read 和 models:write
- 当前请求体允许显式指定：
  - project_id
  - model_version_id
  - model_build_id
  - runtime_profile_id
  - runtime_backend
  - device_name
  - instance_count
  - display_name
  - metadata
- 当前最小实现允许直接绑定训练产出的 `ModelVersion`，也允许绑定 `ModelBuild`；如果同时提供 `model_build_id` 和 `model_version_id`，两者必须指向同一来源版本
- 当前 create 会在提交阶段校验 checkpoint 和 labels 的本地可读性
- 当前 `runtime_backend` 只支持 `pytorch`
- 当前 `instance_count` 默认为 1；每个 instance 对应一个独立推理线程和模型会话
- 当前响应会返回：
  - deployment_instance_id
  - project_id
  - model_id
  - model_version_id
  - model_build_id
  - model_name
  - model_scale
  - task_type
  - runtime_profile_id
  - runtime_backend
  - device_name
  - instance_count
  - input_size
  - labels
  - status

### GET /api/v1/models/yolox/deployment-instances

- 需要 models:read
- 当前支持的查询参数：
  - project_id
  - model_version_id
  - model_build_id
  - deployment_status
  - limit
- 当前列表返回最小 DeploymentInstance 摘要，不暴露 checkpoint 路径

### GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}

- 需要 models:read
- 返回单条 DeploymentInstance 详情，包括绑定的模型、运行时、输入尺寸和 labels

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/start

- 需要 models:read 和 models:write
- 显式启动指定 deployment 的同步推理子进程
- 当前响应会返回：
  - deployment_instance_id
  - display_name
  - runtime_mode
  - desired_state
  - process_state
  - process_id
  - auto_restart
  - restart_count
  - last_exit_code
  - last_error
  - instance_count

### GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/status

- 需要 models:read
- 返回指定 deployment 当前同步推理子进程的监督状态

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/stop

- 需要 models:read 和 models:write
- 显式停止指定 deployment 的同步推理子进程

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/warmup

- 需要 models:read 和 models:write
- 显式启动并预热指定 deployment 的所有同步推理实例
- 当前响应会返回：
  - deployment_instance_id
  - display_name
  - runtime_mode
  - desired_state
  - process_state
  - process_id
  - auto_restart
  - restart_count
  - last_exit_code
  - last_error
  - instance_count
  - healthy_instance_count
  - warmed_instance_count
  - instances[].instance_id
  - instances[].healthy
  - instances[].warmed
  - instances[].busy
  - instances[].last_error

### GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/health

- 需要 models:read
- 返回指定 deployment 当前同步推理子进程及实例池的详细健康视图

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/reset

- 需要 models:read 和 models:write
- 重置指定 deployment 的同步推理实例池
- 如果同步推理子进程尚未启动，接口返回 `invalid_request`

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/start

- 需要 models:read 和 models:write
- 显式启动指定 deployment 的异步推理子进程

### GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/status

- 需要 models:read
- 返回指定 deployment 当前异步推理子进程的监督状态

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/stop

- 需要 models:read 和 models:write
- 显式停止指定 deployment 的异步推理子进程

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/warmup

- 需要 models:read 和 models:write
- 显式启动并预热指定 deployment 的所有异步推理实例

### GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/health

- 需要 models:read
- 返回指定 deployment 当前异步推理子进程及实例池的详细健康视图

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/reset

- 需要 models:read 和 models:write
- 重置指定 deployment 的异步推理实例池
- 如果异步推理子进程尚未启动，接口返回 `invalid_request`

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/infer

- 需要 models:read
- 这是同步直返推理接口；当前只使用 deployment 的同步推理子进程，并按 instance 简单轮转执行
- 当前要求 deployment 的 sync 进程已经通过 `sync/start` 或 `sync/warmup` 启动；未启动时返回 `invalid_request`
- 当前支持 `application/json` 和 `multipart/form-data`
- 输入 one-of 规则：`input_uri`、`image_base64`、`input_image` 三者必须且只能提供一个
- JSON 请求可显式指定：
  - input_uri
  - image_base64
  - input_file_id
  - input_transport_mode：仅同步 `/infer` 使用，支持 `storage`、`memory`
  - score_threshold
  - save_result_image
  - return_preview_image_base64
  - extra_options
- multipart 请求可显式指定：
  - input_image
  - input_uri
  - image_base64
  - input_file_id
  - input_transport_mode：仅同步 `/infer` 使用，支持 `storage`、`memory`
  - score_threshold
  - save_result_image
  - return_preview_image_base64
  - extra_options：JSON 字符串
- 当前 `input_file_id` 仍是保留字段，会返回 `invalid_request`
- 当前同步 `/infer` 支持 `input_transport_mode=memory`：仅允许 `image_base64` 或 `input_image`，请求图片不会写入临时输入文件，而是直接以内存字节送入 deployment 子进程
- 当同步 `/infer` 使用 `input_transport_mode=memory` 时，响应 `input_uri` 会返回 `memory://...` 虚拟 URI，`result_object_key` 为 `null`
- 当前响应会直接返回统一推理载荷，重点字段包括：
  - request_id
  - deployment_instance_id
  - instance_id
  - input_uri
  - input_source_kind
  - detections
  - latency_ms：decode、preprocess、infer、postprocess 四段总耗时
  - decode_ms
  - preprocess_ms
  - infer_ms
  - postprocess_ms
  - serialize_ms
  - preview_image_uri
  - preview_image_base64
  - runtime_session_info

### POST /api/v1/models/yolox/inference-tasks

- 需要 models:read 和 tasks:write
- 当前请求体允许显式指定：
  - project_id
  - deployment_instance_id
  - input_file_id
  - input_uri
  - image_base64
  - score_threshold
  - save_result_image
  - return_preview_image_base64
  - extra_options
  - display_name
- 当前实现会先校验 `deployment_instance_id` 属于请求 Project，再按 one-of 规则把输入归一化后放入 `yolox-inferences` 队列
- 当前支持 `application/json` 和 `multipart/form-data`
- 输入 one-of 规则：`input_uri`、`image_base64`、`input_image` 三者必须且只能提供一个
- 当前 `input_file_id` 仍是保留字段，会返回 `invalid_request`
- 当前异步推理只使用 deployment 的 async 推理子进程；如果同步 `/infer` 已经加载过模型，异步侧仍会在自己的独立子进程中维护实例会话
- inference task 创建接口不会自动启动 async 推理子进程；如果当前 async 进程尚未通过 `async/start` 或 `async/warmup` 启动，接口会直接返回 `invalid_request`
- 当前响应会返回：
  - task_id
  - status
  - queue_name
  - queue_task_id
  - deployment_instance_id
  - input_uri
  - input_source_kind

### GET /api/v1/models/yolox/inference-tasks

- 需要 tasks:read
- 当前支持的查询参数：
  - project_id
  - state
  - created_by
  - deployment_instance_id
  - limit
- 当前列表响应会同时公开：
  - task_id
  - state
  - deployment_instance_id
  - instance_id
  - model_version_id
  - model_build_id
  - input_uri
  - input_source_kind
  - score_threshold
  - save_result_image
  - output_object_prefix
  - result_object_key
  - preview_image_object_key
  - detection_count
  - latency_ms
  - result_summary

### GET /api/v1/models/yolox/inference-tasks/{task_id}

- 需要 tasks:read
- 默认 include_events=true
- 返回单条 YOLOX 推理任务详情，包括 task_spec、events、result_summary 和结果文件 object key

### GET /api/v1/models/yolox/inference-tasks/{task_id}/result

- 需要 tasks:read
- 返回当前推理任务最新的 raw-result.json 内容
- 当前响应统一为 `file_status`、`task_state`、`object_key` 和 `payload`
- `payload` 与同步 `/infer` 使用同一套结果载荷字段；异步场景额外通过 `inference_task_id=request_id=task_id` 标识请求
- 当结果文件尚未生成时，接口返回 `file_status=pending` 和空 `payload`
- 当任务已经结束但结果文件缺失时，接口返回 404

### POST /api/v1/models/yolox/validation-sessions

- 需要 models:read
- 当前请求体允许显式指定：
  - project_id
  - model_version_id
  - runtime_profile_id
  - runtime_backend
  - device_name
  - score_threshold
  - save_result_image
  - extra_options
- 当前实现会沿 ModelVersion -> ModelFile -> checkpoint 链路校验模型文件是否可被本地文件存储解析，并返回已解析的 labels、input_size、checkpoint_storage_uri 和默认 runtime 配置
- 当前 runtime_backend 只支持 `pytorch`
- 当前 detail/create 响应会返回：
  - session_id
  - project_id
  - model_id
  - model_version_id
  - model_name
  - model_scale
  - source_kind
  - status
  - runtime_profile_id
  - runtime_backend
  - device_name
  - score_threshold
  - save_result_image
  - input_size
  - labels
  - checkpoint_file_id
  - checkpoint_storage_uri
  - labels_storage_uri
  - last_prediction

### GET /api/v1/models/yolox/validation-sessions/{session_id}

- 需要 models:read
- 返回单条 validation session 当前详情
- 当前 session 状态持久化在本地文件中，服务重启后仍可读取
- last_prediction 会在至少执行过一次 predict 后回填 prediction_id、raw_result_uri、preview_image_uri、latency_ms 和 detection_count

### POST /api/v1/models/yolox/validation-sessions/{session_id}/predict

- 需要 models:read
- 当前请求体允许显式指定：
  - input_uri
  - input_file_id
  - score_threshold
  - save_result_image
  - extra_options
- 当前最小实现只支持本地 `input_uri` 或 object key；`input_file_id` 当前会返回 invalid_request
- 当前预测会把 raw-result.json 固定写到 `runtime/validation-sessions/{session_id}/predictions/{prediction_id}/`，在 `save_result_image=true` 时额外写出 preview.jpg
- 当前响应会返回：
  - prediction_id
  - session_id
  - input_uri
  - score_threshold
  - detections
  - preview_image_uri
  - raw_result_uri
  - latency_ms
  - labels
  - runtime_session_info
  - image_width
  - image_height

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
- 当前公开 precision 字段只接受 fp16、fp32；未指定时默认 fp32。
- 当前 input_size 未指定时，真实训练默认使用 [640, 640]。
- 当前没有可用 GPU 时会回退到 CPU 训练，用于最小硬件支持和开发环境验证；只是速度会明显变慢。
- 当前 `save`、`pause` 都是“请求登记后等待下一个 epoch 边界生效”，不是同步完成动作。
- 当前 `resume` 会先把任务切回 `queued` 并重新入队；checkpoint 读取失败或配置不一致这类问题可能在后续 worker 执行阶段才把任务切成 `failed`。
- 当前训练详情响应已经正式公开 `available_actions` 和 `control_status`；前端可以直接按这两个字段收口按钮与控制态判断。
- 前端如果轮询训练详情，建议显式传 `include_events=false`；日志流优先使用 `/ws/tasks/events?task_id=...`。
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
- 返回单条 YOLOX 训练任务详情，包括 task_spec、events、训练结果文件 object key、顶层 `model_version_id`、`latest_checkpoint_model_version_id`、training_summary，以及正式训练控制字段 `available_actions` 与 `control_status`
- 如果训练尚未完成，并且已经在 `save` 或 `pause` 的 epoch 边界成功落盘 latest checkpoint，顶层 `model_version_id` 和 `training_summary.model_version_id` 会自动指向当前 latest checkpoint 的固定版本 id
- 如果训练已经完成，顶层 `model_version_id` 继续表示自动登记的 best checkpoint 版本，`latest_checkpoint_model_version_id` 表示 save/pause 自动登记或调试接口手动重登记的 latest checkpoint 版本；两者语义不同，不会互相覆盖
- training_summary 当前会同时公开训练运行设备、precision、GPU 数量、evaluation_interval、output_files、validation 摘要和 warm_start 摘要
- 前端或 Postman 如果只需要收口按钮与控制态，优先读取 `available_actions` 与 `control_status`，不必再直接依赖 `metadata.training_control`
- 当前 events 会包含逐 epoch 的 progress 事件，task.progress 会同步维护 epoch、max_epochs、evaluation_interval、validation_ran、evaluated_epochs、最佳指标和当前轮指标快照
- 当前 running 阶段会继续按 epoch 增量写 train-metrics.json；如果当前轮执行了真实验证评估，也会同步刷新 validation-metrics.json
- checkpoint 仍然只会在 save、pause 或训练完成时写到磁盘
- 如果 task_id 不属于 YOLOX 训练任务，当前接口返回 404

### POST /api/v1/models/yolox/training-tasks/{task_id}/save

- 需要 tasks:write
- 只允许 running 状态调用
- 服务会在下一个 epoch 边界把 latest checkpoint 落盘，补齐 labels.txt，并追加 checkpoint saved 事件

### POST /api/v1/models/yolox/training-tasks/{task_id}/pause

- 需要 tasks:write
- 只允许 running 状态调用
- 服务会在下一个 epoch 边界先保存 latest checkpoint、补齐 labels.txt，再把任务状态切到 paused

### POST /api/v1/models/yolox/training-tasks/{task_id}/resume

- 需要 tasks:write
- 只允许 paused 状态调用
- 接口会复用同一个 task_id，把任务重新放回队列，并基于 latest checkpoint 恢复 optimizer、epoch 和最佳指标状态

### POST /api/v1/models/yolox/training-tasks/{task_id}/register-model-version

- 需要 tasks:write 和 models:write
- 当前要求任务已经产生 latest checkpoint；正常链路里，`save` 或 `pause` 会在下一个 epoch 边界自动完成这次版本登记
- 当前接口主要用于调试或验证：服务会基于当前 latest checkpoint 手动重登记同一个固定 latest ModelVersion，首次调用创建，后续再次调用会更新已有版本，而不是新增多个版本
- 任务未完成时，接口会把 `model_version_id` 回写到训练详情顶层和 `training_summary`；任务完成后，自动 best checkpoint 版本仍保留在 `model_version_id`，latest checkpoint 版本通过 `latest_checkpoint_model_version_id` 暴露
- 当前接口返回训练任务详情，而不是单独的登记回执对象
- 当前训练任务原本的 `checkpoint_object_key` 仍保持“训练最佳 checkpoint”的语义，不会因为手动登记 latest checkpoint 而被覆盖

### GET /api/v1/models/yolox/training-tasks/{task_id}/validation-metrics

- 需要 tasks:read
- 返回当前训练任务最新的 validation-metrics.json 内容
- 当前响应统一为 `file_status`、`task_state`、`object_key` 和 `payload`
- 当训练已经跑到真实评估轮时，接口会返回最新一次增量写出的 validation-metrics.json
- 当验证文件尚未生成时，接口返回 `file_status=pending` 和空 `payload`；任务已经结束但文件缺失时返回 404

### GET /api/v1/models/yolox/training-tasks/{task_id}/train-metrics

- 需要 tasks:read
- 返回当前训练任务最新的 train-metrics.json 内容
- 当前响应统一为 `file_status`、`task_state`、`object_key` 和 `payload`
- 当前 train-metrics.json 会按 epoch 增量写出，running 或 paused 阶段也可以直接读取最近一轮快照
- 当训练指标文件尚未生成时，当前接口不会返回 404，而是返回 `file_status=pending` 和空 `payload`

### GET /api/v1/models/yolox/training-tasks/{task_id}/output-files

- 需要 tasks:read
- 统一列出 `train-metrics`、`validation-metrics`、`summary`、`labels`、`best-checkpoint`、`latest-checkpoint` 这 6 个训练输出文件
- running 或 paused 阶段通常会看到 `train-metrics` 已经进入 `ready`；如果当前轮做过真实验证评估，`validation-metrics` 也会进入 `ready`
- `latest-checkpoint` 仍然主要在 save、pause 或训练完成后进入 `ready`
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