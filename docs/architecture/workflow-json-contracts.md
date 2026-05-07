# 工作流 JSON 合同

## 文档目的

本文档用于定义三层稳定对象：NodeDefinition、WorkflowGraphTemplate 和 FlowApplication。

目标不是直接实现节点执行器，而是先把保存、加载、校验和后续执行所依赖的 JSON 合同定下来，避免后面流程编辑器、插件节点、API 绑定和 worker 执行各自发明一套结构。

## 适用范围

- NodeDefinition 的最小字段
- 节点 payload contract 的最小字段
- 图模板与可执行流程应用的边界
- Python 环境中的保存 / 加载方式
- OpenCV 机器视觉插件节点的基础规划

## 边界结论

- 当前阶段采用最简单的 JSON 方案保存和加载流程配置，方向与 ComfyUI workflow 的使用方式保持一致
- 当前阶段的可执行流程应用是 Python 运行环境中加载的一份 JSON 配置，不是 exe 打包产物
- 图模板只负责节点图结构、参数状态、逻辑输入输出和编辑器状态
- 流程应用只负责引用哪一份图模板，并把模板暴露的逻辑输入输出绑定到 API、HTTP 回包、ZeroMQ、PLC、上传等现场端点
- 训练、验证、转换、推理这些重任务仍然由既有独立 worker 进程承担，不把节点图执行器设计成替代它们的一体化单进程运行器

## 对象分层

### 1. payload contract

payload contract 定义“端口上传的是什么”。

当前最小字段包括：

- payload_type_id：稳定类型 id，例如 image-ref.v1、detections.v1、http-response.v1
- transport_kind：传输方式，例如 inline-json、artifact-ref、hybrid
- json_schema：结构说明
- artifact_kinds：涉及的 artifact 类型，例如 image、report、preview

这里不要求所有图片都以内联 base64 在节点之间流动。对于图片、预览图、裁剪图、模型产物等大对象，推荐传 artifact 引用，而不是把大二进制塞进节点边。

### 2. NodeDefinition

NodeDefinition 定义“节点能接什么、吐什么、怎么运行”。

当前最小字段包括：

- node_type_id：稳定节点类型 id
- category：节点分类，例如 io.input、model.inference、opencv.render、integration.output
- implementation_kind：core-node 或 plugin-node
- runtime_kind：python-callable、worker-task、service-call
- input_ports / output_ports：端口定义，端口直接引用 payload_type_id
- parameter_schema：参数 schema
- runtime_requirements：运行依赖，例如 opencv-python、numpy、特定 worker pool
- plugin_id / plugin_version：仅 plugin-node 需要

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

## 模板与应用的关系

推荐固定为下面的边界：

1. 模板负责：图结构、节点参数、逻辑输入输出、编辑器布局。
2. 应用负责：选择模板版本、绑定 API / ZeroMQ / PLC / 上传等端点、声明运行模式。
3. 执行器负责：在 Python 环境中加载模板 JSON 和应用 JSON，完成校验、实例化和执行。

这意味着同一份模板可以派生出多份流程应用：

- 一份绑定 HTTP API 输入和 HTTP 响应输出
- 一份绑定 ZeroMQ 输入和 PLC 写入输出
- 一份绑定本地文件输入和上传输出

模板不需要复制，只有应用绑定不同。

## 图模型规则

- 当前阶段图模板按 DAG 校验，不允许环路
- 节点边连接时，源输出端口和目标输入端口必须引用同一个 payload_type_id
- 单输入端口默认只允许一个上游输入；只有 multiple=true 的端口才允许多个输入
- 模板输入本质上也是外部来源注入，因此会与上游边共享同一套输入数量校验

这里的 DAG 是节点执行图，不是 RAG，也不建议用 LangGraph 作为平台主干。

## OpenCV 插件节点规划

OpenCV 节点不应直接写死在推理 runtime 里，而应通过 plugin-node 接入节点目录。

第一批值得稳定下来的 OpenCV 节点族：

