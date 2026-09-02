# 节点系统

> 当前状态：本页描述已经落地的可信节点执行边界。Preview 使用进程内协作式取消；正式 Runtime 使用 generation 级共享取消信号，并以整个 Runtime worker 作为 Node Pack 超时后的强制终止和自动恢复边界。实现不创建每节点进程、控制队列或隐藏重试。

## 定位

节点系统是 AMVision 的可组合能力边界。平台通过统一 NodeDefinition、Node Catalog、payload contract 和执行器，把 Core Node 与安装的 Custom Node 放入同一张 Workflow 图。场景化协议、硬件桥接、行业规则和大型扩展模型优先进入 Node Pack，不写入平台主链。

节点分类和一级 pack 拆分见 [节点分类](node-taxonomy.md)，manifest 字段见 [Node Pack manifest](../../nodes/node-pack-manifest.md)。

## 组成

| 组成 | 职责 |
| --- | --- |
| Core Node | 平台稳定的逻辑、集合、图片、ROI、模型调用和控制节点 |
| Custom Node | Node Pack 提供的协议、设备、算法或行业节点 |
| Node Pack | manifest、Catalog、Python handler、依赖和资产的分发单元 |
| Node Catalog | 前后端共享的节点、端口、参数和能力目录 |
| Runtime Registry | 把 `node_type_id` 映射到可信 Python handler |
| Workflow Executor | 按图、结构节点和 enabled 状态调度 handler |

## 依赖方向

```text
manifest + catalog
       ↓ load / validate
NodeCatalogRegistry + RuntimeRegistry
       ↓
Workflow Template → Executor → Node handler
       ↑                    ↓
frontend editor       payload / result
```

- 前端只消费 Catalog，不复制 Python 节点定义。
- Template 保存节点实例、参数、边、分组和 UI state，不内嵌完整 NodeDefinition。
- 执行器按 payload type 检查连线与运行输入，节点不自行修改图结构。
- Node Pack 不直接拥有 Task、ModelVersion、Deployment 或 Workflow Runtime 等平台资源。

## Core 与 Custom 边界

Core 保留：

- 通用图执行、集合、条件、结构控制和 payload bridge。
- 标准图片引用、ROI、结果类型和模型 Deployment 调用。
- Node Pack 生命周期、版本、Catalog 合并和错误映射。

Node Pack 承担：

- OpenCV 专项算法、YOLOE、SAM3 等可选能力。
- HTTP、数据库、PLC、目录、USB/UVC、厂商 SDK 和 MES 集成。
- 客户或行业特定的规则、结果变换和回调。

相机、PLC、传感器和机械臂驱动不是核心平台能力。需要直连时由明确安装和启用的 Node Pack 实现。

## Manifest 与依赖

每个 pack 至少声明：

- `id`、SemVer `version`、category 和 display metadata
- capabilities 与 pack dependencies
- workflow catalog 和 backend entrypoint
- config schema、timeout 与 `enabledByDefault`
- 平台/Python/操作系统或厂商 runtime 的兼容范围

依赖必须显式且范围窄。缺少或版本不匹配时，只让依赖该 pack 的能力失败并给出明确原因，不通过隐式顶层 import 让无关节点失效。

## 可信执行模型

本地工业视觉部署把 Node Pack 的安装与启用视为使用者已经完成的信任选择：

- Core、内置和第三方节点使用同一套进程内 handler 调用。
- Preview 在 backend-service 内直接执行可信节点。
- 正式 Workflow App 在长期 Runtime worker 内直接执行节点。
- 正常节点调用不创建 per-node 进程，不经过跨进程 Mailbox，也不维护 permission scope。
- 一次性安装校验可以在辅助进程检查 import 和 handler 注册，但不进入执行热路径。

Workflow Runtime worker、Deployment 常驻进程和后台 Worker 是服务生命周期与故障恢复边界，不是节点权限沙箱。未经信任的代码必须使用独立服务或操作系统级 container/sandbox，不用 manifest 字段伪装成安全隔离。

## Node Pack timeout

Node Pack manifest 的 `timeout` 固定包含 `defaultSeconds`、`maxSeconds` 和 `killGraceSeconds`。当前没有节点实例级 override；`maxSeconds` 只校验 `defaultSeconds` 不越界。HTTP、数据库、相机等节点参数中的 timeout 是业务 I/O timeout，不能覆盖执行器 timeout。

有效执行 deadline 是 Workflow 剩余时间与 `defaultSeconds` 的较小值。Workflow 总 deadline 更早时保留 Workflow 总超时语义；Node Pack deadline 更早时返回 Node Pack 节点超时语义。

Preview 保持最低开销：

