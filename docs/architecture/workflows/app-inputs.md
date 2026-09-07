# Workflow App 输入契约

> 当前实现：HTTP Runtime 已支持六类公开输入；ZeroMQ/local-shared-memory 只支持 `image-ref.v1`、`value.v1`、`text.v1`；.NET SDK 已提供两套明确的 Builder，并通过实际 Workflow App、Runtime、Trigger 和 SDK 组合调用验收。24 小时以上现场 soak 仍属于发布门禁，不由一次开发验收替代。代码、OpenAPI、Catalog 和持续测试是实现状态的最终证据。

不可变架构取舍见 [ADR-0010：Workflow App Entry 多类型输入契约](../../decisions/ADR-0010-workflow-app-entry-multi-input-contract.md)。本文维护当前输入契约、调用面分工与持续验证规则。

## 文档目的

Workflow 调用不应被限制为每次只提交一张图片。一个公开 App 可以只接收 JSON，也可以同时接收 JSON、文本、图片、单文件或多文件。扩展必须继续使用通用节点和通用 payload，通过 Workflow 编排组合能力，不能为 `JSON + 图片`、`JSON + 文件` 等组合建立应用专用节点。

本文固定以下内容：

- App Entry 的公开 binding、payload type 和 wire transport 三层边界；
- JSON、文本、文件和多文件的统一 payload；
- JSON 与 multipart 请求的确定性解析、校验和 ObjectStore 生命周期；
- Runtime、Preview、Trigger、LocalBuffer、SDK 和前端使用同一输入契约的方式；
- 兼容性、内存、错误和验收规则。

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

## 当前输入能力

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

`text.v1` 当前使用 inline JSON：

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

`file-ref.v1` 用于文件输入。公开 Runtime 中的规范形状固定为受管理的不可变 ObjectStore 引用：

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

`file-refs.v1` 用于文件列表：

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

调用方已经持有受管理对象时，可以在 JSON body 中直接提交 `image-ref.v1` 或 `file-ref.v1`。服务端仍校验 Project、不可变版本、长度和 checksum，不把任意 object key 当作可信输入。

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

应用层 `WorkflowInputValidator`，由 HTTP JSON、HTTP multipart、Preview、Trigger、SDK 转换后的 Runtime 请求共同调用。校验顺序固定为：

1. 拒绝未知 binding，并检查 required binding；
2. 按不可变 App Version 检查 `payload_type_id`；
3. 正式 Runtime 按不可变 App Version 冻结的 `payload_schema` 校验外层 payload；编辑态 Preview 按本次固定 snapshot 对应的 Catalog schema 校验；
4. 对 `request_json` 的 `payload.value` 应用 binding 的 `request_schema`；
5. 校验 inline 大小、JSON 深度、文本长度、文件数量、文件大小和允许 MIME；
6. 校验 storage ref 的 Project、不可变版本、长度和 checksum；
7. 全部通过后才把规范 `input_bindings` 交给 Runtime。

不得通过字符串转数字、scalar 包装、扩展名推断、自动 JSON parse 或丢弃未知字段来“修复”请求。Schema 校验错误详情使用 `binding_id`、`payload_path`、`schema_path` 和 `reason`；容量、数量、MIME 与 ObjectStore 引用错误携带对应的限制值或对象标识。错误不回显 base64、文件内容或敏感 JSON 值。

当前使用以下稳定错误码，并由输入契约、Runtime/Preview API 和自动化测试共同约束：

- `workflow_input_unknown_binding`；
- `workflow_input_required_binding_missing`；
- `workflow_input_payload_schema_invalid`；
- `workflow_input_multipart_binding_conflict`；
- `workflow_input_file_count_exceeded`；
- `workflow_input_file_size_exceeded`；
- `workflow_input_file_media_type_rejected`；
- `workflow_input_object_reference_invalid`，`details` 携带 `binding_id` 和 `object_key`，具体失败原因由错误消息说明；
- `workflow_input_upload_failed`。

## 公开 App 契约与兼容性

