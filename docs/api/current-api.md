# 当前公开 API 总览

## 文档目的

本文档用于汇总当前仓库已经公开的 REST API、WebSocket 入口、最小鉴权规则，以及 DatasetImport、DatasetExport 与 TaskRecord 之间的公开关系。

WebSocket 资源流的统一消息结构、控制事件和重连规则见 [docs/architecture/websocket-architecture.md](../architecture/websocket-architecture.md)。

本文档只描述当前真实实现，不展开未来接口规划。

## 统一鉴权输入

当前公开业务 REST 接口统一使用 Bearer token。仓库默认配置为 `mode=local`，并在空库首次启动时自动初始化默认本地用户和长期调用 token。

### Bearer token

- Authorization: Bearer <token>
- 默认配置使用 `mode=local`；Bearer token 可以是登录会话 access token，也可以是长期调用 user token
- 当本地用户表为空时，服务会在启动阶段自动初始化默认本地用户和长期调用 token；这组初始化数据由启动期初始化器写入数据库，不通过 runtime JSON 配置维护
- 业务接口、调试工具和集成调用应填写当前环境实际 Bearer token，不假定固定 token 值
- 需要区分 token 类型时，可通过 `/api/v1/system/me` 返回的 `auth_credential_kind` 和 `auth_provider_id` 判断

### 最小请求头

- Authorization: Bearer <token>

### 当前公开 scope

- datasets:read
- datasets:write
- auth:read
- auth:write
- models:read
- workflows:read
- workflows:write
- tasks:read
- tasks:write
- system:read

## 当前 auth 状态

- 当前本地用户、权限范围、session token、refresh token、长期调用 user token 和 `auth.events` 实时审计已经闭环。
- 在线 provider 当前只保留目录发现和后续扩展边界，不构成当前前端、工作站或外部集成接入的前提。

## 统一列表分页规则

当前公开的主要列表接口已经统一到 offset/limit + 响应头分页规则，保持 JSON 响应体仍然是原有数组。

- 查询参数：
  - offset：可选，默认 0
  - limit：可选，默认 100，最大 500
- 响应头：
  - x-offset：本次请求实际 offset
  - x-limit：本次请求实际 limit
  - x-total-count：当前筛选条件下的总条数
  - x-has-more：是否还有后续页，取值 true 或 false
  - x-next-offset：仅当 x-has-more=true 时返回
- 当前已经接入该规则的列表接口包括：
  - /api/v1/projects
  - /api/v1/workflows/projects/{project_id}/templates
  - /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions
  - /api/v1/workflows/projects/{project_id}/applications
  - /api/v1/workflows/execution-policies
  - /api/v1/workflows/preview-runs
  - /api/v1/workflows/app-runtimes
  - /api/v1/workflows/trigger-sources

## 当前公开 REST API

