# 工作流 JSON 合同

## 文档目的

本文档用于定义四类稳定对象：WorkflowPayloadContract、NodeDefinition、WorkflowGraphTemplate 和 FlowApplication。

目标不是把执行器一次做完，而是先把保存、加载、校验和后续执行依赖的 JSON 合同定下来，避免流程编辑器、custom nodes、API 绑定和 worker 执行各自发明一套结构。

## 适用范围

- payload contract 的最小字段
- NodeDefinition 的最小字段
- 图模板与可执行流程应用的边界
- custom_nodes 目录与 node pack 合同的关系
- Python 环境中的保存、加载和校验方式

## 边界结论

- 当前阶段采用最简单的 JSON 方案保存和加载流程配置，方向与 ComfyUI workflow 的使用方式保持一致
- 当前阶段的可执行流程应用是 Python 运行环境中加载的一份 JSON 配置，不是 exe 打包产物
- 图模板只负责节点图结构、参数状态、逻辑输入输出和编辑器状态
- 流程应用只负责引用哪一份图模板，并把模板暴露的逻辑输入输出绑定到 API、HTTP 回包、ZeroMQ、PLC、上传等现场端点
- 训练、验证、转换、推理这些重任务仍然由独立 worker 进程承担，不把节点图执行器设计成替代它们的一体化单进程运行器
- deployment 资源创建与运行态控制应继续依赖 backend-service 已装配的 deployment control plane，而不是在 workflow execute 过程中另起一套 workflow-local deployment 服务

## 对象分层

### 1. WorkflowPayloadContract

payload contract 定义“端口上传的是什么”。

当前最小字段包括：

- payload_type_id：稳定类型 id，例如 image-ref.v1、image-refs.v1、detections.v1、contours.v1、measurements.v1、response-body.v1、http-response.v1
- transport_kind：传输方式，例如 inline-json、artifact-ref、hybrid
- json_schema：结构说明
- artifact_kinds：涉及的 artifact 类型，例如 image、report、preview

这里不要求所有图片都以内联 base64 在节点之间流动。对于图片、预览图、裁剪图、模型产物等大对象，推荐传 artifact 引用，而不是把大二进制塞进节点边。

### 2. NodeDefinition

NodeDefinition 定义“节点能接什么、吐什么、怎么运行”。

当前最小字段包括：

- node_type_id：稳定节点类型 id
- category：节点分类，例如 io.input、model.inference、opencv.render、integration.output
- implementation_kind：core-node 或 custom-node
- runtime_kind：python-callable、worker-task、service-call
- input_ports / output_ports：端口定义，端口直接引用 payload_type_id
- parameter_schema：参数 schema
- runtime_requirements：运行依赖，例如 opencv-python、numpy、特定 worker pool
- node_pack_id / node_pack_version：仅 custom-node 需要

这层是节点目录，不是流程实例。

### 3. WorkflowGraphTemplate

WorkflowGraphTemplate 定义“节点怎么连”。

当前最小字段包括：

- nodes：节点实例列表
- edges：节点连线
- template_inputs：模板对外暴露的逻辑输入
- template_outputs：模板对外暴露的逻辑输出
- ui_state：节点编辑器状态，例如位置和折叠状态

模板保存的是图结构和编辑状态，不保存现场端点。

### 4. FlowApplication

FlowApplication 定义“这份模板在现场怎么接入和输出”。

当前最小字段包括：

- template_ref：引用哪一份模板 JSON 或模板注册记录
- runtime_mode：当前固定为 python-json-workflow
- bindings：把模板逻辑输入输出绑定到现场端点

FlowApplication 不是新的打包形式，也不是 exe。它只是另一份 JSON，用来把模板与现场端点装配起来。

当前 backend-service 的 FastAPI 触发面默认是通用 runtime invoke：

- `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke`
- `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload`

FlowApplication 中 `bindings.config.route` 在现阶段主要用于描述绑定目标和后续适配方向，不等价于“保存 application 后自动生成同名专用 HTTP 路由”。

## service 节点语义分组

当前直接对接后端服务的 workflow 节点按语义分成两组：

- 任务节点：按现有公开服务接口直接提交训练、转换、评估、导出、异步推理等后台任务。节点参数和 API 请求体保持同一组业务字段，真正的重任务执行仍交给独立 worker、queue backend 和后台任务管理器。
- deployment 资源与控制节点：core.service.yolox-deployment.create 负责创建 DeploymentInstance 资源；start、warmup、status、health、stop、reset 负责控制或观察已有 deployment 运行态。当前 execute API 会在 backend-service 当前运行时中执行这组节点，节点调用的仍是服务进程已有的 deployment supervisor，而不是 workflow-local supervisor。

