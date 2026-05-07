# Workflow 接口文档

## 文档目的

本文档用于说明当前已经公开的 workflow template 与 FlowApplication 接口，包括 validate、save、get、execute 四组能力，以及使用真实 workflow object key 路径和 Postman 手工测试 deployment lifecycle 示例的方式。

本文档聚焦对外接口规则、真实存储路径、请求体 JSON 例子和 Postman 调试步骤，不展开执行器内部实现细节。

## 适用范围

- workflow template validate、save、get 接口
- FlowApplication validate、save、get、execute 接口
- workflow 请求头鉴权规则
- workflow service 节点语义分组
- 真实 workflow object key 路径
- deployment lifecycle detection 示例的独立 JSON 请求体
- Postman 手工测试步骤

## service 节点语义

当前 workflow 中直接复用后端服务能力的节点分成两组：

- 任务节点：例如 core.service.yolox-training.submit、core.service.yolox-conversion.submit、core.service.yolox-evaluation.submit、core.service.dataset-export.submit、core.service.yolox-inference.submit。这组节点直接调用现有应用服务并提交后台任务，训练、转换、评估、导出和异步推理仍由独立 worker 与 queue backend 执行。
- deployment 资源与控制节点：core.service.yolox-deployment.create 负责创建 DeploymentInstance 资源；core.service.yolox-deployment.start、warmup、status、health、stop、reset 负责控制或观察已有 deployment 运行态。这组节点控制的是 backend-service 已装配的 deployment control plane，而不是在 workflow execute 过程中再发布一套新的 deployment 服务。

## 接口入口

- FastAPI Swagger UI：/docs
- FastAPI OpenAPI JSON：/openapi.json
- 版本前缀：/api/v1
- 资源分组：/workflows

## 鉴权规则

### 最小请求头

- x-amvision-principal-id：调用主体 id
- x-amvision-project-ids：当前主体可访问的 Project id 列表，多个值用逗号分隔；为空时表示不按 Project 做可见性裁剪
- x-amvision-scopes：当前主体持有的 scope 列表，多个值用逗号分隔

### scope 要求

- validate 和 get 接口需要 workflows:read
- save 和 execute 接口需要 workflows:write
- 如果需要先查询可用 deployment_instance_id，还需要 models:read 和 models:write

## 真实 workflow 路径

当前 workflow 文件保存到 LocalDatasetStorage，路径规则固定如下：

- template：workflows/projects/{project_id}/templates/{template_id}/versions/{template_version}/template.json
- application：workflows/projects/{project_id}/applications/{application_id}/application.json

本文档配套的 deployment lifecycle detection 手工调试示例使用下面这组真实 object key：

- template object key：workflows/projects/project-1/templates/yolox-deployment-detection-lifecycle-real-path/versions/1.0.0/template.json
- application object key：workflows/projects/project-1/applications/yolox-deployment-detection-lifecycle-real-path-app/application.json

## 独立 JSON 示例

下面三份文件是可直接拷贝到 Postman raw body 的独立 JSON 请求体示例，不复用之前的 contract 示例文件：

- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-template.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-template.request.json)
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-application.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-application.request.json)
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.execute.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.execute.request.json)

上面这组 JSON 的特点是：

- template 与 application 使用真实 workflow object key 路径
- application.template_ref.source_uri 直接写成真实 template object key
- execute 请求使用 image-ref.v1 的最小 object_key 形状
- deployment_instance_id 保留为占位字符串，需要替换成真实可用实例 id
- 当前 lifecycle 示例只覆盖 deployment 控制链路与 detection 节点，DeploymentInstance 资源需要预先准备

## 接口清单

### POST /api/v1/workflows/templates/validate

- Content-Type：application/json
- 需要 workflows:read
- 请求体字段：
  - template
- 成功状态码：200 OK
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
- 路径参数中的 template_id 和 template_version 必须与请求体中的 template 一致
- 成功状态码：201 Created
- 返回字段：
  - project_id
  - object_key
  - template
  - validate 接口中的同名校验摘要字段

### GET /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions/{template_version}

- 需要 workflows:read
- 返回字段：
  - project_id
  - object_key
  - template
  - validate 接口中的同名校验摘要字段

### POST /api/v1/workflows/applications/validate

- Content-Type：application/json
- 需要 workflows:read
- 请求体字段：
  - project_id
  - application
  - template，可选
- 当 template 为空时，服务会按 application.template_ref 读取已保存 template
- 成功状态码：200 OK
- 返回字段：
  - valid
  - application_id
  - template_id
  - template_version
  - binding_count
  - input_binding_ids
  - output_binding_ids

### PUT /api/v1/workflows/projects/{project_id}/applications/{application_id}

- Content-Type：application/json
- 需要 workflows:write
- 路径参数中的 application_id 必须与请求体中的 application.application_id 一致
- 成功状态码：201 Created
- 服务保存 application 时会把 application.template_ref.source_uri 规范化为实际保存后的 template object key
- 返回字段：
  - project_id
  - object_key
  - application
  - validate 接口中的同名校验摘要字段

