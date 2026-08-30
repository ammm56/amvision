# Workflow 外部调用 SDK

## 当前交付

仓库当前提供 C#/.NET SDK：`sdks/dotnet/`。它面向 WinForms、WPF、MES 桥接、采集程序和现场服务，核心库为 `Amvar.Vision.dll`，默认交付工程支持 VS2019 + .NET Framework 4.7.2。

Python、Go 和 C SDK 当前没有实现，不能作为已交付能力使用。跨语言协议事实位于 `sdks/schemas/`。

## 能力

- Workflow Runtime 查询、启停、重启、健康与 revision 分页
- 停机选择 Workflow App Version
- Workflow App Version archive/restore 状态 CAS
- 同步 invoke、异步 run、Run/Event 查询和取消
- TriggerSource 查询、启停与健康
- ZeroMQ 图片、BGR24、Base64 和事件调用
- 本机共享内存图片、BGR24、Mono8、Bitmap、文件和 Base64 同步调用
- Model Deployment runtime 控制与同步/异步推理
- `Config/config_*.json` 加载和按 name/id 调用

SDK 不创建训练任务、修改模型资源、直接访问数据库/ObjectStore/LocalBuffer，也不读取 Workflow Worker 内部状态。

## 版本调用规则

- 设备侧长期保存稳定 Runtime/Trigger id，不保存 `latest`。
- Runtime 切换兼容版本后调用地址不变；破坏性契约变化必须先升级调用方或新建 Runtime。
- 每条 Run 返回固定的 Workflow App version、revision、generation、snapshot fingerprint 和 worker instance id。
- archive 请求的 `expected_state` 为 `published`，restore 为 `archived`。
- Runtime 创建时 version selector 必须且只能提供一个；新代码使用准确 `workflow_app_version_id`。

## 使用配置包

项目工作台统一生成 SDK 配置包。解压后的 `Config/config_*.json` 包含 Runtime、TriggerSource 或 Model Deployment 的稳定 id、HTTP/ZeroMQ 地址与调用参数。

```csharp
using (var client = AMVisionClient.CreateFromConfig())
{
    var result = await client
        .InvokeConfiguredWorkflowRuntimeByNameAsync("托盘空盘检测")
        .ConfigureAwait(false);
}
```

配置包接口见 [SDK 配置包](sdk-config-packages.md)。完整引用、依赖 DLL、name/id 规则、Console 示例和 VS2019 构建命令见 [sdks/dotnet/README.md](../../sdks/dotnet/README.md)。

## Workflow 输入调用面

`.NET` SDK 分别面向 HTTP Runtime 和高性能 Trigger，两套 API 不混用：

| SDK 调用面 | 输入能力 | 当前状态 |
| --- | --- | --- |
| HTTP Runtime | `image-ref.v1`、`image-base64.v1`、`value.v1`、`text.v1`、`file-ref.v1`、`file-refs.v1` | Runtime 与 multipart streaming 已实现；统一 Base64/reference Builder 方法和显式 JSON/multipart build 待补齐 |
| ZeroMQ Trigger | `image-ref.v1`、`value.v1`、`text.v1` | 图片和通用 payload 已实现；高层图片方法附带强类型 JSON/文本 inputs 待补齐 |
| local-shared-memory Trigger | `image-ref.v1`、`value.v1`、`text.v1` | 图片请求 payload 和 event-only v2 已实现；共用强类型 inputs Builder 待补齐 |

HTTP Builder 必须覆盖 JSON、文本、图片上传、图片引用、Base64 图片、单文件、多文件及文件引用。文件路径使用 stream factory / `StreamContent`，不使用 `File.ReadAllBytes`、完整 `MemoryStream` copy、隐藏重试、排队或 transport fallback。调用方显式选择 JSON 或 multipart build，SDK 不根据输入内容猜测 transport。

高性能 Trigger 使用独立 `WorkflowTriggerInputsBuilder`，只允许 `AddJson` 和 `AddText`。图片由 ZeroMQ 或 local-shared-memory 图片调用方法提供并生成 `request_image_ref`；Builder 不接受 Base64 图片、单文件或多文件。SDK 调用前按配置包中的 Runtime App Contract、TriggerSource mapping 和 transport 上限快速失败，后端仍执行权威校验。完整 API 规划和验收规则见 [Workflow App Entry 多类型输入实施基线](../development/workflow-app-entry-input-implementation.md)。

## 高速图片调用

图片来源与传输表示相互独立。调用方可以从相机、文件、网络或内存获得图片，再显式选择：

