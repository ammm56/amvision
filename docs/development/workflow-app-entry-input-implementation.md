# Workflow App Entry 多类型输入实施基线

> 状态：阶段 1—6 的统一 payload/节点/校验、App Contract v2、ObjectStore streaming、Runtime/Preview multipart、App Entry、typed Preview、现有 .NET HTTP 请求、local-shared-memory event-only v2 和真实 Workflow App 验证已完成。阶段 7—9 的高性能 Trigger capability 校验、.NET 双调用面强类型 API 和补充全链验收处于待实现状态。代码、OpenAPI、Catalog 和持续测试是实现状态的最终证据。

不可变架构取舍见 [ADR-0010：Workflow App Entry 多类型输入契约](../decisions/ADR-0010-workflow-app-entry-multi-input-contract.md)。本文只维护实现顺序、具体 contract 和验证门禁。

## 文档目的

Workflow 调用不应被限制为每次只提交一张图片。一个公开 App 可以只接收 JSON，也可以同时接收 JSON、文本、图片、单文件或多文件。扩展必须继续使用通用节点和通用 payload，通过 Workflow 编排组合能力，不能为 `JSON + 图片`、`JSON + 文件` 等组合建立应用专用节点。

本文固定以下内容：

- App Entry 的公开 binding、payload type 和 wire transport 三层边界；
- JSON、文本、文件和多文件的统一 payload；
- JSON 与 multipart 请求的确定性解析、校验和 ObjectStore 生命周期；
- Runtime、Preview、Trigger、LocalBuffer、SDK 和前端使用同一输入契约的方式；
- 兼容性、内存、错误和验收规则。

## 阶段状态

| 阶段 | 范围 | 当前状态 |
| --- | --- | --- |
| 1 | payload、输入节点、共同校验、App Contract v2 | 已完成 |
| 2 | ObjectStore streaming 与 Runtime multipart | 已完成 |
| 3 | App Entry 前端与 typed Preview | 已完成 |
| 4 | .NET HTTP multipart 组合请求与 streaming | 已完成 |
| 5 | local-shared-memory event-only v2 | 已完成 |
| 6 | 真实 App 复制、版本切换、HTTP/SDK/LocalBuffer 稳定性审计 | 已完成 |
| 7 | ZeroMQ/local-shared-memory 高性能输入 capability 固定与配置校验 | 待实现 |
| 8 | .NET HTTP 全量 Builder 与高性能 Trigger Builder 分层 | 待实现 |
| 9 | 两套调用面的真实组合、拒绝矩阵和长期稳定性验收 | 待实现 |

每个阶段只有在代码、迁移、契约测试和真实链路验证同时完成后才能改为已完成。部分代码落地不能提前修改本文顶部的“尚未实现”结论。

## 核心结论

### `request_*` 是 binding id，不是 payload type

`request_image_ref`、`request_json`、`request_text` 和 `request_file` 是编辑器创建输入时使用的默认公开 `binding_id`。这些 id 可以在发布前重命名，只负责标识一次 App 调用中的字段。

端口是否能连接、Runtime 应如何校验输入，由 `image-ref.v1`、`value.v1`、`text.v1`、`file-ref.v1` 等版本化 `payload_type_id` 决定。HTTP 使用 `application/json` 还是 `multipart/form-data` 则属于 wire transport。三层不得混用：

```text
公开字段名                 节点数据类型             调用传输
request_json       →       value.v1        →       JSON body
request_image_ref  →       image-ref.v1    →       JSON body 或 multipart file
request_file       →       file-ref.v1     →       JSON reference 或 multipart file
```

App Entry 是画布上的公开输入边界和编辑器能力，不新增另一套执行器。快捷入口只创建普通通用输入节点、公开模板端口和 Application binding。多类型输入不改变同步 Runtime admission，不新增业务等待队列、容量等待、自动重试或隐式重放。

### 两套调用面固定分工

App 可以同时公开六类输入，但 transport 不需要具有相同能力。最终边界固定为：

| 调用面 | 支持的默认 binding | 设计目的 |
| --- | --- | --- |
| HTTP Runtime | `request_image_ref`、`request_image_base64`、`request_json`、`request_text`、`request_file`、`request_files` | 通用 JSON、引用和 multipart 文件调用 |
| ZeroMQ Trigger | `request_image_ref`、`request_json`、`request_text` | 跨进程高性能图片和小型参数调用 |
| local-shared-memory Trigger | `request_image_ref`、`request_json`、`request_text` | 同机低复制图片和小型参数调用 |

