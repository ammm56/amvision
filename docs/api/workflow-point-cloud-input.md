# Workflow 点云输入

M3.2 起运行引用为 `point-cloud-ref.v1`，资产内容和显示同步升级；同机 `point-cloud-buffer.v1` 与 Cloud PREPARE 二进制布局不变。旧三维配方需审核重发，旧资产保留历史并需重建，不自动迁移或回退执行。字段与保存/恢复规格见 [M3.2 实施记录](../development/3d-metrology-m3-boundary.md#5-运行引用与保存契约)。

本接口扩展现有文件输入与 local-shared-memory Trigger，不新建 Workflow 或发布系统。每次提交完整输入，载荷不超过 1,000,000,000 字节。该上限不是运行内存上限，也不是全部格式/算法的 1 GB 容量验收声明。当前源码二十六个三维节点已按批准的本机工程配置启用，timeout、运行和显示预算见[节点包说明](../../custom_nodes/metrology3d_nodes/README.md)；示例中的文件、解码和资产上限不能覆盖任意接近 1 GB 的输入，完整容量及发行缺口见[剩余清单](../development/3d-metrology-remaining.md)。

2026-11-02 新增可选 [1 GB 工程配置](../../custom_nodes/metrology3d_nodes/workstation-1gb.example.json)，Windows/WSL 的真实文件、Python 同机数组及 HTTP Preview 主链路已通过精确 1 GB 验证，详见[容量记录](../development/3d-metrology-capacity.md)。该配置不自动覆盖已有服务；原工作站配置仍为较小容量。压缩展开、索引和工作数组仍逐项准入，单次输入上限不等于任意 1 GB 文件都可执行任何算法。

## 文件入口

发布应用使用既有 `file-ref.v1` / `file-refs.v1` 输入和 HTTP streaming multipart；.NET 使用 `WorkflowRequestBuilder.AddFile`、`WorkflowUploadFile.FromFile` 或 stream factory。Read Cloud 节点显式声明格式、全部字段映射和空间单位，不凭扩展名猜测字段或单位。

编辑器 Preview 使用现有会话的 `POST /api/v1/workflows/preview-sessions/{session_id}/inputs/file?byte_length=...&file_name=...`，正文为原文件；返回 input_id/摘要，不返回服务端临时路径。创建会话的 `file_upload_limit_bytes` 为 null 时不能上传文件。会话取消、失败、超时和 worker 退出沿既有 pin/回收边界处理，不把完整文件放入 WebSocket 或 SHM。

文件仍受公开 App Contract、请求配置和显式文件预算约束；不因点云最大载荷为 1 GB 就自动提高已有 HTTP 上限。上传本身不代表永久保存原云，配方通过 Save Cloud 显式保存。资源 ZIP 导入使用独立配置的资产包上限。

## 同机数组入口

调用方使用 `amvision.workflow-trigger-cloud-prepare.v1`，其中 cloud 为 `amvision.point-cloud-buffer.v1`。完整字段见[发布 JSON Schema](../../sdks/schemas/workflow-trigger-cloud-prepare.v1.schema.json)，由后端契约生成。

- fields 按声明顺序排列为 little-endian 连续属性块；positions 每点三个分量，类型为 float32 或 float64。每个属性块内逐点排列分量，不是 x/y/z 分开三个块。
- count 必须等于 point_count；offset_bytes、byte_length 和 content_length 必须精确匹配。仅允许类型对齐所需的零填充，没有额外尾部。
- spatial 显式声明单位、坐标系和轴；单位未知保持 null，不把当前样本默认解释成毫米。外部字段按声明保留精度，当前样本使用 float32。
- TriggerSource 必须映射已发布 `point-cloud-ref.v1` 输入，路径为 `payload.<key>`。PREPARE 的 event_payload_key 与 SDK InputBinding 对应；REQUEST 的 Payload 不得覆盖该键。
- source_indices 和 source_point_count 由 worker 按首次输入建立；调用方不能提交执行期 cloud_id、借用令牌或伪造普通 JSON CloudRef。
- 不支持远程共享内存、ZeroMQ 点云、图片描述符包装或自动 HTTP fallback。浏览器数组输入不提供 JSON 编辑框。

后端在分配前校验输入契约与预算；调用方完成写入、释放 writer guard 后发布 REQUEST。平台取得运行准入并交接 owner，worker 在 ResourceScope 内只读映射，结果按既有 ACK 生命周期释放。没有额外等待队列。

## 标定深度/高度栅格

Raster to Cloud 显式二选一，不从图片灰度、文件名或旧输入猜测物理标定：

- 文件模式输入 `file-ref.v1`，复用上述上传；节点 `settings={kind:"file",file_format:"npy|png|tiff",raster:...}` 固定标定、原始 dtype、尺度、单位与无效规则。NPY 为二维标量，PNG/TIFF 只接受已核定的单通道无损类型，具体范围见 [B06 文件矩阵](../development/3d-metrology-raster-input.md#3-字段与文件范围)。
- 同机数组模式输入 `calibrated-raster.v1`，节点 `settings={kind:"local-array"}`，不允许再填标定。调用使用 `amvision.workflow-trigger-raster-prepare.v1`，其中 raster 为 `amvision.raster-buffer.v1`，完整定义见 [PREPARE schema](../../sdks/schemas/workflow-trigger-raster-prepare.v1.schema.json)。布局为 little-endian 连续 HW 标量，可紧随同尺寸 uint8 0/1 mask，无 padding/尾字节；不能传 NPY 头或压缩图片字节。
- Trigger 映射必须准确指向发布的 `calibrated-raster.v1` binding。标定、布局和输入键在 PREPARE 冻结，REQUEST 不能覆盖；同一 owner/Scope 处理分配、执行、取消、ACK 和客户端退出，不新增等待队列。HTTP JSON、远程共享内存、普通图像 buffer 不提供数组降级入口。
- 原始像素身份为 `row*width+column`，无效像素保留原始值和状态，位置为 NaN。已有 Filter Valid 显式筛除后仍保留最初行号及完整网格总数；保存重读和显示保留标定来源。

Python 使用 `PointCloudClient.invoke_raster`，Windows .NET 使用 `SharedMemoryTriggerClient.InvokeCalibratedRaster` 或配置化 `AMVisionOperationRunner.InvokeSharedMemoryCalibratedRaster`，byte[] 与直接 writer 均支持。输入键使用实际 Trigger 映射，不默认替换应用绑定。源文件仍可通过 HTTP 跨机上传，数组只支持同机。

本批真实发布、Python 数组、取消/切版/异常回收通过 Windows/WSL；.NET 仅声明 Windows net472，页面仅声明 Windows。独立解析网格通过不等于实采标定精度认证；旧点云 1 GB 证据不替代新栅格转换的资源峰值与最大容量验收。

## 标定扫描轮廓

Profiles to Cloud 已接通两种显式方法：原采集行号固定步距、逐行编码器位置。文件模式使用 `settings={kind:"file",file_format:"npz",profiles:...,has_validity:...}` 和 `file-ref.v1`；数组模式只使用 `settings={kind:"local-array"}` 和 `calibrated-profiles.v1`，不能覆盖载荷标定。

同机准备格式为 `amvision.workflow-trigger-profile-prepare.v1`，字段 `profiles` 是 `amvision.profile-buffer.v1`，见[公开 schema](../../sdks/schemas/workflow-trigger-profile-prepare.v1.schema.json)。原始二进制按 `profiles`、`line_offsets`、`line_ids`、可选 `encoder_positions`、可选 `validity` 连续 little-endian 拼接；完整形状、类型和条件见[B07 字段表](../development/3d-metrology-profile-input.md#22-文件成员与二进制布局)。不是 NPZ 文件字节，也不能复用栅格准备格式。

准备时冻结描述摘要、输入键与已发布 binding。REQUEST 不得替换；普通 JSON 和其他协议不能伪造同机数组。调用复用原准入、writer/reader guard、取消和 ACK，不新增队列。Python 使用 `invoke_profiles(profiles=descriptor, ...)`；Windows .NET 使用 `InvokeCalibratedProfiles` 或配置化 `InvokeSharedMemoryCalibratedProfiles`，同时提供 byte[] 和直接写入回调。

`source_indices` 是最初总样点记录号；采集行号、原行内样点号另存字段。缺行不压缩步距，空行不补点，倒向/重复编码器位置原样保留。浏览器文件使用既有上传；数组只展示同机输入提示，不提供无效 JSON 提交框。查看器显示原行表总数、空行数和标定身份，源点拾取显示实际采集行/样点；生成点不伪装为原始记录。

资产 `source.kind=calibrated-profiles` 保存完整标定、输入摘要、`row_table_sha256` 和完整原始点数/采集行数。原 NPZ 使用 `profiles-original` 保存；数组与派生云额外带 `profile-rows.bin`，依次包含 little-endian 行偏移、原采集行号、可选编码器位置。ZIP 精确包含 manifest 与声明的最多三个块，不接受其他成员。完整空行也保留，不靠点字段反推行表。现有资源包的授权、闭包、引用映射及回滚复用不变。

该来源首次接入当前三维 v1 开发契约，既有非轮廓资产不增加行表、不删除或迁移数据，也没有旧格式兼容执行分支。运行、资产与跨代验证范围见[B07 记录](../development/3d-metrology-profile-input.md)。

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

当前 .NET SDK 面向 Windows net472；Ubuntu 服务侧测试不能替代 Ubuntu .NET SDK 交付。已有正式 [Python 同机调用工具](../../runtimes/clients/point_cloud/README.md)，不依赖 tests；本批 1 GB 同机验收使用该工具。工具和工件配方已接入 `assemble-release`，发行入口为 `launchers/client/invoke_point_cloud.py`，实现与搬移验证见[工具发行记录](../development/3d-metrology-tool-delivery.md)。完整离线运行依赖及 .NET 的 1 GB 边界仍需补验，不沿用内部协议测试充当客户端交付。早期实现记录和样本证据见 [M1 传输与界面](../development/3d-metrology-m1-transports.md)。

## 已保存资产的原始点显示

Cloud Preview 新增 `prepare_details: boolean = false`。仅对 Read Cloud 读取的完整资产显式准备，worker 生成可重建显示索引；不在 API handler 建树或扫描点云。默认结果仍只有有界证据，不自动保存输入或延长 LocalBuffer 生命周期。

沿现有 `/api/v1/workflows` 路由提供两个只读接口：

```text
GET /projects/{project_id}/measurement-resources/{resource_id}/versions/{version}/details?sha256={source_digest}
GET /projects/{project_id}/measurement-resources/{resource_id}/versions/{version}/details/{block_id}?sha256={source_digest}&generation={index_generation}
```

第一项返回 `amvision.point-cloud-detail.v1`；第二项返回 `application/octet-stream` 紧密行记录。两者均检查现有 Reader 权限、项目、源资产版本和摘要，响应禁止缓存。块含所有原始字段及逻辑行/来源身份，字段偏移、原 dtype、长度、块范围和 SHA256 均在索引中明确。最新索引代次与块请求不一致时返回错误，客户端必须重新读取，不拼接新旧数据。删除源资产后不可继续读缓存。

显示正文的 `asset_details.source` 必须等于 `source_asset`，不携服务端路径。完整资产范围与概览抽样范围分别保留。前端在容量内按视野加载叶块；仅所有选中块校验成功后标记当前视野全分辨率，超限或失败保留明确状态。显示不参与量值计算。

完整字段、预算、使用路径、双平台证据及最大容量限制见[资产细节显示](../development/3d-metrology-details.md)。1 GB 输入验收不代表 1 GB 显示索引构建已通过。
