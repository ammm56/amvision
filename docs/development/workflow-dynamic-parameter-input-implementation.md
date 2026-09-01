# Workflow 动态参数输入实施基线

## 目标

本实施基线用于把节点参数输入框扩展为可由其他节点输出或 App Entry 输入赋值的正式 Workflow 数据链路。实现参考 ComfyUI 的“输入框与输入端口共存”交互，但继续使用 AMVision 自己的 `NodeDefinition`、版本化 payload、DAG 校验和 Workflow Runtime，不依赖 `projectsrc/` 运行时代码。

## 不可变边界

- 参数输入必须由 `NodeDefinition.parameter_input_bindings` 显式声明，不根据参数名称或 JSON Schema 自动生成。
- 参数端口是正式 `input_ports`，Graph Edge、Template Input、拓扑、循环检测和 payload 类型校验继续使用现有规则。
- 第一版参数端口只接受 `value.v1`，不执行 `text.v1`、数字、布尔或其他 payload 的隐式转换。
- 连接值覆盖节点实例中的固定参数；没有连接时依次使用固定参数和 JSON Schema `default`。
- 连接传入的 `{"value": null}` 是真实动态值，不等同于没有连接。
- 断开连线只移除 Graph Edge 或 Template Input，不删除节点实例中保留的固定回退值。
- 动态值按目标参数的 JSON Schema 属性校验；错误必须包含节点、参数、输入端口、值来源和 schema 路径。
- Parallel、ForEach、Selection 的分支结构、并发数量和其他执行计划参数不开放动态输入。
- 模型部署实例、资源生命周期、timeout 和安全策略默认保持固定；只有完成专项生命周期审计后才能显式开放。
- 不增加隐藏排队、等待、重试、自动类型推断或运行时图修改。
- 不新增 Workflow Graph、HTTP Runtime、ZeroMQ Trigger、本机共享内存 Trigger 或 .NET SDK 协议格式。
- `NodeDefinition` 继续使用 `amvision.node-definition.v1`；新增字段为有默认值的向后兼容字段，不引入代码协议 v2。

## 公开契约

`NodeDefinition` 增加以下绑定：

```json
{
  "parameter_input_bindings": [
    {
      "parameter_name": "file_name",
      "input_port_name": "file_name"
    }
  ]
}
```

每个绑定必须同时满足：

- `parameter_name` 存在于 `parameter_schema.properties`。
- `input_port_name` 存在于 `input_ports`。
- 输入端口为 `required=false`、`multiple=false`、`payload_type_id=value.v1`。
- 参数名和输入端口名在绑定集合中分别唯一。

Graph Template 不保存额外绑定状态。参数端口连接仍使用普通 `WorkflowGraphEdge.target_port`，固定回退值仍保存在 `WorkflowGraphNode.parameters`。

## 运行时解析

节点 handler 调用前统一构建有效参数：

1. 复制节点实例固定参数。
2. 已连接的绑定端口读取 `value.v1.value` 并覆盖对应参数。
3. 未连接且固定参数缺失时读取参数 JSON Schema `default`。
4. 仍缺少 schema 必填参数时返回稳定输入错误。
5. 对每个已声明绑定的最终值执行 Draft 2020-12 JSON Schema 校验。

解析放在统一节点 handler 调用入口，普通图、Parallel 子图、ForEach 子图和 Selection 子图使用同一语义。`request.input_values` 保留原始 payload，`request.parameters` 保存解析后的最终参数。

## 前端行为

- 参数输入框和参数端口始终共存，不提供“启用动态参数”开关。
- 参数端口显示在对应参数行，不在节点顶部普通输入区域重复显示。
- 未连接时输入框可编辑；已连接时输入框只读并显示来源，固定值继续保留为回退值。
- 参数端口继续使用现有端口拖线、右键、选择和 `payload_type_id` 校验。
- 参数行坐标和节点高度由同一布局函数计算，端口与连线不能因 JSON 编辑框高度产生偏移。

## 首批节点

`core.io.image-save` 首批开放：

- `save_directory`
- `file_name`
- `overwrite`

三个参数端口均为可选 `value.v1`。保存目录和文件名复用节点系统通用日期时间模板；扩展名检查、原子重名递增和 ObjectStore/绝对目录边界保持不变。

第一阶段补充 `String Value`、`Number Value` 和 `Boolean Value` 三个明确的通用节点，统一输出 `value.v1`。对象和数组继续使用 App Entry、File Read JSON、Object Create 和 List Create，不新增自动猜测类型的虚拟 Primitive 节点。

## 现有双源节点审计

Core Node Catalog 目前还有 28 个参数具备“可选 `value.v1` 端口 + 固定参数回退”双源行为，分布在目录批处理、文件保存、结果响应、集合索引、数值运算、分支默认值、变量和视频帧等节点。这些节点原本已经通过正式输入端口支持动态赋值，第一阶段不批量改写其 handler 或 UI 布局，原因如下：

- 批量登记绑定会立即改变现有编辑器端口位置，属于可见行为变更。
- 统一解析器会按参数 JSON Schema 校验连接值，部分旧节点当前在 handler 中使用更窄或带上下文的校验规则，必须逐节点核对后迁移。
- 输入名与回退参数名不总是一致，例如 `right -> right_value`、`default -> default_value`，不得按名称自动推断。
- 现有节点的正式输入端口继续可用，不影响本次动态保存路径和文件名能力。

后续迁移必须以单节点或同一能力族为单位，显式增加 `parameter_input_bindings`、删除重复的 handler 双源解析并补兼容测试；不得用目录扫描结果自动写入绑定。首批仅登记 `core.io.image-save` 的三个已完成审计参数。

## 兼容与发布

- 旧节点定义未声明绑定时行为完全不变。
- 旧 Workflow 继续使用固定参数，不需要数据库迁移或 Graph Template 迁移。
- 新参数端口只在使用新 Node Catalog 编辑并重新发布的 Workflow App Version 中生效。
- 已发布版本保持不可变；Runtime 继续按发布快照和依赖指纹加载。
- Custom Node 可以使用同一绑定契约；未声明时保持固定参数语义。

## 验收门禁

- 契约、Catalog、Graph Executor、Save Image 和前端组件测试通过。
- 普通、Parallel、ForEach 和 App Entry 输入覆盖行为一致。
- HTTP、ZeroMQ、本机共享内存和 .NET SDK 使用现有 `value.v1` 输入即可驱动参数，不增加协议分支。
- 两并发保存无覆盖、无重复命名竞争和临时文件残留。
- 动态参数解析不创建线程、队列、锁等待或后台任务。
- 长时间运行时 runtime worker 内存和 handle 不出现持续增长。