表中的名称仍只是默认 binding id；Trigger 的实际允许类型是 `image-ref.v1`、`value.v1` 和 `text.v1`。高性能 Trigger 不绑定 `image-base64.v1`、`file-ref.v1` 或 `file-refs.v1`。HTTP Runtime 承担 Base64 图片、普通文件和多文件输入，不为 Trigger 增加文件 staging、额外 binary frame、普通文件 LocalBuffer 或大 payload mailbox。

### 多输入不产生组合类型

`JSON + 图片`、`JSON + 文件`、`文本 + 图片 + 文件` 都表示同一请求中存在多个独立 binding。禁止新增以下实现：

- `json-image-request.v1`、`json-file-request.v1` 等组合 payload；
- `JSON Image Input`、`Tray Request Input` 等场景专用节点；
- 根据扩展名、MIME 或内容猜测并自动解析文件的隐藏行为；
- 把普通文件伪装成图片写入 LocalBuffer。

需要解析 JSON 文本、读取 JSON 文件或解码图片时，Workflow 必须连接显式 bridge 节点。

## 当前能力与目标矩阵

| 默认 binding id | payload type | App Entry 节点或后续节点 | 状态 |
| --- | --- | --- | --- |
| `request_image_ref` | `image-ref.v1` | `Template Image Input` 或现有 Image Ref Coalesce | 已实现 JSON 引用、App Entry 和 Runtime/Preview multipart 图片上传 |
| `request_image_base64` | `image-base64.v1` | 现有 Image Base64 Decode | 已实现 |
| `request_json` | `value.v1`，其中 `value` 必须是 object | 现有 `Template Object Input` | 已实现快捷入口、binding schema 和统一校验 |
| `request_value` | `value.v1` | 现有 `Template Value Input` | 已实现高级快捷入口和 typed Preview |
| `request_text` | `text.v1` | `Template Text Input` | 已实现 |
| `request_file` | `file-ref.v1` | `Template File Input` | 已实现 |
| `request_files` | `file-refs.v1` | `Template Files Input` | 已实现 |

结构化 JSON 继续复用 `value.v1`，不再增加重复的 `json.v1`。原始 JSON 文本属于 `text.v1`，`.json` 上传文件属于 `file-ref.v1`；二者都必须通过显式节点解析成 `value.v1`。

所有快捷入口默认创建可选 binding。是否必填由 Application 明确保存，不根据节点类型或字段名隐式决定。

## Payload 设计

### 结构化 JSON

结构化 JSON 使用现有 `value.v1` 外层信封：

```json
{
  "value": {
    "threshold": 0.72,
    "station": "station-01",
    "options": {
      "save_debug_image": false
    }
  }
}
```

`request_json` binding 额外声明 `config.request_schema`，约束 `value` 内部对象。`Template Object Input` 继续保证 `payload.value` 是 object。任意 scalar、array 或 object 输入使用 `request_value`，但仍必须包在 `{"value": ...}` 中。

### 文本

新增 `text.v1`，第一版固定为 inline JSON：

```json
{
  "text": "line-01\nline-02",
  "media_type": "text/plain",
  "charset": "utf-8"
}
```

三个字段全部必填，避免依赖隐藏默认值。`text.v1` 表示原始文本，不自动执行 trim、JSON parse、CSV parse、模板替换或编码探测。

`text.v1`、`file-ref.v1` 和 `file-refs.v1` 的 JSON Schema 固定使用 `additionalProperties: false`。未知字段直接失败，不能被 Runtime 或节点静默丢弃。

### 单文件引用

新增 `file-ref.v1`。公开 Runtime 中的规范形状固定为受管理的不可变 ObjectStore 引用：

```json
{
  "transport_kind": "storage",
  "object_key": "runtime/inputs/workflow-runtime-1/request-1/recipe.json",
  "file_name": "recipe.json",
  "media_type": "application/json",
  "content_length": 1842,
  "checksum_algorithm": "sha256",
  "checksum": "<sha256 hex>",
  "immutable_version": "<object version>"
}
```

以上字段全部进入 payload 校验。`object_key` 必须属于当前 Project 可访问范围，调用方不能提交本机绝对路径。公开 payload 不接受完整文件 bytes、文件 base64 或 Runtime 临时文件路径。

如后续支持受信任的本地目录节点，`local-path` 必须是独立 payload 或显式 binding policy，只能在该节点声明的受控根目录内使用，不能成为 `file-ref.v1` 的默认降级路径。

### 多文件引用

新增 `file-refs.v1`：