当前 `amvision.workflow-app-contract.v1` 冻结 binding id、payload type、required、config 和规范化 `request` 策略，至少包括：

- 外层 `payload_schema` 和可选的 `request_schema`；
- `allowed_media_types`；
- `max_inline_bytes`、`max_file_bytes` 和 `max_files`；
- 明确的 `transports`，例如 JSON reference、inline JSON 或 multipart upload；
- 文本 charset 规则。

v1 的公开 input `payload_schema` 使用 closed-object 规则；包括 `value.v1` 外层在内，未声明的外层字段直接失败。该规则只约束公开请求，不改变 Workflow 内部边的 `value.v1` 行为。

开发阶段不保留宽松 v1 与严格 v2 两套行为。Workflow App 每次发布都生成唯一的严格 v1 契约快照，并使用同一份规范化契约驱动 Runtime、编辑器、OpenAPI 示例和 SDK 配置。正式 Runtime 不在执行时回读当前 Catalog schema，避免 Catalog 更新改变已发布版本的输入行为。

同一 v1 协议内比较 Workflow App 发布版本；如果 schema 或 policy 会扩大拒绝集合，则报告破坏性变化并要求现有显式 override。Runtime 固定具体 App Version revision，不从协议格式号推断业务发布版本。

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

当前通用节点：

- `core.io.template-input.text`：`text.v1 → text.v1`；
- `core.io.template-input.file`：`file-ref.v1 → file-ref.v1`；
- `core.io.template-input.files`：`file-refs.v1 → file-refs.v1`；
- `core.logic.text-to-value`：只把 `text` 字符串包装为 `value.v1`，不解析 JSON；
- `core.logic.json-parse-text`：显式把 JSON 文本解析为 `value.v1`；
- `core.logic.value-to-json-text`：按明确参数把 `value.v1` 序列化为 `text.v1`；
- `core.logic.string-concat`：严格拼接两个字符串 `value.v1`，不隐式转换类型或解析日期块；
- `core.logic.scalar-to-string`：显式把字符串、有限数字或布尔值转换成字符串 `value.v1`；
- `core.logic.format-date-time`：复用通用日期时间解析器并输出一次性捕获的本地时间字符串；
- `core.io.file-metadata`：只读取引用元数据；
- `core.io.file-read-text`：显式 charset 和最大读取长度，输出 `text.v1`；
- `core.io.file-read-json`：按固定 UTF-8 和最大读取长度解析 JSON，输出 `value.v1`；
- `core.logic.file-refs-get-item`：从 `file-refs.v1` 按固定或动态索引恢复 `file-ref.v1`；
- `core.io.file-refs-metadata-list`：按上传顺序输出文件引用元数据列表，不读取文件字节。

文件输入节点只透传引用，不读取、解析或缓存文件内容。`Read JSON File` 输出 `value.v1`，从而直接接入已有逻辑、集合、Parallel、ForEach、HTTP 和模型参数节点。文件引用不提供从普通 `value.v1` 反向恢复的 bridge，避免请求 JSON 伪造 ObjectStore 引用；多文件需要读取内容时必须先通过受校验的 `File Refs Get Item` 取得正式 `file-ref.v1`。

`request_text` 构造动态保存文件名的标准链路为：

```text
Template Text Input → Text To Value → Concat Strings.left
String Value("-{YYYYMMDDhhmmss}.jpg") → Concat Strings.right
Concat Strings.value → Save Image.file_name
```

Concat Strings 不处理大括号，日期块由 Save Image 或独立 Format Date Time 节点明确展开。`request_json` 可以直接进入 Extract Value Field、Object/List 节点或 Format String；提取到的数字、布尔值需要参与文本拼接时先经过 Scalar To String。

## Trigger 与 LocalBuffer

高性能 Trigger 的协议中立事件 `payload` 携带 JSON 和文本，input mapping 按显式 dotted path 映射到公开 binding。统一规则为：

