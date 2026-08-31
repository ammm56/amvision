# ADR-0010：Workflow App Entry 多类型输入契约

## 状态

已接受并实施。统一 payload/节点/校验、App Contract v2、ObjectStore streaming、Runtime/Preview multipart、App Entry、typed Preview、local-shared-memory event-only v2、高性能 Trigger capability 校验和 .NET 双调用面强类型 API 已完成。HTTP Runtime 与高性能 Trigger 的调用面边界已经固定，并通过实际 Workflow App、Runtime、Trigger 和 SDK 组合调用验收。实施顺序、payload 形状和验收矩阵见 [Workflow App Entry 多类型输入实施基线](../development/workflow-app-entry-input-implementation.md)。

## 背景

Workflow 的外部调用除了图片，还需要表达结构化 JSON、原始文本、普通文件、多文件，以及这些输入的任意组合。现有 Runtime 请求模型本身不是单图片模型，但编辑器、multipart、SDK 和 Trigger 的能力不完整，容易产生三类错误方向：

- 把 `request_json`、`request_file` 等公开字段名设计成新的 payload type；
- 为 JSON + 图片、JSON + 文件等组合建立应用专用节点；
- 把普通文件塞入 Base64 JSON、LocalBuffer 或 Runtime 进程内存，扩大复制和生命周期风险。

需要固定公开 binding、节点 payload 和 HTTP/SDK transport 的分层关系，同时保持旧图片 App、不可变 App Version 和本机高性能图片数据面的兼容性。

## 决策

### 1. Binding、payload 和 transport 分层

`request_*` 是 Application 的默认公开 `binding_id`，可以在发布前重命名。端口兼容性由版本化 `payload_type_id` 决定；JSON body、multipart、ZeroMQ 和 local-shared-memory 是 transport。三层不能互相替代，也不能根据字段名猜测 payload。

App Entry 继续是画布公开边界，不增加另一套 Runtime 或执行器。编辑器快捷入口只创建普通通用输入节点、模板输入和 Application binding。

### 2. 多输入使用独立 binding

JSON + 图片、JSON + 文件、文本 + 图片 + 文件均由同一请求中的多个独立 binding 表达。核心平台不增加组合 payload、组合输入节点或工位/应用专用节点。

结构化 JSON 复用现有 `value.v1`。新增原始文本 `text.v1`、不可变单文件引用 `file-ref.v1` 和有序多文件引用 `file-refs.v1`。原始 JSON 文本和 JSON 文件必须通过显式解析节点转换为 `value.v1`，不能自动解析。

### 3. 文件使用 ObjectStore 引用

公开文件 payload 只携带 Project 可验证的不可变 ObjectStore 引用、文件名、MIME、长度、checksum 和 immutable version。文件 bytes、文件 base64、本机绝对路径和 Runtime 临时路径不进入规范公开 payload。

multipart 文件按块写入 staging，同时计算长度和 SHA-256；全部 binding 校验成功后原子发布。ObjectStore 增加流式不可变写入能力，后端和 .NET SDK 的新文件主链不能执行全文件 `bytes`、`File.ReadAllBytes` 或无条件 `MemoryStream` copy。

LocalBuffer 继续只负责图片数据面。JSON 和文本保持 inline；普通文件使用 ObjectStore snapshot。不能为复用 mmap 而把普通文件伪装成图片。

多类型输入不改变同步 Runtime admission。上传处理只负责当前已接收请求的解析和暂存，不增加业务等待队列、容量等待、自动重试或隐式重放；Runtime 或上传容量不足时立即返回稳定错误。

### 4. 所有入口共用输入校验

HTTP JSON、HTTP multipart、Preview、Trigger 和 SDK 规范化后的请求共用一个应用层输入校验器。正式 Runtime 依据不可变 App Version 冻结的输入契约检查 unknown/required binding、payload schema、binding schema、大小、数量、MIME、Project、version 和 checksum。

校验不执行类型强制转换、扩展名推断、自动 JSON parse 或未知字段丢弃。失败返回稳定错误码和不包含敏感值的结构化位置详情。

### 5. 新契约显式版本化

现有 `amvision.workflow-app-contract.v1` 保持可读和可运行，不在读取时静默增加严格校验。多类型输入实现发布 `amvision.workflow-app-contract.v2`，冻结外层 payload schema、binding request schema、允许 transport、MIME、inline/file 大小、文件数量和 charset。