```json
{
  "items": [
    {
      "transport_kind": "storage",
      "object_key": "runtime/inputs/workflow-runtime-1/request-1/a.json",
      "file_name": "a.json",
      "media_type": "application/json",
      "content_length": 1842,
      "checksum_algorithm": "sha256",
      "checksum": "<sha256 hex>",
      "immutable_version": "<object version>"
    }
  ],
  "count": 1
}
```

`items` 保留提交顺序，`count` 必须等于数组长度。单文件 binding 必须且只能得到一个文件；多文件 binding 可以通过同名 multipart 字段重复提交，并按 multipart 出现顺序生成 `items`。

## Wire 请求

### JSON body

Runtime 继续支持 `input_bindings` 包装形态和公开 binding 顶层形态，但同一个请求不能混用。多输入包装示例：

```json
{
  "input_bindings": {
    "request_json": {
      "value": {
        "threshold": 0.72
      }
    },
    "request_image_base64": {
      "image_base64": "<base64 image bytes>",
      "media_type": "image/png"
    }
  },
  "execution_metadata": {
    "source": "station-01"
  }
}
```

实现后，如果调用方已经持有受管理对象，可以在 JSON body 中直接提交 `image-ref.v1` 或 `file-ref.v1`。服务端仍校验 Project、不可变版本、长度和 checksum，不把任意 object key 当作可信输入。

### multipart/form-data

multipart 固定使用以下规则：

- `input_bindings_json` 保存全部 JSON、文本和已有对象引用；
- `execution_metadata_json` 保存执行元数据；
- `timeout_seconds` 保存显式同步超时；
- 文件字段名必须等于公开 `binding_id`；
- `request_image_ref` 文件转换为 storage `image-ref.v1`，`request_file` 转换为 `file-ref.v1`；
- `request_files` 通过重复同名字段形成有序 `file-refs.v1`；
- `image-base64.v1` 只用于 JSON 输入，不把 multipart 文件暗中转换成 base64；
- 同一 binding 不能同时出现在 `input_bindings_json` 和文件字段中；
- 未声明字段、普通非文件 form 字段、单文件 binding 的重复文件都直接失败，不猜测调用意图。

multipart 的 `object_key` 只由服务端生成。上传 `file_name` 只保留规范化 basename，拒绝路径分隔符、控制字符和空名称，不能参与服务端路径拼接。

组合请求示例：

```text
POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload
Content-Type: multipart/form-data

input_bindings_json = {
  "request_json": {"value": {"threshold": 0.72}},
  "request_text": {"text": "lot-001", "media_type": "text/plain", "charset": "utf-8"}
}
request_image_ref = @source.bmp
request_file = @recipe.json
```

同步和异步 Runtime 使用同一个 multipart parser、输入校验器和 payload 构造器，不能形成两套语义。

## 上传、ObjectStore 与内存边界

目标链路固定为：

```text
HTTP / SDK / Trigger adapter
        ↓
解析 request envelope
        ↓
分块写入 ObjectStore staging，同时计算长度与 SHA-256
        ↓
校验 binding、payload、schema、MIME、数量和大小
        ↓
原子发布不可变 object，并生成规范 input_bindings
        ↓
Workflow Runtime → App Entry 输入节点 → 下游通用节点
```

实现约束：

- ObjectStore 增加 stream 写入端口，不能把上传文件完整读入 `bytes` 后再发布；
- 上传按固定大小分块处理，并在写入过程中计算 checksum；
- 全部文件暂存和全部 binding 校验成功后才能创建 Run；任一输入失败时清理本次 staging，不留下半发布 Run；
- staging 使用 request id 隔离；原子发布后的临时输入记录 owner、引用状态和 `retention_until`，Run 创建失败、服务重启或超期时只清理未被引用的对象；
- content-addressed object 可能被多个 Run 复用，清理必须依据引用/保留记录，不能根据单次请求失败直接删除共享 object；
- 数据库、Runtime command 和节点记录只保存文件引用与必要元数据，不保存完整文件 bytes；
- multipart 大小、单文件大小、文件数量、inline JSON 大小和文本大小都有可见的 binding policy 与平台硬上限；
- `application/octet-stream` 可以作为调用方明确提交的 MIME，服务端不根据扩展名暗中改变 MIME；
- MIME 是调用元数据，不单独构成安全证明；binding allowlist 匹配声明值，图片解码器和显式文件读取节点仍校验真实内容格式；
- 文件读取节点通过 ObjectStore snapshot 读取固定版本，并在节点结束、取消和异常路径关闭 stream。