- execution context 向 handler 提供 monotonic deadline 和 cancellation Event；
- handler 可在连接等待、循环或分批处理的安全点协作退出；
- 不可协作的可信 Python handler 不能在同进程中安全强杀，返回后执行器仍会把本次 Preview 收敛为超时；
- 不建立 Preview worker 队列、每节点线程或每节点子进程。

正式 Runtime 的强制边界如下：

1. 每个 worker generation 创建一个新的 `multiprocessing.Event`，分派 Run 前由 manager 清理。
2. 只有能按 pack id 和精确版本解析 timeout policy 的 Node Pack handler 才通过现有 response queue 发送 `node-started` / `node-ended`；Core Node 不发送这组控制消息。
3. 每次实际 handler 调用使用一个 32 位十六进制 `node_invocation_id`。ForEach 重复调用和 Parallel 并行调用分别登记，互不覆盖。
4. manager 在一个 invocation map 中观察最早 deadline，不创建每节点 timer。第一次超时原因一经固化便不能被迟到的 `node-ended` 清除；其他并行超时只能缩短强制终止时刻。
5. 到期时 manager 设置共享 Event，取消整个 Run。`killGraceSeconds` 到期仍无结果时终止该 generation，持久化 `timed_out` 和 `runtime.node_timed_out`，再按 Runtime 的 `desired_state` 自动拉起新 worker。
6. 超时 Run 不自动重放，避免重复执行文件写入、PLC、HTTP 回调等有副作用节点。旧 generation 的生命周期消息和 Event 不能作用于新 generation。

生命周期消息只属于控制面，不进入节点 payload。图片继续走 LocalBuffer，timeout 协议不会复制图片或改变节点公开输入输出。

## 外部调用

HTTP、数据库、PLC、相机、ObjectStore 和模型资源由节点通过项目公开接口或对应 SDK 直接使用。节点负责：

- 明确连接、读取、执行和取消超时。
- 把外部错误映射为稳定节点错误。
- 对有副作用操作使用业务可识别的幂等键。
- 不加入隐藏排队、无限重试或吞掉错误的降级路径。

Trigger adapter 负责把外部事件转换成 Workflow Run 请求；业务图仍由稳定 Workflow Runtime 执行，监听器不复制一套图执行器。

## 参数与端口

- JSON Schema 是参数约束事实来源，UI schema 只描述控件呈现。
- `number` 应显式声明 `multipleOf` 和必要范围；未声明时前端只提供确定性 UI 步长回退，后端仍按 schema 校验。
- 输入输出端口必须声明版本化 payload type。
- 隐式类型转换禁止；需要转换时使用明确 bridge 节点。
- `node_type_id`、端口或 payload 的破坏性变化必须同步版本、示例、迁移和测试。
- 需要在运行时由其他节点或 App Entry 赋值的参数必须通过 `parameter_input_bindings` 显式绑定到可选 `value.v1` 输入端口；连接值覆盖固定参数，断开后恢复固定参数。
- 参数输入框与参数端口在编辑器中共存。未声明绑定的参数保持固定值，不根据名称或 schema 自动暴露端口。
- Parallel、ForEach、Selection 的执行计划参数以及资源、安全和 timeout 参数默认不得动态绑定。

详细契约、运行时优先级和验收门禁见 [Workflow 动态参数输入实施基线](../../development/workflow-dynamic-parameter-input-implementation.md)。

### 通用参数编辑器

节点不能通过 `node_type_id` 在前端硬编码专用参数面板。需要比基础 string、number、boolean 或 JSON 文本框更明确的编辑方式时，由 parameter schema 的 `x-amvision-ui.widget` 声明受控控件类型，Catalog 编译为稳定 `NodeParameterUiField.widget` 后由编辑器统一渲染。未声明时固定使用 `auto`。

`color-map` 用于 `名称 → #RRGGBB` 的通用颜色映射。参数本身必须继续使用 JSON object，键名是业务关联事实，行位置和画布位置没有运行时语义。schema 应同时声明 `propertyNames` 和 `additionalProperties`，颜色值保留 `^#[0-9A-Fa-f]{6}$` 校验。例如：

```json
{
  "type": "object",
  "propertyNames": {
    "type": "string",
    "minLength": 1,
    "title": "Class Name"
  },
  "additionalProperties": {
    "type": "string",
    "title": "Color",
    "format": "color",
    "pattern": "^#[0-9A-Fa-f]{6}$"
  },
  "default": {},
  "x-amvision-ui": {
    "widget": "color-map"
  }
}
```

编辑器以紧凑摘要显示颜色数量和色块，在独立编辑层中按键名增删和选色；只有点击应用才原子写回参数。空键、重复键、非字符串值和错误 HEX 必须阻止提交，高级 JSON 编辑也不得静默接受重复键。参数端口连接后控件只读，连接值仍按统一优先级完整覆盖固定 object，不执行隐式合并。Draw Regions、检测框、分割区域、Pose、OBB 和后续状态颜色节点复用同一控件及 object 契约。