### GET /api/v1/workflows/projects/{project_id}/applications/{application_id}

- 需要 workflows:read
- 返回字段：
  - project_id
  - object_key
  - application
  - validate 接口中的同名校验摘要字段

### POST /api/v1/workflows/projects/{project_id}/applications/{application_id}/execute

- Content-Type：application/json
- 需要 workflows:write
- execute API 当前在 backend-service 的现有运行时中执行，service-backed nodes 会直接复用已装配的 queue backend、workflow runtime registry 和 deployment supervisors
- workflow execute 链顺序图与常见失败分支见 [docs/architecture/execution-sequences.md](../architecture/execution-sequences.md)。
- 请求体字段：
  - input_bindings：按 application input binding_id 组织的输入 payload
  - execution_metadata：整次执行附加元数据
- 成功状态码：200 OK
- 返回字段：
  - project_id
  - application_id
  - template_id
  - template_version
  - outputs：按 output binding_id 组织的输出
  - template_outputs：按 template output id 组织的底层输出
  - node_records：节点执行记录列表

## deployment lifecycle detection 手工测试

### 目标链路

当前示例用于演示 deployment 控制节点和 detection 模型节点如何控制并使用一个已经存在的 sync deployment_instance_id。执行链路仍按节点声明顺序组织为：

1. start
2. warmup
3. detection
4. health
5. stop

当前 deployment lifecycle 控制节点还没有显式控制输入端口，因此这组示例依赖最小执行器对零入度节点的稳定声明顺序。

当前示例不把 core.service.yolox-deployment.create 编排进同一条 lifecycle 链路。原因是当前最小合同还没有把上游节点输出直接映射到下游参数字段；DeploymentInstance 资源可以先通过 deployment create API 或 create 节点单独准备，再由 lifecycle 示例负责控制与使用。

### 前置条件

1. backend-service 已启动
2. project-1 下已经存在至少一个可用的 YOLOX deployment_instance_id，或已通过 deployment create API / workflow create 节点单独准备好实例
3. data/files/inputs/source.jpg 已存在，或 execute 请求里的 object_key 已改成实际可读图片路径

### Postman collection

可直接导入下面这份独立 collection：

- [docs/api/postman/workflows.postman_collection.json](postman/workflows.postman_collection.json)

collection 已内置下面这组默认变量：

- baseUrl=http://127.0.0.1:8000
- projectId=project-1
- templateId=yolox-deployment-detection-lifecycle-real-path
- templateVersion=1.0.0
- applicationId=yolox-deployment-detection-lifecycle-real-path-app
- deploymentInstanceId=replace-with-existing-deployment-instance-id
- requestImageObjectKey=inputs/source.jpg

### 建议调用顺序

1. Get Service Health
2. List YOLOX Deployment Instances
3. Validate Workflow Template
4. Save Workflow Template
5. Get Workflow Template
6. Validate Flow Application
7. Save Flow Application
8. Get Flow Application
9. Execute Flow Application

List YOLOX Deployment Instances 的测试脚本会尝试把返回列表第一条记录的 deployment_instance_id 回填到 collection variable。若返回列表为空，说明当前环境还没有可复用 deployment，需要先通过 deployment create 接口或 workflow create 节点准备实例。

### execute 结果重点字段

成功执行后，建议优先检查下面这些字段：

- outputs.start_body.process_state：预期为 running
- outputs.warmup_body.warmed_instance_count：预期大于 0
- outputs.detections.items：预期为 detection 结果数组
- outputs.health_body.healthy_instance_count：预期大于 0
- outputs.stop_body.process_state：预期为 stopped

如果需要判断节点是否按预期顺序执行，可继续检查 node_records 的顺序和每个节点的 outputs。

## 常见调试点

- Save Flow Application 成功后，如果返回体里的 application.template_ref.source_uri 与请求体不同，以返回体里的规范化 object key 为准
- Execute Flow Application 返回图片 object_key 不存在时，优先检查 data/files 下是否真的有对应文件
- Execute Flow Application 当前不会在 workflow 子进程里重新发布 deployment 服务；如果 start、warmup、health、stop 行为异常，应优先检查 backend-service 当前进程里的 deployment supervisor 是否已经完成启动
- detection 节点当前把 auto_start_process 设为 false，目的是让 workflow 明确依赖前面的 start 节点；如果跳过 start 或 warmup，预期会在 detection 处暴露 deployment 运行状态问题
- 当前示例只覆盖 sync deployment detection 链路，不覆盖 async inference-tasks

## 相关文件

- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-template.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-template.request.json)
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-application.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-application.request.json)
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.execute.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.execute.request.json)
- [docs/api/postman/workflows.postman_collection.json](postman/workflows.postman_collection.json)
- [docs/architecture/workflow-json-contracts.md](../architecture/workflow-json-contracts.md)