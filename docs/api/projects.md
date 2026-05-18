# Project 与 Bootstrap 接口文档

## 文档目的

本文档说明当前已经公开的 Project 目录、Project 初始化和前端首屏 bootstrap 接口。

当前阶段的 Project 是本地 ObjectStore 上的工作区命名空间，不是单独的数据库主数据表。前端、工作站和外部集成应把 Project 当作 datasets、training、evaluation、conversion、deployment、workflow 和运行结果的统一作用域。

## 当前公开范围

- GET /api/v1/system/bootstrap
- POST /api/v1/projects/bootstrap
- GET /api/v1/projects
- GET /api/v1/projects/{project_id}
- GET /api/v1/projects/{project_id}/summary
- GET /api/v1/projects/{project_id}/files/metadata
- GET /api/v1/projects/{project_id}/files/content

## 设计边界

- Project 只负责命名空间、目录骨架和最小 manifest，不负责独立的增删改查主数据生命周期。
- Project bootstrap 只在本地磁盘上初始化 `projects/{project_id}` 相关骨架和 manifest，不会额外创建数据库 Project 表。
- system/bootstrap 是前端首屏和工作站首个 HTTP 聚合入口，用于一次性拿到当前主体、provider 目录、可见 Project 和关键能力摘要。
- Project summary 是工作台正式快照面，用于聚合 datasets、imports、exports、training、validation、evaluation、conversion、inference、workflows 和 deployments。
- 当前默认本地调试环境中，空库首次启动会写入默认 seed 用户：用户名 `amvar`、密码 `123456`、长期调用 token `amvision-default-user-token`。数据库已有用户数据时不会覆盖这组 seed。

## 鉴权规则

### 最小请求头

- Authorization: Bearer <token>

### scope 要求