### 文本、JSON 与文件输入组合

App Entry 输入进入图以后继续使用现有版本化 payload，不创建按 binding id 命名的专用数据类型。通用组合规则如下：

- `text.v1` 通过 `core.logic.text-to-value` 显式取得正文字符串，再进入 `value.v1` 字符串节点；
- `core.logic.string-concat` 只拼接两个字符串，不解析占位符，也不把数字、布尔、对象或数组隐式转成字符串；
- `core.logic.scalar-to-string` 只显式转换字符串、有限数字和布尔值，`null`、对象和数组必须选择其他明确节点；
- `value.v1` 对象通过 Extract Value Field、Object 和 List 节点读取或重组，字段路径和其他运行时参数仍通过显式参数端口覆盖；
- `file-ref.v1` 只有经过 File Read Text、File Read JSON 等有界节点才读取内容；`file-refs.v1` 可以按动态索引取单项，也可以只导出有序元数据列表；
- 不提供 `value.v1 → file-ref.v1` 反向转换，避免普通 JSON 伪造 ObjectStore 文件引用。

`String Value`、`Number Value` 和 `Boolean Value` 是无输入的固定值源，不承担转换或拼接。运行时数据处理由独立纯函数节点完成，避免固定参数和连接值优先级重复。

### 确定性对象与列表装配

Workflow 不得用多输入端口的数组位置推断字段名、更新路径、覆盖方向或列表序号。节点在画布中的坐标、拖动顺序和 Template JSON 数组顺序都不是业务数据。通用结构节点采用以下显式契约：

- `core.logic.object-field` 把一个顶层字面量 `key` 和一个 `value.v1` 封装为不可拆分的 `object-field.v1`；`key` 可以是固定参数，也可以由可选参数端口动态提供，不把点号解释为嵌套路径。
- `core.logic.object-build` 只接收 `object-field.v1` 集合和可选静态 `fields`。字段重复时明确失败，不用连线先后决定覆盖结果。
- `core.logic.object-set-path` 每次只按一个明确 `path` 更新一个值；多个更新通过节点串联表达执行顺序。
- `core.logic.object-merge-pair` 使用固定的 `Base` 与 `Overlay` 端口表达覆盖方向；冲突策略必须显式选择。
- `core.logic.list-item` 把一个非负 `index` 和一个 `value.v1` 封装为 `list-item.v1`；`core.logic.list-build` 按显式 index 排序，重复或不连续时明确失败。

`object-field.v1` 和 `list-item.v1` 是通用 Core payload，不属于某个业务节点；两者都可以通过 Payload To Value 显式进入普通 `value.v1` 对象处理链。执行器保存的输入顺序只用于执行既有端口语义，不得作为字段和值等业务关系的表达方式。

旧版 `core.logic.object-create`、`core.logic.object-update`、`core.logic.object-merge` 和 `core.logic.list-create` 只用于既有发布快照兼容执行，在新节点面板中隐藏。新建或重新发布的 Workflow 必须迁移到上述显式节点，不能继续生成位置配对结构。

### 通用日期时间模板

节点需要把运行时本地时间写入文本、目录或文件名时，统一使用 `backend.nodes.render_date_time_template`，不得在各节点内重复实现 `strftime`、正则替换或专用 token。大括号表示一个日期时间格式块，不表示固定字符串；块可以组合，也可以拆成多个块，例如：

- `{YYYYMMDDhh}`
- `{DDMMYYYY hhmmss}`
- `{YY}`、`{YYY}`、`{Y}`
- `saveimage-{YYYY}-{MM}-{DD}-{hh}-{mm}-{ss}-{SSS}.jpg`

字段大小写敏感。`Y` 最多四位，`M`、`D`、`h`、`m`、`s` 最多两位，`S` 最多三位；短字段从固定宽度值右侧取对应位数，例如 2026 年的 `{YY}` 为 `26`，21 日的 `{D}` 为 `1`。因此 `{DDD}`、`{YYYYY}`、`{MMM}` 和 `{SSSS}` 必须明确失败。一个模板中的所有块使用一次性捕获的同一时间点；调用节点可以通过显式 `context` 映射复用 `{node_id}` 等上下文占位符。

通用解析器允许日期时间文本常用的空格、`T`、`-`、`_`、`.`、`:` 和 `/` 分隔符。具体节点仍必须在展开后执行自身边界校验，例如 Image Save 文件名禁止目录分隔符和 Windows 非法字符，保存目录则可以使用 `/` 形成日期层级。

`core.logic.format-date-time` 把通用日期时间模板公开为 `value.v1` 字符串节点。节点每次执行只捕获一个 runtime 主机本地时间点；需要多个下游节点使用完全相同的时间文本时，应复用同一个节点输出。`core.logic.string-concat` 会原样保留日期块，因此也可以先拼接，再交给明确支持日期模板的下游节点展开。

