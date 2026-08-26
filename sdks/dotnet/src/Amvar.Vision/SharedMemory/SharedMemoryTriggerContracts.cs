using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision.SharedMemory
{
    /// <summary>
    /// 在单次 External LocalBuffer Writer Lease 范围内同步填充图片字节。
    /// 回调返回后 destination 立即失效，调用方不得保存其引用。
    /// </summary>
    public delegate void SharedMemoryTriggerBufferWriter(Span<byte> destination);

    /// <summary>
    /// 本机共享内存 Trigger client 配置。
    /// </summary>
    public sealed class SharedMemoryTriggerClientOptions
    {
        /// <summary>backend 发行实例的 data/buffers 绝对目录。</summary>
        public string BuffersRoot { get; set; } = string.Empty;

        /// <summary>已启用的 local-shared-memory TriggerSource id。</summary>
        public string TriggerSourceId { get; set; } = string.Empty;

        /// <summary>创建配置包时固定的 TriggerSource route generation。</summary>
        public long RouteGeneration { get; set; }

        /// <summary>默认图片 input binding。</summary>
        public string DefaultInputBinding { get; set; } = "request_image_ref";

        /// <summary>请求的相对 timeout；后端仍会按 TriggerSource 上限裁剪。</summary>
        public TimeSpan Timeout { get; set; } = TimeSpan.FromSeconds(5);

        /// <summary>mailbox 状态轮询间隔。</summary>
        public TimeSpan PollInterval { get; set; } = TimeSpan.FromMilliseconds(1);

        internal void Validate()
        {
            BuffersRoot = RequireText(BuffersRoot, nameof(BuffersRoot));
            BuffersRoot = Path.GetFullPath(BuffersRoot);
            TriggerSourceId = RequireText(TriggerSourceId, nameof(TriggerSourceId));
            DefaultInputBinding = RequireText(DefaultInputBinding, nameof(DefaultInputBinding));
            if (RouteGeneration <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(RouteGeneration), RouteGeneration, "RouteGeneration must be positive.");
            }

            if (Timeout <= TimeSpan.Zero || Timeout.TotalMilliseconds > uint.MaxValue)
            {
                throw new ArgumentOutOfRangeException(nameof(Timeout), Timeout, "Timeout must fit in an unsigned 32-bit millisecond value.");
            }

            if (!Environment.Is64BitProcess)
            {
                throw new PlatformNotSupportedException("Local shared-memory Trigger requires a 64-bit process.");
            }

            if (PollInterval <= TimeSpan.Zero)
            {
                throw new ArgumentOutOfRangeException(nameof(PollInterval), PollInterval, "PollInterval must be positive.");
            }

        }

        private static string RequireText(string value, string parameterName)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                throw new ArgumentException(parameterName + " cannot be empty.", parameterName);
            }

            return value.Trim();
        }
    }

    /// <summary>
    /// 单次共享内存图片调用的业务参数和追踪字段。
    /// </summary>
    public sealed class SharedMemoryTriggerRequest
    {
        /// <summary>调用事件 id；为空时由 SDK 生成。</summary>
        public string? EventId { get; set; }

        /// <summary>链路 trace id；为空时由 SDK 生成。</summary>
        public string? TraceId { get; set; }

        /// <summary>可选幂等键。</summary>
        public string? IdempotencyKey { get; set; }

        /// <summary>图片写入的 Workflow input binding。</summary>
        public string? InputBinding { get; set; }

        /// <summary>业务 payload；图片引用由服务端按 mapping 注入。</summary>
        public IDictionary<string, object?> Payload { get; } = new Dictionary<string, object?>();

        /// <summary>请求元数据。</summary>
        public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();

        /// <summary>是否采集 SDK 本地分阶段耗时；默认关闭，避免影响高性能热路径。</summary>
        public bool EnableTimings { get; set; }
    }

    /// <summary>一次本机共享内存调用的 SDK 本地诊断耗时，单位为毫秒。</summary>
    public sealed class SharedMemoryTriggerTimings
    {
        private readonly object syncRoot = new object();
        private double attachmentAccessMs;

        internal long InvokeStartedAtTicks { get; set; }

        /// <summary>图片规范化或颜色转换耗时。</summary>
        public double SdkConvertToBgr24Ms { get; internal set; }

        /// <summary>Base64/Data URL 还原耗时。</summary>
        public double SdkBase64DecodeMs { get; internal set; }

        /// <summary>序列化 PREPARE 并占用 mailbox descriptor 的耗时。</summary>
        public double SdkMailboxClaimMs { get; internal set; }

        /// <summary>等待服务端完成 LocalBuffer 分配并发布 locator 的耗时。</summary>
        public double SdkAllocationWaitMs { get; internal set; }

        /// <summary>取得 writer guard 并打开 LocalBuffer mmap view 的耗时。</summary>
        public double SdkWriterOpenMs { get; internal set; }

        /// <summary>图片字节写入 LocalBuffer mmap 的耗时。</summary>
        public double SdkWriteLocalBufferMs { get; internal set; }

        /// <summary>释放本次 writer mapping 引用和 writer guard 的耗时。</summary>
        public double SdkWriterCloseMs { get; internal set; }

        /// <summary>输入写入和输出校验的 CRC32 累计耗时。</summary>
        public double SdkChecksumMs { get; internal set; }

        /// <summary>序列化 REQUEST 并发布 mailbox REQUEST 状态的耗时。</summary>
        public double SdkRequestPublishMs { get; internal set; }

        /// <summary>REQUEST 发布后等待服务端 RESPONSE 的耗时。</summary>
        public double SdkResponseWaitMs { get; internal set; }

        /// <summary>解析 RESPONSE、校验结果并构建结果对象的耗时。</summary>
        public double SdkResultBuildMs { get; internal set; }

        /// <summary>从进入 SDK Invoke 到结果对象可返回的总耗时。</summary>
        public double InvokeReturnMs { get; internal set; }

        /// <summary>调用方打开并读取 attachment view 的累计持有耗时。</summary>
        public double AttachmentAccessMs
        {
            get
            {
                lock (syncRoot)
                {
                    return attachmentAccessMs;
                }
            }
        }

        /// <summary>Dispose 阶段释放 reader guard 并发布 ACK 的耗时。</summary>
        public double DisposeAckMs { get; internal set; }

        internal void AddAttachmentAccess(double elapsedMs)
        {
            lock (syncRoot)
            {
                attachmentAccessMs += elapsedMs;
            }
        }
    }

    internal sealed class WorkflowTriggerInputImageSpec
    {
        [JsonProperty("content_length")]
        public long ContentLength { get; set; }

        [JsonProperty("media_type")]
        public string MediaType { get; set; } = string.Empty;

        [JsonProperty("event_payload_key")]
        public string EventPayloadKey { get; set; } = string.Empty;

        [JsonProperty("shape")]
        public IReadOnlyList<int> Shape { get; set; } = Array.Empty<int>();

        [JsonProperty("dtype")]
        public string? DType { get; set; }

        [JsonProperty("layout")]
        public string? Layout { get; set; }

        [JsonProperty("pixel_format")]
        public string? PixelFormat { get; set; }
    }

    internal sealed class WorkflowTriggerPrepare
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = "amvision.workflow-trigger-prepare.v1";

        [JsonProperty("trigger_source_id")]
        public string TriggerSourceId { get; set; } = string.Empty;

        [JsonProperty("event_id")]
        public string EventId { get; set; } = string.Empty;

        [JsonProperty("image")]
        public WorkflowTriggerInputImageSpec Image { get; set; } = new WorkflowTriggerInputImageSpec();
    }

    internal sealed class WorkflowTriggerAllocation
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonProperty("arena_id")]
        public string ArenaId { get; set; } = string.Empty;

        [JsonProperty("lease_id")]
        public string LeaseId { get; set; } = string.Empty;

        [JsonProperty("buffer_id")]
        public string BufferId { get; set; } = string.Empty;

        [JsonProperty("descriptor_index")]
        public int DescriptorIndex { get; set; }

        [JsonProperty("descriptor_generation")]
        public long DescriptorGeneration { get; set; }

        [JsonProperty("broker_epoch")]
        public string BrokerEpoch { get; set; } = string.Empty;

        [JsonProperty("layout_fingerprint")]
        public string LayoutFingerprint { get; set; } = string.Empty;

        [JsonProperty("offset")]
        public long Offset { get; set; }

        [JsonProperty("content_length")]
        public long ContentLength { get; set; }

        [JsonProperty("allocation_capacity_bytes")]
        public long AllocationCapacityBytes { get; set; }
    }

    internal sealed class WorkflowTriggerRequestPayload
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = "amvision.workflow-trigger-request.v1";

        [JsonProperty("trigger_source_id")]
        public string TriggerSourceId { get; set; } = string.Empty;

        [JsonProperty("event_id")]
        public string EventId { get; set; } = string.Empty;

        [JsonProperty("payload")]
        public IDictionary<string, object?> Payload { get; set; } = new Dictionary<string, object?>();

        [JsonProperty("metadata")]
        public IDictionary<string, object?> Metadata { get; set; } = new Dictionary<string, object?>();

        [JsonProperty("trace_id")]
        public string? TraceId { get; set; }

        [JsonProperty("idempotency_key")]
        public string? IdempotencyKey { get; set; }
    }

    internal sealed class PublicPhysicalPayload
    {
        [JsonProperty("payload_id")]
        public string PayloadId { get; set; } = string.Empty;

        [JsonProperty("delivery_kind")]
        public string DeliveryKind { get; set; } = string.Empty;

        [JsonProperty("media_type")]
        public string MediaType { get; set; } = string.Empty;

        [JsonProperty("content_length")]
        public long ContentLength { get; set; }

        [JsonProperty("checksum_algorithm")]
        public string ChecksumAlgorithm { get; set; } = string.Empty;

        [JsonProperty("checksum")]
        public string Checksum { get; set; } = string.Empty;

        [JsonProperty("buffer_ref")]
        public JObject? BufferRef { get; set; }
    }

    internal sealed class PublicLogicalAttachment
    {
        [JsonProperty("attachment_id")]
        public string AttachmentId { get; set; } = string.Empty;

        [JsonProperty("binding_id")]
        public string BindingId { get; set; } = string.Empty;

        [JsonProperty("item_index")]
        public int ItemIndex { get; set; }

        [JsonProperty("payload_id")]
        public string PayloadId { get; set; } = string.Empty;
    }
}