ObjectStore 已提供分块 staging、SHA-256 计算和不可变原子发布；.NET multipart builder 使用 `StreamContent` 和每次发送独立创建的 stream。`File.ReadAllBytes`、无条件 `MemoryStream` copy 和隐藏重试不进入新文件调用主链。

LocalBuffer 继续只承载图片数据面，不承载 JSON、文本和普通文件。大文件通过 ObjectStore snapshot 共享，避免长期 Runtime Working Set 随上传大小线性增长。

## 统一输入校验

新增应用层 `WorkflowInputValidator`，由 HTTP JSON、HTTP multipart、Preview、Trigger、SDK 转换后的 Runtime 请求共同调用。校验顺序固定为：

1. 拒绝未知 binding，并检查 required binding；
2. 按不可变 App Version 检查 `payload_type_id`；
3. 正式 Runtime 按不可变 App Version 冻结的 `payload_schema` 校验外层 payload；编辑态 Preview 按本次固定 snapshot 对应的 Catalog schema 校验；
4. 对 `request_json` 的 `payload.value` 应用 binding 的 `request_schema`；
5. 校验 inline 大小、JSON 深度、文本长度、文件数量、文件大小和允许 MIME；
6. 校验 storage ref 的 Project、不可变版本、长度和 checksum；
7. 全部通过后才把规范 `input_bindings` 交给 Runtime。

不得通过字符串转数字、scalar 包装、扩展名推断、自动 JSON parse 或丢弃未知字段来“修复”请求。错误详情至少包含 `binding_id`、`payload_type_id`、JSON Pointer 和失败的 schema keyword，但不回显 base64、文件内容或敏感 JSON 值。

计划采用以下稳定错误码，并同时写入 OpenAPI、SDK contract test 和 API 文档：

- `workflow_input_unknown_binding`；
- `workflow_input_required_binding_missing`；
- `workflow_input_payload_schema_invalid`；
- `workflow_input_multipart_binding_conflict`；
- `workflow_input_file_count_exceeded`；
- `workflow_input_file_size_exceeded`；
- `workflow_input_file_media_type_rejected`；
- `workflow_input_object_reference_invalid`，通过 details 区分 missing、stale、version 或 checksum；
- `workflow_input_upload_failed`。

## 公开 App 契约与兼容性

当前 `amvision.workflow-app-contract.v1` 已冻结 binding id、payload type、required 和 config。多类型输入落地时发布 `amvision.workflow-app-contract.v2`，在每个 input 中保存规范化 `request` 策略，至少包括：

- 外层 `payload_schema` 和可选的 `request_schema`；
- `allowed_media_types`；
- `max_inline_bytes`、`max_file_bytes` 和 `max_files`；
- 明确的 `transports`，例如 JSON reference、inline JSON 或 multipart upload；
- 文本 charset 规则。

v2 的公开 input `payload_schema` 使用 closed-object 规则；包括 `value.v1` 外层在内，未声明的外层字段直接失败。该规则只约束 v2 公开请求，不回写或改变旧 v1 App Version 和 Workflow 内部边的 legacy `value.v1` 行为。

旧 v1 App Version 保持可读和可运行，不在读取时静默改写为 v2，也不施加 v2 新增的严格 schema 和文件 policy。旧 App 重新发布时明确生成 v2，并使用同一份规范化契约驱动 Runtime、编辑器、OpenAPI 示例和 SDK 配置。正式 Runtime 不在执行时回读当前 Catalog schema，避免 Catalog 更新改变已发布版本的输入行为。

v1 到 v2 比较先把 v1 binding 映射为 legacy validation profile；如果 v2 schema 或 policy 会拒绝过去可能通过的请求，则报告破坏性变化并要求现有显式 override。契约 `format_id` 变化本身不单独判定为破坏性，实际拒绝集合的变化才是比较依据。现有 Runtime 可以继续固定 v1 revision，不要求批量重发版本。

兼容性固定为：

- 新增 optional input：兼容；
- 新增 required input、删除 input、修改 binding id 或 payload type：破坏性；
- optional 改为 required：破坏性；
- 收紧 JSON Schema、减少 MIME、降低大小/数量上限：破坏性；
- 放宽 schema、增加 MIME 或提高上限：兼容，但仍受平台硬上限约束；
- `value.v1` 改成 `text.v1` 或 `file-ref.v1`：破坏性，不能自动迁移。

第一版 schema 兼容比较采用保守策略：不能证明是放宽的变更按破坏性处理。Runtime 切版仍使用现有 generation CAS 和显式 breaking override，不在调用时动态猜测契约版本。

## 通用节点与 bridge

继续复用：