这组边界的目标是把 workflow 节点保持为“参数化的服务调用编排”，而不是让 workflow 执行器演变成另一套独立部署 runtime。

## 模板与应用的关系

推荐固定为下面的边界：

1. 模板负责：图结构、节点参数、逻辑输入输出、编辑器布局。
2. 应用负责：选择模板版本、绑定 API、ZeroMQ、PLC、上传等端点、声明运行模式。
3. 执行器负责：在 Python 环境中加载模板 JSON 和应用 JSON，完成校验、实例化和执行。

这意味着同一份模板可以派生出多份流程应用：

- 一份绑定 HTTP API 输入和 HTTP 响应输出
- 一份绑定 ZeroMQ 输入和 PLC 写入输出
- 一份绑定本地文件输入和上传输出

模板不需要复制，只有应用绑定不同。

## 节点目录与 custom_nodes 的关系

- backend/nodes/core_catalog.py 提供内建 core nodes 与 core payload contract
- LocalNodePackLoader 扫描 custom_nodes 根目录，读取每个 node pack 的 manifest.json 与 workflow/catalog.json
- node pack 内部可以把 catalog 源拆到 workflow/catalog_sources/ 下的多个碎片文件，再通过生成步骤汇总成 workflow/catalog.json
- NodeCatalogRegistry 把 core nodes 与 custom nodes 合并成统一目录
- WorkflowGraphTemplate 和 FlowApplication 的校验始终针对统一节点目录，而不是只看某一个 node pack

### barcode.protocol-nodes 当前维护方式

barcode.protocol-nodes 现在采用和 opencv.basic-nodes 一致的拆分维护方式：