| 方法 | 路径 | scope | 说明 |
| --- | --- | --- | --- |
| GET | /api/v1/auth/providers | 无 | 返回当前公开可发现的账号 provider 目录；当前 local 是唯一完整可用的 provider，其他已配置在线 provider 只保留扩展边界。 |
| POST | /api/v1/auth/bootstrap-admin | 无 | 当本地用户表为空时初始化首个管理员，并返回登录会话 access token 与 refresh token。 |
| POST | /api/v1/auth/login | 无 | 使用指定 provider 的 password login 入口登录；当前只有 local 提供完整 password login。 |
| POST | /api/v1/auth/refresh | 无 | 使用 local 登录返回的 refresh token 刷新一组新的登录会话凭据。 |
| POST | /api/v1/auth/logout | 仅需主体 | 撤销当前 Bearer token 对应的本地登录会话；长期调用 token 不支持 logout。 |
| GET | /api/v1/auth/users | auth:read | 列出当前全部本地用户。 |
| POST | /api/v1/auth/users | auth:write | 创建一个本地用户，写入 scopes 与 project_ids，并默认签发一个长期调用 token。 |
| PATCH | /api/v1/auth/users/{user_id} | auth:write | 更新一个本地用户的展示名称、密码、scope、Project 可见性和启用状态。 |
| DELETE | /api/v1/auth/users/{user_id} | auth:write | 删除一个本地用户，并清理其登录会话、refresh token 与长期调用 token。 |
| POST | /api/v1/auth/users/{user_id}/reset-password | auth:write | 重置一个本地用户密码，并按请求撤销现有会话或长期调用 token。 |
| GET | /api/v1/auth/users/{user_id}/tokens | auth:read | 列出一个本地用户的长期调用 token 摘要。 |
| POST | /api/v1/auth/users/{user_id}/tokens | auth:write | 为一个本地用户创建长期调用 token，并返回一次性 token 明文。 |
| DELETE | /api/v1/auth/users/{user_id}/tokens/{token_id} | auth:write | 撤销一个本地用户的长期调用 token。 |
| GET | /api/v1/system/health | 无 | 返回最小健康状态和 request_id。 |
| GET | /api/v1/system/me | 仅需主体 | 返回当前主体、project_ids 和 scopes。 |
| GET | /api/v1/system/database | system:read | 返回数据库连通性检查结果。 |
| GET | /api/v1/projects | workflows:read + models:read | 列出当前主体可见的 Project 目录项；支持 include_summary、offset、limit 和统一分页响应头。 |
| GET | /api/v1/projects/{project_id} | workflows:read + models:read | 读取一个 Project 的目录信息和当前 summary。 |
| GET | /api/v1/projects/{project_id}/summary | workflows:read + models:read | 读取一个 Project 当前工作台可用的聚合摘要。 |
| GET | /api/v1/projects/{project_id}/files/metadata | workflows:read + models:read | 读取一个 Project 公开文件命名空间中的对象元数据、content_url 和 download_url；当前只开放 inputs、results 和 datasets 下的 versions、exports。 |
| GET | /api/v1/projects/{project_id}/files/content | workflows:read + models:read | 直接输出一个 Project 公开文件命名空间中的对象文件内容，适用于图片预览和结果文件下载。 |
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
| POST | /api/v1/models/yolox/conversion-tasks | models:read + tasks:write | 以训练产出的 source ModelVersion 创建 YOLOX conversion 任务。 |
| GET | /api/v1/models/yolox/conversion-tasks | tasks:read | 按 Project、来源版本和状态列出 YOLOX conversion 任务。 |
| GET | /api/v1/models/yolox/conversion-tasks/{task_id} | tasks:read | 查询单条 YOLOX conversion 任务详情和事件流。 |
| GET | /api/v1/models/yolox/conversion-tasks/{task_id}/result | tasks:read | 查询 YOLOX conversion 结果文件状态与当前转换摘要。 |
| GET | /api/v1/models/yolox/training-tasks | tasks:read | 按 Project、DatasetExport 边界和状态列出 YOLOX 训练任务。 |
| GET | /api/v1/models/yolox/training-tasks/{task_id} | tasks:read | 查询单条 YOLOX 训练任务详情和事件流。 |
| POST | /api/v1/models/yolox/training-tasks/{task_id}/save | tasks:write | 为 running 的 YOLOX 训练任务登记一次手动保存请求。 |
| POST | /api/v1/models/yolox/training-tasks/{task_id}/pause | tasks:write | 为 running 的 YOLOX 训练任务请求暂停，并在下一轮边界先保存 latest checkpoint。 |
| POST | /api/v1/models/yolox/training-tasks/{task_id}/resume | tasks:write | 把 paused 的 YOLOX 训练任务重新入队，并基于 latest checkpoint 恢复训练。 |
| POST | /api/v1/models/yolox/training-tasks/{task_id}/register-model-version | tasks:write + models:write | 调试时手动重登记当前 latest checkpoint 对应的固定 latest ModelVersion，并回写到训练详情。 |
| GET | /api/v1/workflows/node-catalog | workflows:read | 读取 workflow 节点目录快照，并支持按分类、节点包、payload 类型和关键词过滤。 |
| POST | /api/v1/workflows/templates/validate | workflows:read | 校验一份 workflow template。 |
| GET | /api/v1/workflows/projects/{project_id}/templates | workflows:read | 列出指定 Project 下的 workflow template 摘要；支持 offset、limit 和统一分页响应头。 |
| GET | /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions | workflows:read | 列出指定 workflow template 的全部版本摘要；支持 offset、limit 和统一分页响应头。 |
| PUT | /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions/{template_version} | workflows:write | 保存一份 workflow template JSON。 |
| GET | /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions/{template_version} | workflows:read | 读取一份已保存的 workflow template JSON。 |
| GET | /api/v1/workflows/projects/{project_id}/templates/{template_id}/latest | workflows:read | 读取指定 workflow template 当前可见的最新版本。 |
| POST | /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions/{template_version}/copy | workflows:write | 复制一份已保存的 workflow template 版本。 |
| DELETE | /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions/{template_version} | workflows:write | 删除一份已保存的 workflow template 版本。 |
| POST | /api/v1/workflows/applications/validate | workflows:read | 校验一份 FlowApplication 与 template 绑定关系。 |
| GET | /api/v1/workflows/projects/{project_id}/applications | workflows:read | 列出指定 Project 下的 FlowApplication 摘要；支持 offset、limit 和统一分页响应头。 |
| PUT | /api/v1/workflows/projects/{project_id}/applications/{application_id} | workflows:write | 保存一份 FlowApplication JSON。 |
| GET | /api/v1/workflows/projects/{project_id}/applications/{application_id} | workflows:read | 读取一份已保存的 FlowApplication JSON。 |
| POST | /api/v1/workflows/projects/{project_id}/applications/{application_id}/copy | workflows:write | 复制一份已保存的 FlowApplication。 |
| DELETE | /api/v1/workflows/projects/{project_id}/applications/{application_id} | workflows:write | 删除一份已保存的 FlowApplication。 |
| POST | /api/v1/workflows/execution-policies | workflows:write | 创建一条 WorkflowExecutionPolicy。 |
| GET | /api/v1/workflows/execution-policies | workflows:read | 按 Project 列出 WorkflowExecutionPolicy；支持 offset、limit 和统一分页响应头。 |
| GET | /api/v1/workflows/execution-policies/{execution_policy_id} | workflows:read | 读取一条 WorkflowExecutionPolicy。 |
| POST | /api/v1/workflows/preview-runs | workflows:write | 创建一条 WorkflowPreviewRun；支持 sync/async wait_mode。 |
| GET | /api/v1/workflows/preview-runs | workflows:read | 按 Project 列出 WorkflowPreviewRun，并支持状态、创建时间、offset、limit 和统一分页响应头。 |
| GET | /api/v1/workflows/preview-runs/{preview_run_id} | workflows:read | 读取一条 WorkflowPreviewRun。 |
| GET | /api/v1/workflows/preview-runs/{preview_run_id}/events | workflows:read | 读取一条 WorkflowPreviewRun 的执行事件；支持 after_sequence 和 limit。 |
| POST | /api/v1/workflows/preview-runs/{preview_run_id}/cancel | workflows:write | 取消一条 queued 或 running 的 WorkflowPreviewRun。 |
| DELETE | /api/v1/workflows/preview-runs/{preview_run_id} | workflows:write | 删除一条 WorkflowPreviewRun 和对应 snapshot 目录。 |
| POST | /api/v1/workflows/app-runtimes | workflows:write | 创建一条 WorkflowAppRuntime。 |
| GET | /api/v1/workflows/app-runtimes | workflows:read | 按 Project 列出 WorkflowAppRuntime；支持 offset、limit 和统一分页响应头。 |
| GET | /api/v1/workflows/app-runtimes/{workflow_runtime_id} | workflows:read | 读取一条 WorkflowAppRuntime。 |
| DELETE | /api/v1/workflows/app-runtimes/{workflow_runtime_id} | workflows:write | 删除一条 WorkflowAppRuntime，并清理对应 snapshot 目录。 |
| POST | /api/v1/workflows/app-runtimes/{workflow_runtime_id}/start | workflows:write | 启动单实例 runtime worker。 |
| POST | /api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop | workflows:write | 停止单实例 runtime worker。 |
| POST | /api/v1/workflows/app-runtimes/{workflow_runtime_id}/restart | workflows:write | 重启单实例 runtime worker，并重新加载固定 snapshot。 |
| GET | /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events | workflows:read | 读取一条 WorkflowAppRuntime 的事件列表；支持 after_sequence 和 limit。 |
| GET | /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health | workflows:read | 查询 runtime 当前健康状态。 |
| GET | /api/v1/workflows/app-runtimes/{workflow_runtime_id}/instances | workflows:read | 列出 runtime 当前可观测的 instance 摘要。 |
| POST | /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs | workflows:write | 为已启动 runtime 创建一条异步 WorkflowRun。 |
| POST | /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs/upload | workflows:write | 通过 multipart/form-data 为已启动 runtime 创建一条异步 WorkflowRun；当前只支持 dataset-package.v1 文件输入。 |
| POST | /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke | workflows:write | 通过 runtime 发起一次同步调用。 |
| POST | /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload | workflows:write | 通过 multipart/form-data 发起一次同步调用；当前只支持 dataset-package.v1 文件输入。 |
| POST | /api/v1/workflows/trigger-sources | workflows:write | 创建一条 WorkflowTriggerSource 管理资源。 |
| GET | /api/v1/workflows/trigger-sources | workflows:read | 按 Project 列出 WorkflowTriggerSource；支持 offset、limit 和统一分页响应头。 |
| GET | /api/v1/workflows/trigger-sources/{trigger_source_id} | workflows:read | 读取一条 WorkflowTriggerSource。 |
| DELETE | /api/v1/workflows/trigger-sources/{trigger_source_id} | workflows:write | 删除一条 WorkflowTriggerSource；已接入 adapter 时会先停止监听。 |
| POST | /api/v1/workflows/trigger-sources/{trigger_source_id}/enable | workflows:write | 启用一条 WorkflowTriggerSource；当前要求绑定的 runtime 已处于 running。 |
| POST | /api/v1/workflows/trigger-sources/{trigger_source_id}/disable | workflows:write | 停用一条 WorkflowTriggerSource。 |
| GET | /api/v1/workflows/trigger-sources/{trigger_source_id}/health | workflows:read | 读取一条 WorkflowTriggerSource 的健康摘要。 |
| GET | /api/v1/workflows/runs/{workflow_run_id} | workflows:read | 读取一条 WorkflowRun。 |
| GET | /api/v1/workflows/runs/{workflow_run_id}/events | workflows:read | 读取一条 WorkflowRun 的事件列表；支持 after_sequence 和 limit。 |
| POST | /api/v1/workflows/runs/{workflow_run_id}/cancel | workflows:write | 取消一条 queued 或 running 的异步 WorkflowRun。 |
| GET | /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/events | models:read | 读取一条 deployment 生命周期事件列表；支持 after_sequence、runtime_mode 和 limit。 |
| POST | /api/v1/tasks | tasks:write | 创建公开任务记录，立即返回任务详情。 |
| GET | /api/v1/tasks | tasks:read | 按公开筛选字段查询任务列表。 |
| GET | /api/v1/tasks/{task_id} | tasks:read | 查询单条任务详情；默认同时返回 events。 |
| GET | /api/v1/tasks/{task_id}/events | tasks:read | 按任务查询事件流快照。 |
| POST | /api/v1/tasks/{task_id}/cancel | tasks:write | 取消一条尚未结束的任务。 |