- `core.io.template-input.value`；
- `core.io.template-input.object`；
- `core.io.template-input.image`；
- 现有 Image Base64 Decode 和 typed value bridge。

新增通用节点：

- `core.io.template-input.text`：`text.v1 → text.v1`；
- `core.io.template-input.file`：`file-ref.v1 → file-ref.v1`；
- `core.io.template-input.files`：`file-refs.v1 → file-refs.v1`；
- `core.logic.text-to-value`：只把 `text` 字符串包装为 `value.v1`，不解析 JSON；
- `core.logic.json-parse-text`：显式把 JSON 文本解析为 `value.v1`；
- `core.logic.value-to-json-text`：按明确参数把 `value.v1` 序列化为 `text.v1`；
- `core.io.file-metadata`：只读取引用元数据；
- `core.io.file-read-text`：显式 charset 和最大读取长度，输出 `text.v1`；
- `core.io.file-read-json`：显式 charset、最大读取长度和可选 JSON Schema，输出 `value.v1`；
- `core.logic.file-refs-get-item`：从 `file-refs.v1` 按索引恢复 `file-ref.v1`。

文件输入节点只透传引用，不读取、解析或缓存文件内容。`Read JSON File` 输出 `value.v1`，从而直接接入已有逻辑、集合、Parallel、ForEach、HTTP 和模型参数节点。每个正式结构化 payload 都要提供对称 bridge，避免产生只能由一个节点识别的数据孤岛。

## Trigger 与 LocalBuffer

高性能 Trigger 的协议中立事件 `payload` 携带 JSON 和文本，input mapping 按显式 dotted path 映射到公开 binding。统一规则为：

- JSON 和文本直接放入事件 payload；
- 图片继续通过 LocalBuffer 或现有 ZeroMQ binary frame 转成 `image-ref.v1`；
- `image-base64.v1`、`file-ref.v1` 和 `file-refs.v1` 只通过 HTTP Runtime 调用，不进入高性能 Trigger mapping；
- TriggerSource mapping 与 HTTP 调用最终必须经过同一个 `WorkflowInputValidator`；
- Trigger adapter 不根据内容生成未声明 binding，也不自动 fallback transport。

local-shared-memory 图片 v1 的 `WorkflowTriggerPrepareV1.image` 保持必填；`WorkflowTriggerRequestV1.payload` 可在同一次图片调用中同时携带 JSON 和文本。event-only v2 已作为独立操作实现，纯 JSON/文本请求直接进入 REQUEST phase，跳过图片 PREPARE、LocalBuffer allocation 和 lease 状态机。v1 没有把必填 image 改成可空，也不会为空事件分配假图片 slot。

ZeroMQ JSON 事件继续支持纯结构化 JSON/文本请求。普通文件不得复用图片 binary frame，local-shared-memory 也不得为普通文件分配 LocalBuffer。`Invoke*ImageBase64` 只表示 SDK 接受 Base64 作为图片来源并解码成图片 bytes，最终仍写入 `request_image_ref`；该方法不表示 Trigger 支持 `request_image_base64`。

## 前端编辑器与 Preview

App Contract 面板新增以下通用快捷入口：

- JSON Parameters；
- Value；
- Text；
- File；
- Files。

现有 image-only composable 应收敛为通用 request input 管理，不为每种组合建立一套布局和保存逻辑。每个 binding 面板显示并保存：

- binding id、显示名、说明和 required；
- payload type；
- JSON Schema 或示例；
- 文本 charset；
- 文件 MIME、单文件大小、数量限制；
- 支持的 JSON reference / multipart transport。

Preview 输入组件按 payload type 渲染：结构化 JSON 编辑器、纯文本输入、多行文本、单文件选择、多文件选择和图片选择。生成请求示例时同时给出 JSON、multipart、curl 和 .NET SDK 形态。前端只消费已发布契约，不复制后端 payload schema。

## SDK 设计

### HTTP Runtime Builder

.NET HTTP SDK 使用组合请求 builder，在同一请求中支持：

- `AddJson(bindingId, value)`；
- `AddText(bindingId, textPayload)`；
- `AddImage(bindingId, streamFactory, fileName, mediaType)`；
- `AddImageReference(bindingId, imageRef)`；
- `AddImageBase64(bindingId, imageBase64, mediaType)`；
- `AddFile(bindingId, streamFactory, fileName, mediaType)`；
- `AddFileReference(bindingId, fileRef)`；
- `AddFiles(bindingId, orderedFiles)`；
- `AddFileReferences(bindingId, orderedFileRefs)`。