- backend/nodes/*.py 只放节点执行实现、NODE_TYPE_ID 和 handle_node
- workflow/catalog_sources/nodes/*.json 单独维护每个节点的 NodeDefinition
- workflow/catalog_sources/payload_contracts.json 维护额外 payload contract
- workflow/catalog_sources/metadata.json 维护节点包元数据
- workflow/catalog.json 作为最终产物，供 manifest.json 的 customNodeCatalogPath 引用

其中 custom_nodes/barcode_protocol_nodes/workflow/catalog_builder.py 提供两层调用：

- build_custom_node_catalog_payload：把 workflow/catalog_sources 下的定义组装成可序列化 JSON 结构
- write_custom_node_catalog：把组装结果写回 workflow/catalog.json

custom_nodes/barcode_protocol_nodes/workflow/generate_catalog.py 是面向日常维护的命令入口。开发阶段不依赖自动任务；当节点定义变化或新增节点后，由开发人员手动执行生成步骤回写 catalog.json。

### barcode.protocol-nodes 手动生成流程

对于 barcode.protocol-nodes，catalog.json 的维护流程分成两类：

1. decode 节点规格发生变化

这类变化通常来自 custom_nodes/barcode_protocol_nodes/specs.py，例如新增条码制式、修改 display_name、description、capability_tags 或公共参数 schema。此时需要先更新批量生成的 backend 节点模块和对应 node JSON，再回写 catalog.json。

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m custom_nodes.barcode_protocol_nodes.backend.generate_decode_node_modules
D:/software/anaconda3/envs/amvision/python.exe -m custom_nodes.barcode_protocol_nodes.workflow.generate_catalog
```

2. 非 decode 节点发生变化

这类节点包括 filter-results、match-exists、results-summary、draw-results 等手写节点。修改方式是分别维护：

- backend/nodes/<node>.py
- workflow/catalog_sources/nodes/<node>.json

完成修改后只需要回写 catalog.json：

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m custom_nodes.barcode_protocol_nodes.workflow.generate_catalog
```

### 维护约定

- workflow/catalog.json 视为发布产物，不直接手工编辑
- workflow/catalog_sources/nodes/*.json 才是 barcode.protocol-nodes 的 NodeDefinition 源文件
- backend/nodes/*.py 和 workflow/catalog_sources/nodes/*.json 需要保持一一对应
- 新增节点时，应先补执行实现和对应 node JSON，再手动执行 generate_catalog.py 回写 catalog.json
- 如变更来自 specs.py，还应先执行 generate_decode_node_modules.py，避免 backend/nodes 与 node JSON 漂移

## 图模型规则

- 当前阶段图模板按 DAG 校验，不允许环路
- 节点边连接时，源输出端口和目标输入端口必须引用同一个 payload_type_id
- 单输入端口默认只允许一个上游输入；只有 multiple=true 的端口才允许多个输入
- 模板输入本质上也是外部来源注入，因此会与上游边共享同一套输入数量校验

这里的 DAG 是节点执行图，不是 RAG，也不建议用 LangGraph 作为平台主干。

## OpenCV 自定义节点规划

OpenCV 节点不应直接写死在推理 runtime 里，而应通过 custom-node 接入统一节点目录。

当前 opencv.basic-nodes 已落地的节点族：

- opencv.render：draw-detections
- opencv.filter：gaussian-blur、binary-threshold、morphology、canny
- opencv.analysis：contour、measure
- opencv.io：crop-export
- opencv.preview：gallery-preview

其中 contour 输出 contours.v1，measure 输出 measurements.v1，gallery-preview 输出 response-body.v1，可继续接到 core.output.http-response。

这些节点统一通过 NodeDefinition 声明 runtime_requirements，例如：

- python_packages: [opencv-python, numpy]
- node_pack_id: opencv.basic-nodes
- capability_tags: [opencv.draw, opencv.measure]

## 最小 JSON 例子

### NodeDefinition

```json
{
  "format_id": "amvision.node-definition.v1",
  "node_type_id": "custom.opencv.draw-detections",
  "display_name": "Draw Detections",
  "category": "opencv.render",
  "description": "通过 OpenCV 把 detection 结果叠加到图片上。",
  "implementation_kind": "custom-node",
  "runtime_kind": "python-callable",
  "input_ports": [
    {
      "name": "image",
      "display_name": "Image",
      "payload_type_id": "image-ref.v1",
      "required": true,
      "multiple": false,
      "metadata": {}
    },
    {
      "name": "detections",
      "display_name": "Detections",
      "payload_type_id": "detections.v1",
      "required": true,
      "multiple": false,
      "metadata": {}
    }
  ],
  "output_ports": [
    {
      "name": "image",
      "display_name": "Image",
      "payload_type_id": "image-ref.v1",
      "required": true,
      "multiple": false,
      "metadata": {}
    }
  ],
  "parameter_schema": {
    "type": "object",
    "properties": {
      "line_thickness": {"type": "integer", "minimum": 1},
      "font_scale": {"type": "number", "minimum": 0},
      "draw_scores": {"type": "boolean"},
      "output_object_key": {"type": "string"}
    }
  },
  "capability_tags": ["opencv.draw", "vision.render"],
  "runtime_requirements": {
    "python_packages": ["opencv-python", "numpy"]
  },
  "node_pack_id": "opencv.basic-nodes",
  "node_pack_version": "0.1.0",
  "metadata": {}
}
```

### NodePack manifest

```json
{
  "format_id": "amvision.node-pack-manifest.v1",
  "id": "opencv.basic-nodes",
  "version": "0.1.0",
  "displayName": "OpenCV Basic Nodes",
  "category": "custom-node-pack",
  "capabilities": ["pipeline.node", "vision.filter", "vision.render", "vision.analysis", "vision.preview"],
  "enabledByDefault": true,
  "customNodeCatalogPath": "workflow/catalog.json"
}
```

对于需要拆分维护的 node pack，推荐把每个 NodeDefinition 单独维护在 workflow/catalog_sources/nodes/ 下，把额外 payload contract 维护在 workflow/catalog_sources/payload_contracts.json，然后通过类似 custom_nodes/opencv_basic_nodes/workflow/generate_catalog.py 的生成步骤汇总出最终的 workflow/catalog.json。

barcode.protocol-nodes 当前已经采用这套维护方式，并固定通过 custom_nodes/barcode_protocol_nodes/workflow/generate_catalog.py 手动回写 workflow/catalog.json。

### FlowApplication

```json
{
  "format_id": "amvision.flow-application.v1",
  "application_id": "inspection-api-app",
  "display_name": "Inspection API App",
  "template_ref": {
    "template_id": "inspection-demo",
    "template_version": "1.0.0",
    "source_kind": "json-file",
    "source_uri": "workflows/inspection-demo.template.json",
    "metadata": {}
  },
  "runtime_mode": "python-json-workflow",
  "description": "应用只负责端点绑定。",
  "bindings": [
    {
      "binding_id": "api-entry",
      "direction": "input",
      "template_port_id": "request_image",
      "binding_kind": "api-request",
      "config": {"route": "/api/v1/inspect", "method": "POST"},
      "metadata": {}
    },
    {
      "binding_id": "api-return",
      "direction": "output",
      "template_port_id": "inspection_response",
      "binding_kind": "http-response",
      "config": {"status_code": 200},
      "metadata": {}
    }
  ],
  "metadata": {}
}
```

### Deployment lifecycle detection 示例

一组可直接保存的最小 JSON 示例已放在下面两个文件：

- [docs/examples/workflows/yolox_deployment_detection_lifecycle.template.json](../examples/workflows/yolox_deployment_detection_lifecycle.template.json)
- [docs/examples/workflows/yolox_deployment_detection_lifecycle.application.json](../examples/workflows/yolox_deployment_detection_lifecycle.application.json)

这组示例复用已有 deployment_instance_id，按 sync deployment 通道执行 start -> warmup -> detection -> health -> stop，并把 start、warmup、detections、health、stop 五个结果作为 template outputs 暴露给 FlowApplication。

在语义上，这组示例包含两类节点：

- deployment 控制节点：start、warmup、health、stop
- 模型使用节点：detect

当前示例不把 create 节点编排进同一条链路。DeploymentInstance 资源可先通过 deployment create API 或 create 节点单独准备，再由当前示例负责控制和使用。当前 deployment lifecycle 控制节点还没有显式控制输入端口，因此该示例通过 template.nodes 的声明顺序表达执行先后。当前最小执行器会按零入度节点的声明顺序稳定执行，所以这组 JSON 在现有实现下是可验证且可执行的；如果后续引入专门的 control-edge 或 trigger payload，这组示例应改成显式边连接。

通过 execute API 调用这份 FlowApplication 时，最小输入 payload 形状如下：

```json
{
  "input_bindings": {
    "request_image": {
      "object_key": "projects/project-1/inputs/source.jpg"
    }
  }
}
```

这里的 `projects/project-1/inputs/source.jpg` 用来表达“传入一个 Project 管理的 storage object key”。请求期临时输入不应复用这个目录，而应进入 `runtime/inputs/{consumer}/{request_id}/...`。

上面两份文件保持 contract 示例角色，继续使用 docs/examples 下的演示路径。面向真实 workflow object key 路径、真实 save、preview-run、app-runtime create 和 invoke 请求体，以及 Postman 手工测试的独立 JSON 示例，已另外放到下面这些文件：

- [docs/api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/save-template.request.json](../api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/save-template.request.json)
- [docs/api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/save-application.request.json](../api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/save-application.request.json)
- [docs/api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/preview-run.request.json](../api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/preview-run.request.json)
- [docs/api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/app-runtime.create.request.json](../api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/app-runtime.create.request.json)
- [docs/api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/app-runtime.invoke.request.json](../api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/app-runtime.invoke.request.json)
- [docs/api/workflows.md](../api/workflows.md)
- [docs/api/postman/workflow-runtime.postman_collection.json](../api/postman/workflow-runtime.postman_collection.json)

## 当前落地范围

当前已经落地：

- workflows contracts Python 模块
- WorkflowPayloadContract、NodeDefinition、WorkflowGraphTemplate、FlowApplication 四类对象
- 节点目录校验、模板 DAG 校验、流程应用绑定校验
- LocalNodePackLoader、NodePackManifest、CustomNodeCatalogDocument
- NodeCatalogRegistry 合并 core nodes 与 custom nodes
- backend-service 的模板 / 应用 validate、save、get API
- backend-service 当前已经公开 WorkflowPreviewRun、WorkflowAppRuntime、WorkflowRun 三类 runtime API；编辑态试跑走隔离子进程，已发布应用走单 runtime worker
- 最小图执行器，当前支持 python-callable 和 worker-task 两类节点
- node pack entrypoint 到实际 python-callable / worker-task handler 的自动注册

当前还没有落地：

- 更完整的 custom node 运行时隔离与依赖装载
- 流程编辑器前端

## 下一步建议

1. 在节点编辑器里补齐 node group、分类和节点包版本展示。
2. 把 custom_nodes 资产纳入发行装配与发布校验。
3. 再把图执行结果接入现有任务状态流和现场端点绑定。