## auth 资源组

- 当前本地用户与权限管理已经作为现阶段稳定基线收敛完成。
- 在线 provider 当前只保留目录发现与后续扩展边界。

### GET /api/v1/auth/providers

- 返回当前公开可发现的账号 provider 目录
- 当前应把 `provider_id=local` 视为唯一完整可用的 provider
- 当前目录项字段：provider_id、provider_kind、display_name、enabled、login_mode、supports_password_login、supports_refresh、supports_bootstrap_admin、supports_user_management、supports_long_lived_tokens、issuer_url、metadata

### POST /api/v1/auth/bootstrap-admin

- 当本地用户表为空时可调用一次
- 创建首个本地管理员，默认授予 `*` scope 和不受限的 Project 可见性
- 返回字段：session_id、access_token、token_type、expires_at、refresh_token、refresh_expires_at、user

### POST /api/v1/auth/login

- 使用 password login 入口登录指定 provider
- 当前支持请求体字段：provider_id、username、password
- 返回字段：session_id、access_token、token_type、expires_at、refresh_token、refresh_expires_at、user

### POST /api/v1/auth/refresh

- 使用 local 登录返回的 refresh token 刷新一组新的登录会话凭据
- 返回字段：session_id、access_token、token_type、expires_at、refresh_token、refresh_expires_at、user

### POST /api/v1/auth/logout

- 需要 Bearer token 主体
- 只撤销当前本地 access token 对应的会话
- 只接受登录会话 token，不接受长期调用 token

### GET /api/v1/auth/users

- 需要 auth:read
- 返回当前全部本地用户列表

### POST /api/v1/auth/users

- 需要 auth:write
- 可写字段：username、password、display_name、principal_type、project_ids、scopes、metadata、initial_user_token
- 默认会返回 `user` 和 `initial_user_token`

### PATCH /api/v1/auth/users/{user_id}

- 需要 auth:write
- 可更新字段：display_name、password、project_ids、scopes、is_active、metadata

### DELETE /api/v1/auth/users/{user_id}

- 需要 auth:write
- 删除用户时会级联清理其登录会话、refresh token 和长期调用 token

### POST /api/v1/auth/users/{user_id}/reset-password

- 需要 auth:write
- 可写字段：new_password、revoke_sessions、revoke_user_tokens

### GET /api/v1/auth/users/{user_id}/tokens

- 需要 auth:read
- 返回指定用户的长期调用 token 摘要列表

### POST /api/v1/auth/users/{user_id}/tokens

- 需要 auth:write
- 可写字段：token_name、ttl_hours、expires_at、metadata
- 返回新 token 的一次性明文值

### DELETE /api/v1/auth/users/{user_id}/tokens/{token_id}

- 需要 auth:write
- 撤销指定长期调用 token

## system 资源组

### GET /api/v1/system/health

- 无需鉴权 scope
- 返回字段：status、request_id

### GET /api/v1/system/me

- 需要主体请求头
- 返回字段：principal_id、principal_type、project_ids、scopes、username、display_name、auth_source、auth_provider_id、auth_provider_kind、auth_credential_kind、auth_credential_id、auth_session_id、auth_token_id、auth_token_name、auth_mode

### GET /api/v1/system/database

- 需要 system:read
- 返回字段：status、database、scalar、principal_id、request_id

## projects 资源组

### GET /api/v1/projects

- 需要 workflows:read 和 models:read
- 当前支持查询参数：
  - include_summary
  - offset
  - limit
- 返回当前主体可见的 Project 目录项列表
- 响应体仍然是数组；分页信息通过统一分页响应头返回

### GET /api/v1/projects/{project_id}

- 需要 workflows:read 和 models:read
- 返回字段包括：
  - project_id
  - display_name
  - description
  - metadata
  - registered_in_catalog
  - storage_prefix
  - summary

### GET /api/v1/projects/{project_id}/summary

- 需要 workflows:read 和 models:read
- 返回字段：
  - project_id
  - generated_at
  - workflows.template_total
  - workflows.application_total
  - workflows.preview_run_total
  - workflows.preview_run_state_counts
  - workflows.workflow_run_total
  - workflows.workflow_run_state_counts
  - workflows.app_runtime_total
  - workflows.app_runtime_observed_state_counts
  - deployments.deployment_instance_total
  - deployments.deployment_status_counts
- 该接口是项目级工作台和 `/ws/v1/projects/events` 的正式快照面

### GET /api/v1/projects/{project_id}/files/metadata

- 需要 workflows:read 和 models:read
- 当前支持查询参数：
  - object_key
  - storage_uri，兼容字段；等价于 object_key