- opencv.io：图片加载、图片保存、图片预览、裁剪图导出
- opencv.filter：blur、threshold、morphology、canny
- opencv.geometry：contour、hull、line、circle、rectangle、perspective transform
- opencv.measure：尺寸测量、角度、面积、距离、缺陷计数
- opencv.render：draw boxes、draw polygons、draw text、overlay mask
- opencv.match：template match、feature match、region compare

这些节点统一通过 NodeDefinition 声明 runtime_requirements，例如：

- python_packages: [opencv-python, numpy]
- plugin_id: opencv.basic-nodes
- capability_tags: [opencv.draw, opencv.measure]

## 最小 JSON 例子

### NodeDefinition

```json
{
  "format_id": "amvision.node-definition.v1",
  "node_type_id": "plugin.opencv.draw-detections",
  "display_name": "Draw Detections",
  "category": "opencv.render",
  "description": "通过 OpenCV 把 detection 结果叠加到图片上。",
  "implementation_kind": "plugin-node",
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
      "name": "response",
      "display_name": "Response",
      "payload_type_id": "http-response.v1",
      "required": true,
      "multiple": false,
      "metadata": {}
    }
  ],
  "parameter_schema": {
    "type": "object",
    "properties": {
      "line_thickness": {"type": "integer", "minimum": 1},
      "render_preview": {"type": "boolean"}
    }
  },
  "capability_tags": ["opencv.draw", "vision.render"],
  "runtime_requirements": {
    "python_packages": ["opencv-python", "numpy"]
  },
  "plugin_id": "opencv.basic-nodes",
  "plugin_version": "0.1.0",
  "metadata": {}
}
```

### WorkflowGraphTemplate

```json
{
  "format_id": "amvision.workflow-graph-template.v1",
  "template_id": "inspection-demo",
  "template_version": "1.0.0",
  "display_name": "Inspection Demo",
  "description": "模板只负责图结构。",
  "nodes": [
    {
      "node_id": "input_image",
      "node_type_id": "core.io.template-input.image",
      "parameters": {},
      "ui_state": {"position": {"x": 20, "y": 60}},
      "metadata": {}
    },
    {
      "node_id": "detect",
      "node_type_id": "core.model.yolox-detection",
      "parameters": {"score_threshold": 0.3},
      "ui_state": {"position": {"x": 280, "y": 60}},
      "metadata": {}
    }
  ],
  "edges": [
    {
      "edge_id": "edge-input-image",
      "source_node_id": "input_image",
      "source_port": "image",
      "target_node_id": "detect",
      "target_port": "image",
      "metadata": {}
    }
  ],
  "template_inputs": [
    {
      "input_id": "request_image",
      "display_name": "Request Image",
      "payload_type_id": "image-ref.v1",
      "target_node_id": "input_image",
      "target_port": "payload",
      "metadata": {}
    }
  ],
  "template_outputs": [
    {
      "output_id": "inspection_response",
      "display_name": "Inspection Response",
      "payload_type_id": "http-response.v1",
      "source_node_id": "draw_response",
      "source_port": "response",
      "metadata": {}
    }
  ],
  "metadata": {}
}
```

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

## 当前落地范围

当前已经先落地：

- workflows contracts Python 模块
- payload contract、NodeDefinition、WorkflowGraphTemplate、FlowApplication 四类对象
- 节点目录校验、模板 DAG 校验、流程应用绑定校验

当前还没有落地：

- PluginLoader 与节点目录扫描
- 图执行器
- 模板 / 应用保存和加载 API
- OpenCV 插件节点实现
- 流程编辑器前端

## 下一步建议

1. 先在 backend-service 中补模板 / 应用 JSON 的保存与读取接口。
2. 再补一层最小图执行器，只支持 python-callable 和 worker-task 两类节点。
3. 先内置一组 core io 节点与一组 OpenCV plugin-node 示例节点。
4. 最后再把图执行结果接入现有任务状态流和现场端点绑定。