- `InvokeBgr24`、`InvokeBgr24FromBitmap`、`InvokeBgr24FromFile`：由调用方提供或由 SDK helper 转为连续 BGR24；后端直接解释 raw matrix，不执行图片 codec 解码；
- `InvokeImageBytes`、`InvokeImageFromFile`、`InvokeImageBase64`：保留 JPEG、PNG、BMP 等 encoded bytes；后端首次矩阵消费时解码一次并在本次 Workflow 内复用。

两组方法都是正式支持入口。BGR24 是本机高性能默认选择，不是强制格式；encoded 方法通常减少传输字节但增加后端解码和矩阵分配，SDK 开发者根据现场链路选择。

`InvokeImageBase64` 中的 Base64 只描述调用方图片来源。SDK 将其解码为 encoded image bytes，再通过 ZeroMQ binary frame 或 LocalBuffer 发送，最终绑定 `image-ref.v1`；它不向 Workflow 的 `request_image_base64` 输入发送 Base64。需要 `image-base64.v1` 时使用 HTTP Runtime。

```text
SDK BGR24/image bytes
  → ZeroMQ envelope + content
  → TriggerSource adapter
  → LocalBufferBroker BufferRef
  → Workflow Runtime
```

ZeroMQ SDK 不直接操作 mmap 文件或 slot。timeout、transport error 和后端非 2xx/错误 reply 必须保留原始状态与错误详情，调用方自行决定现场处置；SDK 不隐藏队列或无限重试。

当前 ZeroMQ reply 统一为 `amvision.workflow-trigger-result.v1` multipart：Frame 0 是 JSON manifest，后续 0 到 N 帧是按完整物理 identity 去重的图片 payload。SDK 严格校验 frame 集合、长度和 checksum；多个逻辑 attachment 可以共享同一个物理 frame。

## 本机共享内存 Trigger

独立 `local-shared-memory` TriggerSource 的 binary protocol、External LocalBuffer Writer Lease、全局 Workflow Trigger mailbox、结果 reader 生命周期和 .NET SDK 已实现，并已通过性能矩阵、10,000 次混合 soak、真实 Workflow/Deployment/Trigger 业务链和故障恢复门禁。它与 ZeroMQ API 并列，不改变或替代 ZeroMQ。

现有实现已完成每 lease writer/reader guard、异常 writer 隔离、真实 Runtime execution token、公开输出图片 owner handoff、ACK/deadline 回收和 Python/.NET binary contract 门禁。设计边界见 [ADR-0007](../decisions/ADR-0007-local-shared-memory-workflow-trigger.md)，完整门禁见[本机共享内存 Trigger 实施基线](../development/local-shared-memory-trigger-implementation.md)。SDK 不在两种 transport 之间自动 fallback。

`SharedMemoryTriggerRequest.EnableTimings` 默认是 `false`。显式开启后，返回结果的 `Timings` 提供 `SdkConvertToBgr24Ms`、`SdkBase64DecodeMs`、`SdkWriteLocalBufferMs`、`SdkChecksumMs`、`InvokeReturnMs`、`AttachmentAccessMs` 和 `DisposeAckMs`。`SdkChecksumMs` 只记录结果 attachment 校验；trusted-local 输入通过 writer guard 与 descriptor publication 保证一致性，不做 full-image CRC。`InvokeReturnMs` 截止结果对象可返回；零复制 attachment 的读取持有耗时与最终 ACK 只有在结果 `Dispose`/`DisposeAsync` 后才完整。诊断关闭时不为图片写入热路径创建这些计时。

v1 固定为同步调用、每次一张输入图片和 0 到 N 张输出图片。当前 Workflow Trigger mailbox 的完整 request wire 上限为 64 KiB；SDK 必须在 claim 前按实际序列化长度校验 JSON/文本 payload。图片内容不计入该 wire 大小，而是写入 LocalBuffer。SDK 必须先完成精确长度写入、销毁写 view并释放 writer guard，随后才发布 REQUEST；后端取得 guard并校验 receipt/epoch/generation/owner/deadline，在同一 Broker 锁内原子发布 lease与首次 owner transfer。SDK 不在 Workflow 执行期间继续持有输入 writer guard，也不自行写 Broker owner、lease state 或 descriptor FREE。

### 统一结果模型

Workflow 节点决定返回表示：

- 图片直接公开为 `image-ref.v1`：SDK 得到图片 attachment；
- 图片经过 `Image Encode`：SDK 得到对应 JPEG/PNG/BMP/WebP attachment；
- 图片经过 `Image Base64 Encode`：SDK 在 JSON 中得到 `image-base64.v1`，不再收到重复 binary attachment。