v1 到 v2 的比较先规范化旧契约；任何新增拒绝行为按破坏性变化处理。旧 Runtime 不必升级，重新发布和切版继续使用现有显式 breaking override、revision 和 generation CAS。

### 6. Transport 保持确定性

JSON 请求继续支持 `input_bindings` 包装字段或公开 binding 顶层字段，但不能混用。multipart 使用 `input_bindings_json` 保存非文件输入，文件字段名必须等于 binding id；单文件只允许一个 part，多文件通过重复同名 part 保留顺序。

同一 binding 不能同时出现在 JSON 和文件 part。未知字段、普通非文件 form part、类型不匹配和数量冲突直接失败，不自动 fallback 到 Base64、临时文件或其他 transport。

### 7. HTTP Runtime 与高性能 Trigger 使用不同能力面

HTTP Runtime 是通用调用面，支持 `image-ref.v1`、`image-base64.v1`、`value.v1`、`text.v1`、`file-ref.v1` 和 `file-refs.v1`。JSON 请求负责 inline payload 和已有引用，multipart 请求负责图片、单文件和多文件的流式上传；同一请求可以组合多个独立 binding。

ZeroMQ 与 local-shared-memory 是高性能 Trigger 调用面，只允许映射 `image-ref.v1`、`value.v1` 和 `text.v1`。调用方图片 bytes 分别通过 ZeroMQ binary frame 或 LocalBuffer 传输，由服务端生成 `image-ref.v1`；JSON 和文本位于小型事件 payload。高性能 Trigger 不映射 `image-base64.v1`、`file-ref.v1` 或 `file-refs.v1`，也不增加文件 staging、普通文件 binary frame 或普通文件 LocalBuffer 语义。

local-shared-memory v1 的必填图片语义保持不变。纯 JSON/文本调用使用显式 event-only v2，跳过图片 PREPARE、LocalBuffer allocation 和 lease 状态机；不能把 v1 image 改成隐式可空或为空事件分配假图片。ZeroMQ 和 local-shared-memory 的 transport 限制必须在 TriggerSource 配置、SDK 调用前校验和 Runtime 权威校验三处保持一致。

`.NET` SDK 同时覆盖两套调用面，但 API 不混用：HTTP Builder 支持六类输入；高性能 Trigger Builder 只支持 JSON 和文本，图片由对应 transport 的图片调用方法提供。两套 Builder 都不得隐藏排队、重试、等待或 transport fallback。

## 未采用方案

- 为每种输入组合增加 `json-image-request.v1`、`json-file-request.v1` 或专用节点：组合数量无界，且破坏通用编排。
- 新增与 `value.v1` 重复的 `json.v1`：同一结构化值形成两套 bridge 和校验语义。
- 把普通文件以内联 Base64 放入 `value.v1`：增加传输体积、序列化成本和 Runtime Working Set。
- 用 LocalBuffer 或图片 binary frame 传普通文件：混淆 allocator、lease、解码和生命周期边界。
- 根据文件名、扩展名、MIME 或内容自动选择解析节点：产生不可见行为和调用差异。
- 后端或 SDK 先完整缓冲文件再上传：大文件和并发调用下产生额外完整副本，不满足长期稳定运行要求。
- 为旧 v1 App Version 静默启用 v2 严格校验：会改变不可变发布物的生产行为。

## 影响

- Workflow App 可以用通用 binding 组合 JSON、文本、图片、单文件和多文件，不增加应用专用节点；具体调用入口仍受 transport capability 限制。
- Node Catalog、App Contract、Runtime、Preview、Trigger、ObjectStore、前端和 SDK 必须共享同一 payload 与限制定义。
- 文件上传增加 staging、流式 checksum、不可变发布、引用保留和启动清理职责，但大文件不进入 Runtime command 或数据库 JSON。
- App Contract v2 和新 payload 属于显式公开契约变化，需要兼容比较、SDK contract test 和旧 v1 回归门禁。
- local-shared-memory v1 图片热路径不受影响；纯结构化事件通过单独版本扩展，不向图片状态机加入隐藏分支。ZeroMQ/local-shared-memory 不承担 Base64 图片或普通文件输入。