- GET /api/v1/system/bootstrap：无；未登录也可调用
- POST /api/v1/projects/bootstrap：当前主体需要至少具备 `datasets:write` 或 `workflows:write`
- GET /api/v1/projects、GET /api/v1/projects/{project_id}、GET /api/v1/projects/{project_id}/summary`：需要 `workflows:read` 和 `models:read`
- GET /api/v1/projects/{project_id}/files/metadata`、GET /api/v1/projects/{project_id}/files/content`：需要 `workflows:read` 和 `models:read`

当 Bearer token 自带 `project_ids` 可见性裁剪时，Project 相关接口还会额外校验 `project_id` 是否在可访问范围内。

## 推荐调用顺序

### 前端首屏或工作站进入

1. 调用 GET /api/v1/system/bootstrap，读取当前主体、provider、visible_projects 和 capabilities。
2. 如果目标 Project 尚不存在，调用 POST /api/v1/projects/bootstrap 初始化工作区。
3. 调用 GET /api/v1/projects/{project_id}/summary，读取当前 Project 的工作台聚合快照。

### 新建 Project 后进入训练或 workflow 链路

1. POST /api/v1/projects/bootstrap
2. 训练发布链：datasets/imports -> datasets/export-formats -> datasets/exports -> training / validation / evaluation / conversion / deployment / inference
3. workflow app 链：workflows/node-catalog -> templates -> applications -> preview-runs -> app-runtimes -> runs / invoke

## GET /api/v1/system/bootstrap

- 成功状态码：200 OK
- 当前接口支持匿名调用；如果未携带 Bearer token，则 `current_user` 为空，`visible_projects` 返回空数组。
- 当前接口用于前端首屏初始化，不替代 `GET /api/v1/system/me` 的主体详情接口。

### 当前响应字段

- `auth_mode`
- `bearer_auth_enabled`
- `websocket_query_token_enabled`
- `current_user`
- `providers`
- `visible_projects`
- `capabilities`

### current_user 重点字段

- `principal_id`
- `principal_type`
- `project_ids`
- `scopes`
- `username`
- `display_name`
- `auth_source`
- `auth_provider_id`
- `auth_provider_kind`
- `auth_credential_kind`
- `auth_credential_id`
- `auth_session_id`
- `auth_token_id`
- `auth_token_name`

### capabilities 重点字段

- `project_bootstrap_enabled`
- `dataset_export.supported_formats`
- `dataset_export.implemented_formats`
- `dataset_export.default_format`
- `project_summary_topics`

### 当前调试语义

- 默认空库调试环境里，使用 `amvision-default-user-token` 调用时，`current_user.username` 应返回 `amvar`。
- 当前默认会把 `project_bootstrap_enabled` 返回为 `true`。
- 当前默认会把 `dataset_export.default_format` 返回为 `coco-detection-v1`。

## POST /api/v1/projects/bootstrap

- 成功状态码：201 Created
- 用于初始化一个 Project 目录、最小 manifest 和工作区骨架。
- 当前接口是幂等偏保守语义：同名 Project 已存在时会复用已有目录与 manifest 信息，不会创建第二份 Project。

### 请求体字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | string | 是 | Project id，同时也是磁盘目录名。 |
| display_name | string | 否 | 可选展示名称。 |
| description | string | 否 | 可选项目说明。 |
| metadata | object | 否 | 附加元数据。 |

### 成功响应字段

- `project_id`
- `display_name`
- `description`
- `metadata`
- `registered_in_catalog`
- `storage_prefix`
- `summary`

### 调用后续

- 如果下一步进入训练链，可继续调用 datasets/imports 或 datasets/exports 相关接口。
- 如果下一步进入 workflow 编排链，可继续调用 workflows/node-catalog、template save 和 application save。

## GET /api/v1/projects

- 当前支持查询参数：
  - `include_summary`
  - `offset`
  - `limit`
- 返回当前主体可见的 Project 目录项数组。
- 响应体仍然是数组；分页信息通过 `x-offset`、`x-limit`、`x-total-count`、`x-has-more` 和 `x-next-offset` 返回。

### 单条目录项字段

- `project_id`
- `display_name`
- `description`
- `metadata`
- `registered_in_catalog`
- `storage_prefix`
- `summary`，仅在 `include_summary=true` 时内联返回

## GET /api/v1/projects/{project_id}

- 返回指定 Project 的目录信息，并内联当前 summary。
- 当前响应结构与 `GET /api/v1/projects?include_summary=true` 的单条元素保持一致。

## GET /api/v1/projects/{project_id}/summary

- 返回当前 Project 的工作台聚合快照。
- 当前接口是 `/ws/v1/projects/events` 的正式快照面对照面。

### 当前响应字段

- `project_id`
- `generated_at`
- `datasets.dataset_total`
- `imports.total`
- `imports.status_counts`
- `exports.total`
- `exports.status_counts`
- `training.total`
- `training.status_counts`
- `validation.total`
- `validation.status_counts`
- `evaluation.total`
- `evaluation.status_counts`
- `conversion.total`
- `conversion.status_counts`
- `inference.total`
- `inference.status_counts`
- `workflows.template_total`
- `workflows.application_total`
- `workflows.preview_run_total`
- `workflows.preview_run_state_counts`
- `workflows.workflow_run_total`
- `workflows.workflow_run_state_counts`
- `workflows.app_runtime_total`
- `workflows.app_runtime_observed_state_counts`
- `deployments.deployment_instance_total`
- `deployments.deployment_status_counts`

## GET /api/v1/projects/{project_id}/files/metadata

- 当前支持查询参数：
  - `object_key`
  - `storage_uri`，兼容字段，等价于 `object_key`
- 返回指定公开对象文件的元数据和稳定读取地址。

### 当前返回字段

- `project_id`
- `object_key`
- `file_name`
- `media_type`
- `size_bytes`
- `last_modified_at`
- `content_url`
- `download_url`

### 当前公开命名空间

- `projects/{project_id}/inputs/**`
- `projects/{project_id}/results/**`
- `projects/{project_id}/datasets/*/versions/**`
- `projects/{project_id}/datasets/*/exports/**`

## GET /api/v1/projects/{project_id}/files/content

- 当前支持查询参数：
  - `object_key`
  - `storage_uri`，兼容字段，等价于 `object_key`
  - `download`
- 用于图片预览、结果文件下载和其他公开对象内容直读。
- 当前允许访问的命名空间与 files/metadata 接口保持一致。

## 当前限制

- 当前不公开 Project rename、delete、archive 等独立主数据生命周期接口。
- 当前 `project_id` 一旦作为目录名进入后续数据链路，应视为稳定命名空间，不建议在外层随意重写。
- 当前 files 读取接口只开放公开命名空间，不作为任意 ObjectStore 浏览器使用。