- JSON 和文本直接放入事件 payload；
- 图片继续通过 LocalBuffer 或现有 ZeroMQ binary frame 转成 `image-ref.v1`；
- `image-base64.v1`、`file-ref.v1` 和 `file-refs.v1` 只通过 HTTP Runtime 调用，不进入高性能 Trigger mapping；
- TriggerSource mapping 与 HTTP 调用最终必须经过同一个 `WorkflowInputValidator`；
- Trigger adapter 不根据内容生成未声明 binding，也不自动 fallback transport。

local-shared-memory 的 `WorkflowTriggerPrepareV1.image` 保持必填；`WorkflowTriggerRequestV1.payload` 可在同一次图片调用中同时携带 JSON 和文本。event-only 请求作为同一 v1 协议内的独立操作，纯 JSON/文本请求直接进入 REQUEST phase，跳过图片 PREPARE、LocalBuffer allocation 和 lease 状态机。实现没有把必填 image 改成可空，也不会为空事件分配假图片 slot。

ZeroMQ JSON 事件继续支持纯结构化 JSON/文本请求。普通文件不得复用图片 binary frame，local-shared-memory 也不得为普通文件分配 LocalBuffer。`Invoke*ImageBase64` 只表示 SDK 接受 Base64 作为图片来源并解码成图片 bytes，最终仍写入 `request_image_ref`；该方法不表示 Trigger 支持 `request_image_base64`。

## 前端编辑器与 Preview

App Contract 面板提供以下通用快捷入口：

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

## SDK 调用面

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

同一输入集合由调用方显式选择 `BuildJson()` 或 `BuildMultipart()`，不由 SDK 猜测 transport。`BuildJson()` 拒绝待上传 stream；`BuildMultipart()` 使用 `input_bindings_json` 携带非文件输入，并流式发送图片和文件。`WorkflowRequestBuilder` 已实现 JSON、文本、图片上传、图片 Base64/引用、单文件/多文件上传和文件引用；旧 `Build()` 只作为等价于 `BuildMultipart()` 的兼容入口保留。

### 高性能 Trigger Builder

ZeroMQ 与 local-shared-memory 共用只包含 JSON/文本的 `WorkflowTriggerInputsBuilder`：

- `AddJson(bindingId, value)`；
- `AddText(bindingId, textPayload)`。

图片不放入该 Builder，由 `InvokeZeroMqImage*` 或 `InvokeSharedMemoryImage*` 的图片参数提供，并按 TriggerSource 默认或显式 image binding 生成 `image-ref.v1`。图片调用可以同时附带 Builder 生成的 JSON/文本；event-only 调用只发送 JSON/文本。Builder 必须依据 Runtime 固定 App Contract 和 TriggerSource mapping 拒绝未映射 binding、错误 payload type、超过 transport 限制的 payload，以及 `image-base64/file/files`。

方法名表示调用方意图，但最终仍按 Runtime 公开契约校验。SDK 不缓存整文件、不隐藏排队、等待、自动重试或 transport fallback；重试和幂等策略由调用方显式决定。stream 必须由每次发送独立创建，并在 HTTP content 释放时关闭。

SDK 配置包固定 Runtime id、公开输入契约和限制，用于调用前快速失败；后端仍执行权威校验。Python、Go 和 C SDK 在实现前继续标记为未交付。

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

实现位于以下源目录；修改时同步契约、测试和对应 API 文档：

- `backend/nodes/core_catalog.py` 与 `backend/nodes/core_nodes/io/templates/`；
- `backend/service/application/workflows/` 的共同输入校验；
- `backend/service/api/rest/v1/routes/workflow_runtime_support/uploads.py`；
- `backend/service/application/ports/object_store.py` 与本地 ObjectStore adapter；
- `frontend/web-ui/src/workflows/workflow-editor/` 的 App Contract 和 Preview 输入；
- `sdks/dotnet/` 的 HTTP request builder 与 contract harness；
- Runtime、Preview、Trigger 和 SDK API 文档。

任何实现阶段都不得通过新增组合专用节点、隐藏转换或全文件内存复制绕开上述边界。