同一输入集合由调用方显式选择 `BuildJson()` 或 `BuildMultipart()`，不由 SDK 猜测 transport。`BuildJson()` 拒绝待上传 stream；`BuildMultipart()` 使用 `input_bindings_json` 携带非文件输入，并流式发送图片和文件。现有 `WorkflowRequestBuilder` 已实现 JSON、文本、图片上传、单文件和多文件上传；Base64/引用类方法和显式双 Build API 属于阶段 8 待实现内容。

### 高性能 Trigger Builder

ZeroMQ 与 local-shared-memory 共用只包含 JSON/文本的 `WorkflowTriggerInputsBuilder`：

- `AddJson(bindingId, value)`；
- `AddText(bindingId, textPayload)`。

图片不放入该 Builder，由 `InvokeZeroMqImage*` 或 `InvokeSharedMemoryImage*` 的图片参数提供，并按 TriggerSource 默认或显式 image binding 生成 `image-ref.v1`。图片调用可以同时附带 Builder 生成的 JSON/文本；event-only 调用只发送 JSON/文本。Builder 必须依据 Runtime 固定 App Contract 和 TriggerSource mapping 拒绝未映射 binding、错误 payload type、超过 transport 限制的 payload，以及 `image-base64/file/files`。

方法名表示调用方意图，但最终仍按 Runtime 公开契约校验。SDK 不缓存整文件、不隐藏排队、等待、自动重试或 transport fallback；重试和幂等策略由调用方显式决定。stream 必须由每次发送独立创建，并在 HTTP content 释放时关闭。

SDK 配置包固定 Runtime id、公开输入契约和限制，用于调用前快速失败；后端仍执行权威校验。Python、Go 和 C SDK 在实现前继续标记为未交付。

## 实施顺序

### 阶段 1：契约和共同校验

- 注册 `text.v1`、`file-ref.v1`、`file-refs.v1`；
- 实现 Template Text/File/Files Input 和必要 bridge；
- 实现 `WorkflowInputValidator`；
- 发布 App Contract v2，并完成 v1 读取兼容与比较测试。

### 阶段 2：ObjectStore 与 multipart

- 增加 ObjectStore 流式不可变写入、staging 和原子发布；
- 把同步 invoke 和异步 runs 的 multipart 入口收敛到同一实现；
- 支持图片、单文件和多文件字段；
- 验证取消、超时、异常和服务重启后的 staging 清理。

### 阶段 3：前端与 Preview

- 增加 App Entry 快捷入口和 binding policy 编辑；
- 增加 typed Preview 输入组件；
- 生成准确的 JSON、multipart 和 SDK 请求示例；
- 保证旧图片 App 打开、保存、Preview 和发布行为不变。

### 阶段 4：.NET SDK

- 增加组合 request builder 和真正的 streaming multipart；
- 删除新文件路径中的 `File.ReadAllBytes` 和完整 `MemoryStream` copy；
- 增加 v1/v2 App Contract 和 multipart contract harness。

### 阶段 5：Trigger event-only

- 增加 local-shared-memory event-only v2；
- 复用 Trigger input mapping 和统一校验器；
- 保持图片 v1 协议、lease 与 ACK 生命周期不变。

### 阶段 7：高性能 Trigger capability

- 为 ZeroMQ/local-shared-memory 固定 `image-ref.v1`、`value.v1`、`text.v1` capability；
- TriggerSource 创建、enable 和 Runtime 切版时拒绝 `image-base64.v1`、`file-ref.v1`、`file-refs.v1` mapping；
- 前端 mapping 面板只展示当前 transport 可用的公开 binding，并明确标记其余输入为 HTTP Runtime only；
- 保持当前 `request_image_ref/request_json/request_text` 三条映射，不自动补 binding。

### 阶段 8：.NET 双调用面 API

- 补齐 HTTP Builder 的 Base64 和 ObjectStore reference 方法，并显式区分 JSON/multipart build；
- 增加共用 `WorkflowTriggerInputsBuilder`；
- 为 ZeroMQ 图片高层方法增加可选 JSON/文本 inputs；
- 让 local-shared-memory 图片和 event-only 调用复用相同 inputs 校验；
- 保留低层 Dictionary API，不把它作为常用调用示例。

### 阶段 9：真实链路验收

- HTTP 同步 invoke、异步 run 和 .NET SDK 覆盖六类输入及组合；
- ZeroMQ/local-shared-memory 覆盖 image、image+JSON、image+text、image+JSON+text、JSON+text event-only；
- 在 SDK、TriggerSource 配置和后端分别验证高性能 Trigger 对 Base64/file/files 的确定性拒绝；
- 完成长时间资源、handle、LocalBuffer lease、mailbox descriptor 和进程内存审计。