- object_key 只能指向当前 Project 的公开文件命名空间
- 当前允许的命名空间包括：
  - projects/{project_id}/inputs/**
  - projects/{project_id}/results/**
  - projects/{project_id}/datasets/*/versions/**
  - projects/{project_id}/datasets/*/exports/**
- 当同时提供 object_key 和 storage_uri 时，两者必须一致
- 返回字段包括：
  - project_id
  - object_key
  - file_name
  - media_type
  - size_bytes
  - last_modified_at
  - content_url
  - download_url

### GET /api/v1/projects/{project_id}/files/content

- 需要 workflows:read 和 models:read
- 当前支持查询参数：
  - object_key
  - storage_uri，兼容字段；等价于 object_key
  - download
- object_key 只能指向当前 Project 的公开文件命名空间
- 当前允许的命名空间与 metadata 接口保持一致
- 当前适用于图片预览和结果文件下载

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

### POST /api/v1/models/yolox/conversion-tasks/onnx

- 需要同时具备 models:read 和 tasks:write
- 转换链顺序图与常见失败分支见 [docs/architecture/execution-sequences.md](../architecture/execution-sequences.md)。
- 当前请求体允许显式指定：
  - project_id
  - source_model_version_id
  - runtime_profile_id
  - extra_options
  - display_name
- 当前接口固定创建 `onnx` 目标的 conversion task，不再通过同一个创建接口混合多种输出格式
- 当前实现会先解析来源 ModelVersion 的 checkpoint、labels 和 input_size，再按 conversion planner 固化步骤图谱并提交到 `yolox-conversions` 队列
- 当前已真实可执行目标支持：
  - onnx
  - onnx-optimized
  - openvino-ir
  - tensorrt-engine
- 当前 `openvino-ir` 构建链会先产出 optimized ONNX，再通过隔离子进程执行 OpenVINO `convert_model/save_model` 写出 xml/bin 产物
- 当前 `tensorrt-engine` 构建链会先产出 `onnx` 与 `onnx-optimized`，再通过 TensorRT Python API 构建 engine，并在 `ModelBuild.metadata` 中回写 `build_precision` 与 `tensorrt_version`
- 当前响应会返回：
  - task_id
  - status
  - queue_name
  - queue_task_id
  - source_model_version_id
  - target_formats

### POST /api/v1/models/yolox/conversion-tasks/onnx-optimized

- 需要同时具备 models:read 和 tasks:write
- 当前请求体字段与 `onnx` 创建接口一致
- 当前接口固定创建 `onnx-optimized` 目标的 conversion task，内部仍会先产出中间 `onnx`

### POST /api/v1/models/yolox/conversion-tasks/openvino-ir-fp32

- 需要同时具备 models:read 和 tasks:write
- 当前请求体字段与 `onnx` 创建接口一致
- 当前接口固定创建 `openvino-ir` 目标的 conversion task，并把 OpenVINO IR 构建策略固化为 `fp32`
- 当前接口会先产出 `onnx` 与 `onnx-optimized`，再生成未压缩权重的 xml/bin 形式 OpenVINO IR

### POST /api/v1/models/yolox/conversion-tasks/openvino-ir-fp16

- 需要同时具备 models:read 和 tasks:write
- 当前请求体字段与 `onnx` 创建接口一致
- 当前接口固定创建 `openvino-ir` 目标的 conversion task，并把 OpenVINO IR 构建策略固化为 `fp16`
- 当前接口会先产出 `onnx` 与 `onnx-optimized`，再生成压缩为 fp16 权重的 xml/bin 形式 OpenVINO IR

### POST /api/v1/models/yolox/conversion-tasks/tensorrt-engine-fp32

- 需要同时具备 models:read 和 tasks:write
- 当前请求体字段与 `onnx` 创建接口一致
- 当前接口固定创建 `tensorrt-engine` 目标的 conversion task，并把 TensorRT engine 构建策略固化为 `fp32`
- 当前接口会先产出 `onnx` 与 `onnx-optimized`，再通过 TensorRT Python API 生成 fp32 engine

### POST /api/v1/models/yolox/conversion-tasks/tensorrt-engine-fp16

- 需要同时具备 models:read 和 tasks:write
- 当前请求体字段与 `onnx` 创建接口一致
- 当前接口固定创建 `tensorrt-engine` 目标的 conversion task，并把 TensorRT engine 构建策略固化为 `fp16`
- 当前接口会先产出 `onnx` 与 `onnx-optimized`，再在 TensorRT builder 上打开 fp16 flag 生成 engine

### GET /api/v1/models/yolox/conversion-tasks

- 需要 tasks:read
- 当前支持的查询参数：
  - project_id
  - state
  - created_by
  - source_model_version_id
  - target_format
  - limit
- 当前列表响应会同时公开：
  - task_id
  - state
  - source_model_version_id
  - target_formats
  - runtime_profile_id
  - output_object_prefix
  - plan_object_key
  - report_object_key
  - requested_target_formats
  - produced_formats
  - builds
  - report_summary

### GET /api/v1/models/yolox/conversion-tasks/{task_id}

- 需要 tasks:read
- 默认 include_events=true
- 返回单条 YOLOX conversion 任务详情，包括 task_spec、events、builds 和 report_summary
- 当前 progress 会在执行期回写 `stage` 和 `percent`

### GET /api/v1/models/yolox/conversion-tasks/{task_id}/result

- 需要 tasks:read
- 返回当前转换任务最新的 conversion-report.json 内容
- 当前响应统一为 `file_status`、`task_state`、`object_key` 和 `payload`
- 当结果文件尚未生成时，接口返回 `file_status=pending` 和空 `payload`
- 当任务已经结束但结果文件缺失时，接口返回 404

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
  - runtime_precision
  - device_name
  - instance_count
  - display_name
  - metadata
- 当前 `metadata.deployment_process` 支持下面这些可选覆盖字段：
  - warmup_dummy_inference_count：覆盖默认 warmup 的 dummy infer 次数
  - warmup_dummy_image_size：覆盖 dummy infer 使用的最小输入图片尺寸，格式为 `[width, height]`
  - keep_warm_enabled：启用 deployment 子进程内的 keep-warm 后台线程
  - keep_warm_interval_seconds：覆盖 keep-warm 连续 dummy infer 的最小间隔秒数
  - tensorrt_pinned_output_buffer_enabled：覆盖 TensorRT 输出 host buffer 是否启用 pinned memory
  - tensorrt_pinned_output_buffer_max_bytes：覆盖 TensorRT 输出 host buffer 允许使用 pinned memory 的最大字节数
- 当前最小实现允许直接绑定训练产出的 `ModelVersion`，也允许绑定 `ModelBuild`；如果同时提供 `model_build_id` 和 `model_version_id`，两者必须指向同一来源版本
- 当前 `ModelVersion` 默认走 `pytorch`；当前 `ModelBuild` 已支持 `onnx` / `onnx-optimized` / `openvino-ir` / `tensorrt-engine` 绑定，并自动解析为 `onnxruntime`、`openvino` 或 `tensorrt`
- 当前 create 会在提交阶段校验 checkpoint 和 labels 的本地可读性
- 当前运行方式矩阵已经显式公开：`pytorch fp32/fp16 cpu/cuda`、`onnxruntime fp32 cpu`、`openvino fp32 auto/cpu/gpu/npu + fp16 gpu/npu`、`tensorrt fp32/fp16 cuda`
- 当前 `tensorrt` deployment 只接受 `device_name=cuda|cuda:0`，create 响应会统一归一化为 `cuda:0`；`runtime_precision` 必须与 engine `build_precision` 一致
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
  - runtime_precision
  - runtime_execution_mode
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

### GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/events

- 需要 models:read
- 当前支持的查询参数：
  - runtime_mode，可选，支持 `sync`、`async`
  - after_sequence
  - limit
- 返回 deployment 进程历史事件列表
- 当前稳定事件类型覆盖 start、stop、warmup、health、crash、restart 等过程事件

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
  - restart_count_rollover_count
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
- 当前 warmup 会先加载全部实例会话，再按默认配置或 `metadata.deployment_process` 覆盖值执行 N 次真实 dummy infer
- 当 `metadata.deployment_process.keep_warm_enabled=true` 时，warmup 完成后会激活 keep-warm 后台线程；首次真实推理成功后也会激活同一机制
- 当前响应会返回：
  - deployment_instance_id
  - display_name
  - runtime_mode
  - desired_state
  - process_state
  - process_id
  - auto_restart
  - restart_count
  - restart_count_rollover_count
  - last_exit_code
  - last_error
  - instance_count
  - healthy_instance_count
  - warmed_instance_count
  - pinned_output_total_bytes
  - instances[].instance_id
  - instances[].healthy
  - instances[].warmed
  - instances[].busy
  - instances[].last_error
  - keep_warm.enabled
  - keep_warm.activated
  - keep_warm.paused
  - keep_warm.idle
  - keep_warm.interval_seconds
  - keep_warm.yield_timeout_seconds
  - keep_warm.success_count
  - keep_warm.success_count_rollover_count
  - keep_warm.error_count
  - keep_warm.error_count_rollover_count
  - keep_warm.last_error

### GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/health

- 需要 models:read
- 返回指定 deployment 当前同步推理子进程及实例池的详细健康视图
- 当前响应会额外返回 keep-warm 状态：
  - pinned_output_total_bytes：当前所有已加载 session 的 pinned output host buffer 总字节数
  - restart_count：当前 restart 计数的安全整数窗口值
  - restart_count_rollover_count：restart_count 已发生的 rollover 次数；当 restart_count 达到 JavaScript 安全整数上限后，下一次自增会把 restart_count 置为 1，并把这个字段加 1
  - keep_warm.enabled：当前 deployment 是否启用 keep-warm
  - keep_warm.activated：keep-warm 是否已经被 warmup 或真实推理激活
  - keep_warm.paused：keep-warm 当前是否因为控制面动作或真实请求而暂停
  - keep_warm.idle：当前是否没有 keep-warm dummy infer 正在执行
  - keep_warm.interval_seconds：当前生效的 keep-warm 间隔秒数
  - keep_warm.yield_timeout_seconds：真实请求等待 keep-warm 让出的最长秒数
  - keep_warm.success_count：keep-warm 成功完成的 dummy infer 当前安全整数窗口值
  - keep_warm.success_count_rollover_count：success_count 已发生的 rollover 次数；当 success_count 达到 JavaScript 安全整数上限后，下一次成功会把 success_count 置为 1，并把这个字段加 1
  - keep_warm.error_count：keep-warm 失败次数当前安全整数窗口值
  - keep_warm.error_count_rollover_count：error_count 已发生的 rollover 次数；当 error_count 达到 JavaScript 安全整数上限后，下一次失败会把 error_count 置为 1，并把这个字段加 1
  - keep_warm.last_error：最近一次 keep-warm 失败错误

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/reset

- 需要 models:read 和 models:write
- 重置指定 deployment 的同步推理实例池
- 如果同步推理子进程尚未启动，接口返回 `invalid_request`
- 当前响应会返回与 `sync/health` 相同的详细健康字段，重点包括：
  - desired_state
  - process_state
  - process_id
  - restart_count
  - restart_count_rollover_count
  - healthy_instance_count
  - warmed_instance_count
  - pinned_output_total_bytes
  - instances[].instance_id
  - instances[].healthy
  - instances[].warmed
  - instances[].busy
  - instances[].last_error
  - keep_warm.enabled
  - keep_warm.activated
  - keep_warm.paused
  - keep_warm.idle
  - keep_warm.interval_seconds
  - keep_warm.yield_timeout_seconds
  - keep_warm.success_count
  - keep_warm.success_count_rollover_count
  - keep_warm.error_count
  - keep_warm.error_count_rollover_count
  - keep_warm.last_error

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
- 当前 warmup 会先加载全部实例会话，再按默认配置或 `metadata.deployment_process` 覆盖值执行 N 次真实 dummy infer
- 当 `metadata.deployment_process.keep_warm_enabled=true` 时，warmup 完成后会激活 keep-warm 后台线程；首次真实推理成功后也会激活同一机制
- 当前响应会返回与 sync/warmup 相同的 keep_warm 状态字段，以及 `pinned_output_total_bytes`，可直接判断 keep-warm 是否启用、是否激活，以及当前已加载 session 持有的 pinned output 总量

### GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/health

- 需要 models:read
- 返回指定 deployment 当前异步推理子进程及实例池的详细健康视图
- 当前响应会额外返回与 sync/health 相同的 keep_warm 状态字段和 `pinned_output_total_bytes`，可直接判断 keep-warm 是否启用、是否激活，以及当前已加载 session 持有的 pinned output 总量

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/reset

- 需要 models:read 和 models:write
- 重置指定 deployment 的异步推理实例池
- 如果异步推理子进程尚未启动，接口返回 `invalid_request`
- 当前响应会返回与 `async/health` 相同的详细健康字段，重点包括：
  - desired_state
  - process_state
  - process_id
  - restart_count
  - restart_count_rollover_count
  - healthy_instance_count
  - warmed_instance_count
  - pinned_output_total_bytes
  - instances[].instance_id
  - instances[].healthy
  - instances[].warmed
  - instances[].busy
  - instances[].last_error
  - keep_warm.enabled
  - keep_warm.activated
  - keep_warm.paused
  - keep_warm.idle
  - keep_warm.interval_seconds
  - keep_warm.yield_timeout_seconds
  - keep_warm.success_count
  - keep_warm.success_count_rollover_count
  - keep_warm.error_count
  - keep_warm.error_count_rollover_count
  - keep_warm.last_error

### POST /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/infer

- 需要 models:read
- 这是同步直返推理接口；当前只使用 deployment 的同步推理子进程，并按 instance 简单轮转执行
- 部署推理链顺序图与常见失败分支见 [docs/architecture/execution-sequences.md](../architecture/execution-sequences.md)。
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
- 当前当 deployment 绑定 `tensorrt-engine` ModelBuild 时，worker 会通过 async deployment 子进程真实加载 TensorRT engine，并在结果 `runtime_session_info` 中回写 `runtime_execution_mode` 与 `compiled_runtime_precision`
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
- 训练链顺序图与常见失败分支见 [docs/architecture/execution-sequences.md](../architecture/execution-sequences.md)。
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
- 当前 Swagger/OpenAPI 已把 training create 的 extra_options 展开为具名字段，公开键包括 seed、num_workers、device、max_labels、flip_prob、hsv_prob、mosaic_prob、mixup_prob、enable_mixup、multiscale_range、ema、warmup_epochs、no_aug_epochs、min_lr_ratio、evaluation_confidence_threshold、evaluation_nms_threshold 等。
- 当前 extra_options 默认关闭 flip、hsv、mosaic、mixup 和多尺度训练；EMA 默认保持启用。完整字段说明见 [docs/api/yolox-training.md](yolox-training.md)。
- 当前没有可用 GPU 时会回退到 CPU 训练，用于最小硬件支持和开发环境验证；只是速度会明显变慢。
- 当前 `save`、`pause` 都是“请求登记后等待下一个 epoch 边界生效”，不是同步完成动作。
- 当前 `resume` 会先把任务切回 `queued` 并重新入队；checkpoint 读取失败或配置不一致这类问题可能在后续 worker 执行阶段才把任务切成 `failed`。
- 当前训练详情响应已经正式公开 `available_actions` 和 `control_status`；前端可以直接按这两个字段收口按钮与控制态判断。
- 前端如果轮询训练详情，建议显式传 `include_events=false`；日志流优先使用 `/ws/v1/tasks/events?task_id=...`。
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

## workflow 资源组

当前 workflow runtime 公开接口描述的是 HTTP 控制面下的正式执行路径。WorkflowTriggerSource 第一阶段已经提供管理控制面，并已接入 ZeroMQ adapter 的 REST 启停和启动恢复；04/05 继续用于 HTTP JSON invoke，06/07 单独用于同 app HTTP base64 + ZeroMQ image-ref 双入口调试。TriggerSource 只提交协议原生输入，不负责跨 payload type 转换；如果同一 app 需要同时接 HTTP base64 和 ZeroMQ image-ref，应通过图里的显式 binding 或转换节点处理。后续 PLC、MQTT、gRPC、IO 变化等协议 adapter 仍统一映射到 WorkflowRun，触发入口说明见 [docs/api/workflow-trigger-sources.md](workflow-trigger-sources.md)。

### POST /api/v1/workflows/templates/validate

- Content-Type：application/json
- 需要 workflows:read
- 请求体字段：
  - template
- 返回字段：
  - valid
  - template_id
  - template_version
  - node_count
  - edge_count
  - template_input_ids
  - template_output_ids
  - referenced_node_type_ids

### PUT /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions/{template_version}

- Content-Type：application/json
- 需要 workflows:write
- 路径参数中的 template_id 与 template_version 必须和请求体中的 template 一致
- 成功响应会同时返回：
  - project_id
  - object_key
  - template
  - 校验摘要字段

### GET /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions/{template_version}

- 需要 workflows:read
- 返回已保存 template 的 object_key 与完整 template JSON

### POST /api/v1/workflows/applications/validate

- Content-Type：application/json
- 需要 workflows:read
- 请求体字段：
  - project_id
  - application
  - template，可选
- 当 template 未提供时，当前实现会按 application.template_ref 读取已保存 template

### PUT /api/v1/workflows/projects/{project_id}/applications/{application_id}

- Content-Type：application/json
- 需要 workflows:write
- 路径参数中的 application_id 必须和请求体中的 application.application_id 一致
- 保存时会把 application.template_ref.source_uri 规范化为真实 template object key
- 成功响应会同时返回：
  - project_id
  - object_key
  - application
  - 校验摘要字段

### GET /api/v1/workflows/projects/{project_id}/applications/{application_id}

- 需要 workflows:read
- 返回已保存 application 的 object_key 与完整 application JSON

### POST /api/v1/workflows/preview-runs

- Content-Type：application/json
- 需要 workflows:write
- 请求体字段：
  - project_id
  - application_ref，可选；当前至少需要 application_ref 或 inline application + template 其中一组
  - application，可选
  - template，可选
  - input_bindings
  - execution_metadata
  - timeout_seconds
- 成功状态码：201 Created
- 当前响应会同时返回：
  - preview_run_id
  - state
  - application_snapshot_object_key
  - template_snapshot_object_key
  - outputs
  - template_outputs
  - node_records
  - error_message

### GET /api/v1/workflows/preview-runs

- 需要 workflows:read
- 当前必须显式提供查询参数：
  - project_id
- 当前支持的可选查询参数：
  - state
  - created_from
  - created_to
  - offset
  - limit
- 响应体仍然是数组；分页信息通过统一分页响应头返回

### GET /api/v1/workflows/execution-policies

- 需要 workflows:read
- 当前必须显式提供查询参数：
  - project_id
  - offset，可选
  - limit，可选
- 响应体仍然是数组；分页信息通过统一分页响应头返回

### GET /api/v1/workflows/preview-runs/{preview_run_id}

- 需要 workflows:read
- 返回单条 WorkflowPreviewRun 当前快照和执行结果

### POST /api/v1/workflows/app-runtimes

- Content-Type：application/json
- 需要 workflows:write
- 请求体字段：
  - project_id
  - application_id
  - display_name，可选
  - request_timeout_seconds，可选
  - heartbeat_interval_seconds，可选
  - heartbeat_timeout_seconds，可选，且必须大于 heartbeat_interval_seconds
  - metadata，可选
- 成功状态码：201 Created
- 当前响应会同时返回：
  - workflow_runtime_id
  - desired_state
  - observed_state
  - application_snapshot_object_key
  - template_snapshot_object_key
  - request_timeout_seconds
  - heartbeat_interval_seconds
  - heartbeat_timeout_seconds
  - health_summary

### GET /api/v1/workflows/app-runtimes

- 需要 workflows:read
- 当前必须显式提供查询参数：
  - project_id
  - offset，可选
  - limit，可选
- 响应体仍然是数组；分页信息通过统一分页响应头返回

### GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}

- 需要 workflows:read
- 返回单条 WorkflowAppRuntime 的快照来源、期望状态、观察状态和健康摘要

### GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events

- 需要 workflows:read
- 当前支持的查询参数：
  - after_sequence
  - limit
- 返回 WorkflowAppRuntime 历史事件列表
- 当前稳定事件类型包括：
  - runtime.created
  - runtime.started
  - runtime.stopped
  - runtime.restarted
  - runtime.heartbeat
  - runtime.heartbeat_timed_out
  - runtime.heartbeat_recovered
  - runtime.failed

### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/start

- 需要 workflows:write
- 成功后返回更新后的 WorkflowAppRuntime

### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop

- 需要 workflows:write
- 成功后返回更新后的 WorkflowAppRuntime

### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/restart

- 需要 workflows:write
- 成功后返回更新后的 WorkflowAppRuntime
- 当前语义固定为 stop 当前单实例 worker，再重新加载同一组 application/template snapshot

### GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health

- 需要 workflows:read
- 返回当前 worker 观测到的 runtime 状态，包括 heartbeat_at、worker_process_id 和 loaded_snapshot_fingerprint

### GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/instances

- 需要 workflows:read
- 返回当前 runtime 下面可观测的 instance 摘要列表
- 当前单实例模型下，running 或 failed 且 worker 仍存活时通常返回 1 条；stopped 或已清理 worker 返回空列表
- 当前列表项稳定字段包括：
  - instance_id
  - state
  - process_id
  - current_run_id
  - started_at
  - heartbeat_at
  - loaded_snapshot_fingerprint
  - last_error
  - health_summary

### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke

- Content-Type：application/json
- 需要 workflows:write
- 仅支持已经处于 running 的 WorkflowAppRuntime
- 请求体字段：
  - input_bindings
  - execution_metadata
  - timeout_seconds，可选
- 当前响应会同时返回：
  - workflow_run_id
  - state
  - assigned_process_id
  - outputs
  - template_outputs
  - node_records
  - error_message
  - metadata

### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload

- Content-Type：multipart/form-data
- 需要 workflows:write
- 仅支持已经处于 running 的 WorkflowAppRuntime
- 当前 multipart 保留字段：
  - input_bindings_json，可选
  - execution_metadata_json，可选
  - timeout_seconds，可选
- 其他文件字段名必须等于 application 的 input binding_id
- 当前 multipart 文件上传只支持 `dataset-package.v1` 输入绑定，不支持把图片文件直接作为 `request_image` 上传
- 当前响应与 JSON `invoke` 一样返回完整 WorkflowRun 合同

### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs

- Content-Type：application/json
- 需要 workflows:write
- 仅支持已经处于 running 的 WorkflowAppRuntime
- 请求体字段：
  - input_bindings
  - execution_metadata
  - timeout_seconds，可选
- 当前响应会同时返回：
  - workflow_run_id
  - state
  - requested_timeout_seconds
  - input_payload
  - metadata

### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs/upload

- Content-Type：multipart/form-data
- 需要 workflows:write
- 仅支持已经处于 running 的 WorkflowAppRuntime
- 当前 multipart 保留字段：
  - input_bindings_json，可选
  - execution_metadata_json，可选
  - timeout_seconds，可选
- 其他文件字段名必须等于 application 的 input binding_id
- 当前 multipart 文件上传只支持 `dataset-package.v1` 输入绑定，不支持把图片文件直接作为 `request_image` 上传
- 当前响应与 JSON `runs` 一样返回完整 WorkflowRun 合同

### POST /api/v1/workflows/trigger-sources

- Content-Type：application/json
- 需要 workflows:write
- 用于创建 WorkflowTriggerSource 管理资源，不替代 runtime invoke 或 runs 执行 API
- 请求体字段：
  - trigger_source_id
  - project_id
  - display_name
  - trigger_kind
  - workflow_runtime_id
  - submit_mode，默认 async
  - enabled，默认 false
  - transport_config
  - match_rule
  - input_binding_mapping
  - result_mapping
  - default_execution_metadata
  - ack_policy
  - result_mode
  - reply_timeout_seconds，可选
  - debounce_window_ms，可选
  - idempotency_key_path，可选
  - metadata
- ZeroMQ TriggerSource 常用请求体字段：

```json
{
  "trigger_source_id": "zeromq-trigger-source-07",
  "project_id": "project-1",
  "display_name": "ZeroMQ TriggerSource 07 OpenCV Process Save Image",
  "trigger_kind": "zeromq-topic",
  "workflow_runtime_id": "{{workflowRuntimeId}}",
  "submit_mode": "sync",
  "transport_config": {
    "bind_endpoint": "tcp://127.0.0.1:5556",
    "default_input_binding": "request_image",
    "buffer_ttl_seconds": 30
  },
  "input_binding_mapping": {
    "request_image": {
      "source": "payload.request_image",
      "payload_type_id": "image-ref.v1"
    }
  },
  "result_mapping": {
    "result_binding": "http_response",
    "result_mode": "sync-reply",
    "reply_timeout_seconds": 30
  },
  "ack_policy": "ack-after-run-finished",
  "result_mode": "sync-reply",
  "reply_timeout_seconds": 30
}
```

- 06 调试请求体见 `docs/api/examples/workflows/06-yolox-deployment-infer-opencv-health-zeromq-image-ref/trigger-source.create.request.json`
- 07 调试请求体见 `docs/api/examples/workflows/07-opencv-process-save-image-zeromq-image-ref/trigger-source.create.request.json`
- ZeroMQ 数据面不经过该 REST API 发送图片；图片 bytes 由 C# SDK 通过 ZeroMQ multipart 发送到已启用的 TriggerSource
- 成功状态码：201 Created
- 当前响应返回 WorkflowTriggerSource 合同，包括 desired_state、observed_state、health_summary、created_at 和 updated_at

### GET /api/v1/workflows/trigger-sources

- 需要 workflows:read
- 当前必须显式提供查询参数：
  - project_id
  - offset，可选
  - limit，可选
- 返回当前 Project 下的 WorkflowTriggerSource 列表
- 响应体仍然是数组；分页信息通过统一分页响应头返回

### GET /api/v1/workflows/trigger-sources/{trigger_source_id}

- 需要 workflows:read
- 返回单条 WorkflowTriggerSource 的完整配置和最近状态

### DELETE /api/v1/workflows/trigger-sources/{trigger_source_id}

- 需要 workflows:write
- 删除一条 WorkflowTriggerSource
- 如果 trigger_kind 已注册 adapter，当前会先停止对应 adapter，再删除持久化资源
- 成功状态码：204 No Content
- 删除后可重新使用同一个 trigger_source_id 再次创建 TriggerSource

### POST /api/v1/workflows/trigger-sources/{trigger_source_id}/enable

- 需要 workflows:write
- 启用一条 WorkflowTriggerSource
- 当前要求绑定的 WorkflowAppRuntime 已经处于 running 状态
- 如果 trigger_kind 已注册 adapter，当前会启动对应 adapter，并在 health_summary 中返回 adapter_configured、adapter_running 和计数信息
- 如果 trigger_kind 尚未注册 adapter，当前只更新管理态，observed_state 仍可能是 stopped

### POST /api/v1/workflows/trigger-sources/{trigger_source_id}/disable

- 需要 workflows:write
- 停用一条 WorkflowTriggerSource
- 如果 trigger_kind 已注册 adapter，当前会停止对应 adapter
- disable 不会取消已经创建的 WorkflowRun

### GET /api/v1/workflows/trigger-sources/{trigger_source_id}/health

- 需要 workflows:read
- 返回当前启用状态、期望状态、观测状态、最近错误、最近触发时间和 health_summary

### POST /api/v1/workflows/runs/{workflow_run_id}/cancel

- 需要 workflows:write
- 用于取消当前仍处于 queued 或 running 的异步 WorkflowRun
- 当前响应会返回更新后的 WorkflowRun，包括：
  - state
  - error_message
  - metadata.cancel_requested_at
  - metadata.cancelled_by

### GET /api/v1/workflows/runs/{workflow_run_id}

- 需要 workflows:read
- 返回单条 WorkflowRun 的当前持久化结果，包括输入、输出、错误信息和元数据

### GET /api/v1/workflows/runs/{workflow_run_id}/events

- 需要 workflows:read
- 当前支持的查询参数：
  - after_sequence
  - limit
- 返回 WorkflowRun 历史事件列表
- 当前 WebSocket replay 与 live 事件 payload 与 REST 事件合同保持同层字段结构，不再额外包一层 `payload.data`

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
| /ws/v1/system/events | 无 | system 事件流入口，当前会返回 system.connected。 |
| /ws/v1/auth/events | auth:read | 订阅登录会话和长期调用 token 的实时审计事件。 |
| /ws/v1/tasks/events | tasks:read | 按 task_id 订阅任务事件。 |
| /ws/v1/workflows/preview-runs/events | workflows:read | 按 preview_run_id 订阅 preview run 实时事件。 |
| /ws/v1/workflows/runs/events | workflows:read | 按 workflow_run_id 订阅 WorkflowRun 实时事件。 |
| /ws/v1/workflows/app-runtimes/events | workflows:read | 按 workflow_runtime_id 订阅 WorkflowAppRuntime 实时事件。 |
| /ws/v1/deployments/events | models:read | 按 deployment_instance_id 订阅 deployment 实时事件。 |
| /ws/v1/projects/events | workflows:read + models:read | 按 project_id 订阅项目级聚合 summary 快照与后续更新。 |

workflow preview-run、run、app-runtime 和 deployment 四类事件流当前都已经把 WebSocket payload 与对应 REST 事件合同对齐，业务字段直接平铺在 `payload` 下，不再额外包一层 `payload.data`。

### /ws/v1/auth/events

请求头沿用 REST 的主体和 scope 规则。

当前流面向本地登录会话与长期调用 user token 的实时审计事件。

当前支持的 query 参数：

- event_type：可选
- user_id：可选
- provider_id：可选
- credential_kind：可选

连接成功后会先收到一条 auth.connected 事件，随后按当前筛选条件持续推送实时审计事件。

当前实现使用 service_event_bus 分发实时审计事件；当前阶段不提供历史回放。

### /ws/v1/tasks/events

请求头沿用 REST 的主体和 scope 规则。

当前支持的 query 参数：

- task_id：必填
- event_type：可选
- after_cursor：可选
- limit：可选，默认 100，最大 500

连接成功后会先收到一条 tasks.connected 事件，随后按当前筛选条件持续推送任务事件。

当前实现使用 service_event_bus 分发实时事件，并使用 `task_events` 表提供历史回放。

### /ws/v1/workflows/preview-runs/events

请求头沿用 REST 的主体和 scope 规则。

当前支持的 query 参数：

- preview_run_id：必填
- after_cursor：可选；当前使用 preview run 事件的 sequence 作为恢复游标
- limit：可选，默认 100，最大 500

连接成功后会先收到一条 workflows.preview-runs.connected 事件，随后按当前筛选条件持续推送 preview run 事件。

当前实现使用 service_event_bus 分发实时事件，并使用 preview run snapshot 目录下的 `events.json` 提供历史回放。

### /ws/v1/workflows/runs/events

请求头沿用 REST 的主体和 scope 规则。

当前支持的 query 参数：

- workflow_run_id：必填
- after_cursor：可选；当前使用 WorkflowRun 事件的 sequence 作为恢复游标
- limit：可选，默认 100，最大 500

连接成功后会先收到一条 workflows.runs.connected 事件，随后按当前筛选条件持续推送 WorkflowRun 事件。

当前实现使用 service_event_bus 分发实时事件，并使用 `GET /api/v1/workflows/runs/{workflow_run_id}/events` 对应的 `events.json` 提供历史回放。

### /ws/v1/workflows/app-runtimes/events

请求头沿用 REST 的主体和 scope 规则。

当前支持的 query 参数：

- workflow_runtime_id：必填
- after_cursor：可选；当前使用 WorkflowAppRuntime 事件的 sequence 作为恢复游标
- limit：可选，默认 100，最大 500

连接成功后会先收到一条 workflows.app-runtimes.connected 事件，随后按当前筛选条件持续推送 WorkflowAppRuntime 事件。

当前实现使用 service_event_bus 分发实时事件，并使用 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events` 对应的 `events.json` 提供历史回放。

当前实时事件会覆盖生命周期、worker 主动 heartbeat、heartbeat 超时和 heartbeat 恢复。

### /ws/v1/deployments/events

请求头沿用 REST 的主体和 scope 规则。

当前支持的 query 参数：

- deployment_instance_id：必填
- runtime_mode：可选；支持 `sync`、`async`
- after_cursor：可选；当前使用 deployment 事件的 sequence 作为恢复游标
- limit：可选，默认 100，最大 500

连接成功后会先收到一条 deployments.connected 事件，随后按当前筛选条件持续推送 deployment 事件。

当前实现使用 service_event_bus 分发实时事件，并使用 `GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/events` 对应的 `events.json` 提供历史回放。

### /ws/v1/projects/events

请求头沿用 REST 的主体和 scope 规则。

当前支持的 query 参数：

- project_id：必填
- topic：可选；当前支持 `workflows.preview-runs`、`workflows.runs`、`workflows.app-runtimes` 和 `deployments`

连接成功后会先收到一条 `projects.connected` 控制事件，再收到一条 `projects.summary.snapshot` 快照事件；之后当 workflow preview-run、WorkflowRun、WorkflowAppRuntime 或 deployment 生命周期事件导致项目级聚合摘要变化时，会持续推送 `projects.summary.updated`。

当前实现使用 service_event_bus 分发实时项目聚合更新，并使用 `GET /api/v1/projects/{project_id}/summary` 作为正式快照面。

## DatasetImport、DatasetExport 与 TaskRecord 的公开关系

当前 DatasetImport 提交流程已经正式挂接 TaskRecord：

1. POST /api/v1/datasets/imports 接收 zip 并保存 package.zip
2. 同时创建一条正式 TaskRecord
3. 响应返回 dataset_import_id 和 task_id
4. backend-service 生命周期托管的 DatasetImport worker 从本地持久化队列消费任务
5. worker 在处理过程中更新 TaskRecord、追加 TaskEvent，并把结果写回 DatasetImport 和 DatasetVersion

因此，导入状态有两条公开观察路径：

- 资源视角：GET /api/v1/datasets/imports/{dataset_import_id}
- 任务视角：GET /api/v1/tasks/{task_id}、GET /api/v1/tasks/{task_id}/events、/ws/v1/tasks/events?task_id=...

当前 DatasetExport 提交流程也已经正式挂接 TaskRecord：

1. POST /api/v1/datasets/exports 为指定 DatasetVersion 创建正式 DatasetExport 资源
2. 同时创建一条正式 TaskRecord
3. 响应返回 dataset_export_id 和 task_id
4. backend-service 生命周期托管的 DatasetExport worker 从本地持久化队列消费任务
5. worker 在处理过程中更新 TaskRecord、追加 TaskEvent，并把 manifest_object_key、export_path、split_names、sample_count 等结果写回 DatasetExport

因此，导出状态同样有两条公开观察路径：

- 资源视角：GET /api/v1/datasets/exports/{dataset_export_id}、GET /api/v1/datasets/{dataset_id}/versions/{dataset_version_id}/exports
- 任务视角：GET /api/v1/tasks/{task_id}、GET /api/v1/tasks/{task_id}/events、/ws/v1/tasks/events?task_id=...

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