### Image Save 保存契约

`core.io.image-save` 使用三个边界清晰的参数：`save_directory` 只负责保存目录，`file_name` 负责完整单级图片文件名，`overwrite` 决定覆盖或自动编号。三个参数同时提供显式可选 `value.v1` 输入端口，连接值优先，未连接时使用节点保存的固定值。目录和文件名共用上述通用日期时间模板与同一个时间点；文件名既可以是 `fixed.jpg`，也可以是 `saveimage-{YYYY}-{MM}-{DD}-{hh}-{mm}-{ss}-{SSS}.jpg`。

关闭覆盖时，节点先尝试原名，再依次尝试扩展名前的 `_001`、`_002`。最终创建必须使用原子不覆盖操作，多个 workflow/runtime 同时写入同一目录时不能通过“先 exists、后覆盖写”的竞争窗口丢失图片。该策略不增加 workflow 调用队列或等待，最终实际路径继续通过 `saved_output.object_key` 或 `saved_output.local_path` 返回。

## App Entry 多类型输入

App Entry 是公开 binding 边界，不是新的节点执行器。当前 `request_image_ref`、`request_image_base64` 等名称只是可重命名的默认 binding id；节点连线和 Runtime 校验仍由 `image-ref.v1`、`image-base64.v1`、`value.v1` 等版本化 payload 决定。

当前 Runtime JSON 请求可以同时提交多个已声明 binding，结构化值使用 `value.v1`。HTTP Runtime、Trigger、LocalBuffer、前端和 .NET SDK 的已交付边界与验证记录见 [Workflow App Entry 多类型输入实施基线](../../development/workflow-app-entry-input-implementation.md)。

## Parallel、ForEach 与节点组

- Parallel 和 ForEach 是 Core 结构节点的执行语义，不由普通 Node Pack 自行实现调度器。
- `max_concurrency` 只限制显式分支或循环项，不自动并行整张 DAG。
- 普通节点不提供 `parallel` 开关；同类节点能否同时执行由显式 Parallel 边界和 NodeDefinition `concurrency_policy` 共同决定。
- `Payload To Value` 能接收的正式结构化 payload 应具有对称的 `Value To ...` 恢复路径，确保 Parallel、ForEach 和集合节点不会形成只能生成、不能继续消费的数据孤岛。
- 画布节点组只影响布局与成员的最终 enabled 状态，不创建运行时子图或隔离进程。

详见 [Parallel 分支](parallel-branches.md)、[视觉并行与模型批量节点设计](vision-parallel-and-model-batch.md)与 [Workflow 编辑器](editor.md)。

## 说明节点与执行边界

Workflow 说明节点用于画布内文档，不属于 Core Node 或 Custom Node：不注册 NodeDefinition、不实现 handler、不声明 payload 和 runtime requirements，也不进入拓扑、Parallel、ForEach、Selection、Node Pack 依赖或 node record。

说明节点作为 `WorkflowGraphTemplate.notes` editor artifact 随 App Version 固化。修改说明会改变版本快照 fingerprint，但不会改变公开输入输出契约、Trigger mapping、SDK 调用格式或 Runtime 执行结果。说明内容不允许连接端口，也不能用说明节点替代 String Value、Text To Value 或其他实际文本数据节点。

详细字段、安全渲染、节点组成员关系和验收记录见 [Workflow 说明节点实施基线](../../development/workflow-note-node-implementation.md)。当前代码和真实 Workflow App 验收已完成。

## 生命周期

Node Pack 安装和变更遵循 staging、校验、原子激活与恢复：

1. 校验 ZIP 路径、manifest、版本、依赖和 Catalog。
2. 在 staging 中检查 Python entrypoint 与 handler 注册。
3. 原子切换活动版本并重载 Catalog/Registry。
4. 失败时恢复原版本；启动时先收敛未完成事务。
5. disable 或 rollback 后，现有 Workflow 必须在 validate/start 时得到明确缺失能力错误。

生命周期 API 与前端目录页使用同一事实，不直接手工修改已激活 manifest。

## 验收

- Core 与 Custom Node 在 Preview 和正式 Runtime 中使用同一 payload/参数语义。
- Catalog、Runtime Registry、前端端口和保存文档一致。
- 节点执行不产生 per-node 进程启动延迟或大图 Base64 复制。
- timeout、取消、异常和 Runtime 停止能释放文件、连接与 LocalBuffer 引用。
- Node Pack 超时只产生一个权威 `timed_out` 结果，整代 worker 自动恢复且不重放原 Run。
- pack 安装、禁用、升级、回滚和启动恢复保留明确版本与错误记录。
- 缺失外部依赖不会让无关 pack 或 backend-service 启动失败。

扩展开发入口见 [节点扩展](../../nodes/README.md)。