## 验收矩阵

HTTP Runtime 功能与兼容性至少覆盖：

- JSON-only、text-only、file-only 和 files-only；
- JSON + base64 图片、JSON + multipart 图片、JSON + 文件；
- JSON + 图片 + 文件、多文件有序提交；
- direct top-level binding 与 `input_bindings` 两种 JSON 形态；
- unknown、missing required、重复文件、JSON/file 冲突、schema invalid；
- MIME 拒绝、文件过大、数量过多、checksum 或 immutable version 不一致；
- 同步 invoke、异步 run、Preview 和 .NET HTTP SDK 结果一致；
- 已发布图片 App 和 App Contract v1 不发生行为回归。

高性能 Trigger 至少覆盖：

- image、image + JSON、image + text、image + JSON + text；
- JSON + text event-only；
- ZeroMQ 与 local-shared-memory 使用相同 binding payload 形状；
- `image-base64.v1`、`file-ref.v1`、`file-refs.v1` mapping 和 SDK 添加操作稳定拒绝；
- Runtime 满载立即返回 busy，不增加 SDK 或服务端等待队列；
- Base64 图片 helper 最终进入 `request_image_ref`，不误写入 `request_image_base64`。

稳定性与内存至少覆盖：

- 上传失败、取消、timeout 和 Runtime 停止后 staging、stream、文件 handle 全部释放；
- 大文件传输时 backend-service、Runtime worker 和 .NET SDK Working Set 不随文件大小形成额外完整副本；
- 持久化 Run、事件和日志中不存在文件 bytes、base64 或本机绝对路径；
- 并发上传遵守显式容量上限，满载立即返回稳定错误，不隐藏排队；
- 长时间循环调用后 ObjectStore staging、LocalBuffer lease、mailbox descriptor 和文件 handle 回到基线；
- multipart 校验失败不创建可执行 Run，不留下部分成功输入。

## 实现落点

实现已落在以下源目录；后续修改仍必须同步契约、测试和本文状态：

- `backend/nodes/core_catalog.py` 与 `backend/nodes/core_nodes/io/templates/`；
- `backend/service/application/workflows/` 的共同输入校验；
- `backend/service/api/rest/v1/routes/workflow_runtime_support/uploads.py`；
- `backend/service/application/ports/object_store.py` 与本地 ObjectStore adapter；
- `frontend/web-ui/src/workflows/workflow-editor/` 的 App Contract 和 Preview 输入；
- `sdks/dotnet/` 的 HTTP request builder 与 contract harness；
- Runtime、Preview、Trigger 和 SDK API 文档。

任何实现阶段都不得通过新增组合专用节点、隐藏转换或全文件内存复制绕开上述边界。

## 真实验证记录（2026-08-30）

基于两个既有 Batch 并行验证应用创建了独立副本；源应用、源 Template 和既有 Runtime 未修改：

| 场景 | 新 Application | 新 Template | Runtime | 当前发布版本 |
| --- | --- | --- | --- | --- |
| 3570 治具空盘 | `workflow-app-20260830050503` | `workflow-graph-20260830050503` | `workflow-runtime-8c257afd0c144890a58592c8a15586e9` | `workflow-app-version-1e3177d397774687a4dc24187d0021e9` |
| 3570 塑盒满盘 | `workflow-app-20260830050504` | `workflow-graph-20260830050504` | `workflow-runtime-83b9c7644e5e44b58bda402ce84ee889` | `workflow-app-version-2584543191694ec791fc9745924b4cf1` |

两个 App 均冻结 `amvision.workflow-app-contract.v2`，公开 6 个可选 input：`request_image_ref`、`request_image_base64`、`request_json`、`request_text`、`request_file`、`request_files`。新增 Object/Text/File/Files 输入节点保持通用、纯函数和未连接时不执行，不改变原 Hough、Parallel 和 Classification Batch 主链。

真实 HTTP multipart 调用同时提交 59,885,622 bytes BMP、JSON、文本、单文件和两个有序文件，两条 Workflow 均成功；输入对象在调用结束后清理，LocalBuffer lease 归零。invalid JSON schema、未知 binding、错误 MIME、单文件重复上传和 closed schema 多余字段均按稳定错误码失败。

真实 net472 SDK 通过 local-shared-memory 同时提交 59,885,622 bytes BMP、JSON 和文本。每条链路执行 4 次预热和 40 次计量，合计 `88/88` 成功：

