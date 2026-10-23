# Workflow 点云输入

M3.2 起运行引用为 `point-cloud-ref.v2`，资产内容和显示同步升级；同机 `point-cloud-buffer.v1` 与 Cloud PREPARE 二进制布局不变。旧三维配方需审核重发，旧资产保留历史并需重建，不自动迁移或回退执行。字段与保存/恢复规格见 [M3.2 实施记录](../development/3d-metrology-m3-boundary.md#5-运行引用与保存契约)。

本接口扩展现有文件输入与 local-shared-memory Trigger，不新建 Workflow 或发布系统。每次提交完整输入，载荷不超过 1,000,000,000 字节。该上限不是运行内存上限，也不是已完成 1 GB 容量验收的声明。生产节点仍等待 timeout、运行和显示预算确认。

## 文件入口

发布应用使用既有 `file-ref.v1` / `file-refs.v1` 输入和 HTTP streaming multipart；.NET 使用 `WorkflowRequestBuilder.AddFile`、`WorkflowUploadFile.FromFile` 或 stream factory。Read Cloud 节点显式声明格式、全部字段映射和空间单位，不凭扩展名猜测字段或单位。

编辑器 Preview 使用现有会话的 `POST /api/v1/workflows/preview-sessions/{session_id}/inputs/file?byte_length=...&file_name=...`，正文为原文件；返回 input_id/摘要，不返回服务端临时路径。创建会话的 `file_upload_limit_bytes` 为 null 时不能上传文件。会话取消、失败、超时和 worker 退出沿既有 pin/回收边界处理，不把完整文件放入 WebSocket 或 SHM。

文件仍受公开 App Contract、请求配置和显式文件预算约束；不因点云最大载荷为 1 GB 就自动提高已有 HTTP 上限。上传本身不代表永久保存原云，配方通过 Save Cloud 显式保存。资源 ZIP 导入使用独立配置的资产包上限。

## 同机数组入口

调用方使用 `amvision.workflow-trigger-cloud-prepare.v1`，其中 cloud 为 `amvision.point-cloud-buffer.v1`。完整字段见[发布 JSON Schema](../../sdks/schemas/workflow-trigger-cloud-prepare.v1.schema.json)，由后端契约生成。

- fields 按声明顺序排列为 little-endian 连续属性块；positions 每点三个分量，类型为 float32 或 float64。每个属性块内逐点排列分量，不是 x/y/z 分开三个块。
- count 必须等于 point_count；offset_bytes、byte_length 和 content_length 必须精确匹配。仅允许类型对齐所需的零填充，没有额外尾部。
- spatial 显式声明单位、坐标系和轴；单位未知保持 null，不把当前样本默认解释成毫米。外部字段按声明保留精度，当前样本使用 float32。
- TriggerSource 必须映射已发布 `point-cloud-ref.v2` 输入，路径为 `payload.<key>`。PREPARE 的 event_payload_key 与 SDK InputBinding 对应；REQUEST 的 Payload 不得覆盖该键。
- source_indices 和 source_point_count 由 worker 按首次输入建立；调用方不能提交执行期 cloud_id、借用令牌或伪造普通 JSON CloudRef。
- 不支持远程共享内存、ZeroMQ 点云、图片描述符包装或自动 HTTP fallback。浏览器数组输入不提供 JSON 编辑框。

后端在分配前校验输入契约与预算；调用方完成写入、释放 writer guard 后发布 REQUEST。平台取得运行准入并交接 owner，worker 在 ResourceScope 内只读映射，结果按既有 ACK 生命周期释放。没有额外等待队列。

## .NET 调用

低层 `SharedMemoryTriggerClient.InvokePointCloud` 接受 descriptor 和 byte[]，或受限 Span writer。以下 descriptor、soaBytes 和 eventId 由调用方提供；InputBinding 使用 TriggerSource 实际映射键，示例中的 cloud 不是系统固定名称。

```csharp
using (var result = sharedClient.InvokePointCloud(
    descriptor,
    soaBytes,
    new SharedMemoryTriggerRequest { InputBinding = "cloud", EventId = eventId }))
{
    // 在 using 范围内读取结果；退出时释放 view 并 ACK。
}
```

已有采集/计算库可直接填充受限 Span，避免额外创建整云 byte[]：

```csharp
using (var result = sharedClient.InvokePointCloud(
    descriptor,
    destination => FillDeclaredSoA(destination),
    new SharedMemoryTriggerRequest { InputBinding = "cloud", EventId = eventId }))
{
    // FillDeclaredSoA 由调用方实现，必须写满声明布局和零填充。
}
```

回调返回后 Span 失效，不允许保留指针。descriptor 在调用时深复制，服务端执行权威字段检查。回调异常不发布 REQUEST，沿原取消协议释放。

高层 `AMVisionOperationRunner.InvokeSharedMemoryPointCloud(triggerSourceName, descriptor, contentOrWriter, request)` 复用配置 client 和结果物化逻辑，返回 `TriggerResult`；返回前释放 reader 并 ACK。该方法按明确的配置名称调用，request 必须提供 InputBinding，不从图片默认 binding 猜测点云键。

## 验证边界

Windows .NET byte[] 与 writer 两种入口已通过完整 14,745,099 点样本的真实发布版本、WorkflowAppRuntime、Trigger 和独立 worker 组合验收。覆盖版本切换、停止状态拒绝、旧 route generation、writer/执行中客户端异常退出、停止与重启及资源回收。WSL Ubuntu 使用原生文件系统和独立 Python 协议客户端验证同一服务链路，不替换真实控制面准入。

写入阶段超时会释放协议准入；仍持有 writer guard 的内存必须等 guard 释放或进程退出才可回收。执行中断连或正常停止不保证把已经完成的计算改写为失败。真实证据及测试配置见[发布运行验收](../development/3d-metrology-m1-published.md)，不等于生产容量或计量精度已验收。

当前 .NET SDK 面向 Windows net472；Ubuntu 服务侧测试不能替代 Ubuntu .NET SDK 交付。Python 独立 SDK 尚未实现，backend 内部测试客户端不属于外部 SDK。实现记录和样本证据见 [M1 传输与界面](../development/3d-metrology-m1-transports.md)。