本机共享内存结果只在 mailbox JSON 中携带 `local-buffer` locator，图片 bytes 继续留在 LocalBuffer。SDK 在 `Invoke` 返回前取得 reader guard，并由结果对象持有到 `Dispose`/`DisposeAsync`；结果释放先禁止新读取、等待 SDK 内活动 accessor 结束并使 owner-backed view 失效，再释放全部 guard，最后只发布一次 ACK。JSON-only 或已经显式复制为 SDK 自有 `byte[]` 的结果可以提前 ACK；零复制 LocalBuffer view 不能提前 ACK。调用方不得在 dispose 后继续使用先前取得的 Span/View，终结器只报告泄漏并作为最后防线。

ZeroMQ 统一使用 `amvision.workflow-trigger-result.v1`：Frame 0 为 JSON manifest，后续第 1 到第 N 帧为唯一物理图片 payload bytes；无图片时 N=0。SDK 根据 manifest 校验 logical attachment 到 physical frame 的映射、frame count/index、length、checksum、media type、shape、dtype、layout 和 pixel format；多个逻辑 attachment 可以共享同一帧，raw BGR24 不被暗中编码。配置包不增加 reply protocol 或 JSON/multipart mode，SDK 始终读取完整 multipart message，不忽略未声明的额外帧。

成功、业务失败和 adapter 错误由同一个 result schema 表达，`error` 为空或包含 code、message 和 details。实现时删除独立 ZeroMQ error model、只解析第一帧和双协议兼容逻辑。

同一个高层结果可以同时包含结构化 JSON、单图和多图，但底层生命周期不同：ZeroMQ attachment 在 SDK 收包后由 SDK 自己持有；LocalBuffer attachment 依赖 response lease，必须在 reader guard 与 ACK 闭环后释放。

统一 wire result 包含有序 logical `attachments` 和按完整物理 representation identity 去重的 physical `payloads`。attachment 只保存 binding/item 与 payload 引用；checksum 只用于完整性校验，不能单独作为去重或所有权依据。payload locator 使用 `kind` discriminator：`local-buffer` 包含现有 BufferRef 定位/代次字段和 reader guard locator，`zeromq-frame` 包含物理 frame index，`object-store` 必须包含稳定 object key、media type、content length、checksum algorithm/value 和 immutable version。权威 owner、pool、deadline 只保存在服务端私有 handoff receipt，不公开给 SDK 作为清理授权。SDK 对未知 locator、缺字段、越界 frame、长度或 checksum 不一致一律拒绝，不猜测 transport。

attachment 顺序固定为 TriggerSource `result_bindings` 顺序，再按 `image-refs.v1.items` 顺序；`source_image` 不被隐式加入。普通 JSON 中出现嵌套 memory/buffer/frame 临时引用时服务端返回 `ephemeral_image_ref_in_json_result`，SDK 不尝试递归提取。

带临时 attachment 的幂等调用不能在结果已 ACK/发送后重放旧引用。重复请求返回 `idempotent_attachment_result_not_replayable` 和原 `workflow_run_id`，且不得重新执行 Workflow；JSON-only 结果和已经 ObjectStore 持久化的结果按各自稳定重放/查询规则处理。

ZeroMQ 后端按唯一物理 payload 跟踪 frame 生命周期，多个逻辑 attachment 可以共享同一 frame index。adapter 在发送 Frame 0 前为全部唯一 physical frame 预留进程内有界 transport-lifetime registry 容量，并取得 reader guard/ObjectStore read snapshot；满载时在任何 multipart frame 发出前返回 `zeromq_transport_capacity_exhausted`。发送失败时先关闭 socket；全部 tracker 完成后 adapter 销毁 Frame/view、关闭 snapshot、释放 guard，再调用 Broker 条件释放。未完成资源继续由 adapter registry 持有，lease 进入 REVOKING/QUARANTINED；Broker 不保存或等待 `MessageTracker`。SDK 侧校验唯一物理 frame 集合与逻辑映射，在完整 multipart 收包后管理自己的内存；发送超时不会触发自动 fallback 或业务重试。

Workflow TriggerSource result mapping REST payload 与 `amvision.workflow-trigger-result.v1` 当前属于发布前开发契约，迁移时后端、前端、.NET SDK、fixture 和已有数据整体升级并删除旧字段及双读代码。该规则不扩大到其他 REST `/api/v1` 契约。

## 门禁

.NET contract harness 使用真实 `net472` 编译，覆盖 selector 互斥、版本选择、archive/restore、revision 分页、Run 来源字段和 409 错误详情。命令见 [sdks/dotnet/README.md](../../sdks/dotnet/README.md)。