| 场景 | 轮次 | mean | P50 | P95 | max | mmap 写入均值 |
| --- | --- | --- | --- | --- | --- | --- |
| 治具空盘 | 1 | 877 ms | 875 ms | 1002 ms | 1031 ms | 4.49 ms |
| 治具空盘 | 2 | 931 ms | 922 ms | 1039 ms | 1184 ms | 4.52 ms |
| 塑盒满盘 | 1 | 1051 ms | 1017 ms | 1248 ms | 1250 ms | 4.41 ms |
| 塑盒满盘 | 2 | 991 ms | 970 ms | 1172 ms | 1187 ms | 4.58 ms |

两轮后每个 Trigger 的 request/success 为 `44/44`，error、timeout、busy 和 capacity reject 均为 0；mailbox page 为 `512 free / 0 used`。2 GiB LocalBuffer 的 active lease、allocated/published bytes、WRITING、ACTIVE、REVOKING、QUARANTINED 和 pending response route 全部归零。

Runtime 首次负载前后存在模块和 OpenCV 工作集加载；第二轮 40 次调用后，治具 Runtime Working Set 仅从 176.12 MiB 到 176.38 MiB，塑盒 Runtime 从 180.91 MiB 到 181.12 MiB，未发现随调用次数线性增长。项目当前较大的常驻内存来源是显式 desired-running 的多个独立 Runtime worker 和模型部署进程，不是单次请求残留；验证副本在验收结束后停止，既有用户 Runtime 保持原状态。

内存审计还发现 direct reader、direct writer 和 Workflow owner view 曾分别打开同一个 2 GiB `images.mmap`。现已改为控制面 client 延迟打开数据面、同一 client 的 reader/writer 共用一个 `MmapBufferArenaExternalAccess`、独立 Deployment worker 的 reader/writer 复用同一 access，Workflow 已持有所有权的解码 view 也从该 access 取得，不再经旧文件 cache 建立第二个映射。修复后进行真实 net472 回归：治具 `20/20` 成功，mean 998 ms、P95 1370 ms；塑盒连续两轮均 `20/20` 成功，mean 1111/1051 ms、P95 1289/1165 ms。第二轮后塑盒 Runtime Working Set 仅从 180.77 MiB 到 180.92 MiB。每个活跃 Workflow worker、模型 Deployment worker 和 Broker owner 均只有一个 `images.mmap` view，Backend 与 inference daemon 控制进程为 0；LocalBuffer 最终为 0 active lease、0 allocated bytes、2 GiB free、0 pending response route。验证副本停止后，Backend 进程树共 16 个进程（主服务、Broker 和 14 个既有 desired-running Runtime），Working Set/USS 合计约 2329.5/1747.3 MiB；inference daemon 进程树共 6 个进程，主要为既有已加载模型 worker，合计约 4036.6/2698.2 MiB。Windows 对 file-backed mmap 的逐 mapping `rss` 可能显示完整文件长度，常驻判断使用进程 Working Set/USS 和 view 数，不把虚拟映射长度误报为物理占用。

真实链路验证额外发现并修复三项边界错误：

- worker 不再用当前 Node Catalog 重算旧 Runtime 指纹，而是从不可变 App Version 的 Application、Template、Contract 和 dependency manifest 计算；
- optional Template Input 节点声明为 pure，未连接输入不再被当成可观察副作用而隐藏执行；
- local-shared-memory、ZeroMQ 和 Preview 生成的 buffer `image-ref.v1` 显式保留顶层 `media_type`，不依赖 BufferRef 内部重复字段，也不按扩展名猜测。
- LocalBuffer direct reader/writer 和 Workflow owner view 共用延迟 mmap，消除同进程重复 2 GiB 虚拟映射，同时保留 publication identity 重验与 owner cleanup 边界。

代码门禁结果：最终后端组合回归 288 项通过；前端全量 76 个测试文件、289 项测试通过并完成 production build；.NET net472 x64 Release 零 warning/零 error且契约程序通过；所有改动 Python 文件通过 Ruff，`git diff --check` 通过；浏览器核对两个 App、App Contract、Preview 控件、Parallel/Batch/Hough 节点和 Runtime 状态，控制台无 warning/error。

## 完成与归档条件

全部阶段完成并通过验收矩阵后，稳定不变量分别迁入 Workflow JSON、节点系统、Runtime API、Trigger API 和 SDK 正式文档，本文顶部状态改为已完成。完成后的历史阶段清单和一次性验证数据不作为长期架构重复保留；当正式文档、代码和持续门禁已能独立说明行为时，从 `docs/development/README.md` 移除本实施基线并删除或归档本文。
