using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.Workflows
{

    /// <summary>
    /// backend-service 统一配置快照响应。
    /// </summary>
    public sealed class SystemConfigResponse
    {
        /// <summary>
        /// 配置快照格式 id。
        /// </summary>
        [JsonPropertyName("format_id")]
        public string FormatId { get; set; } = string.Empty;

        /// <summary>
        /// 当前进程已解析并合并后的配置。敏感字段已由服务端遮蔽。
        /// </summary>
        [JsonPropertyName("config")]
        public IDictionary<string, JsonElement> Config { get; set; } = new Dictionary<string, JsonElement>();

        /// <summary>
        /// 配置快照附加信息。
        /// </summary>
        [JsonPropertyName("metadata")]
        public IDictionary<string, JsonElement> Metadata { get; set; } = new Dictionary<string, JsonElement>();

        /// <summary>
        /// LocalBufferBroker 配置；当前后端未返回该配置时为空。
        /// </summary>
        [JsonIgnore]
        public LocalBufferBrokerConfig? LocalBufferBroker
        {
            get
            {
                if (!Config.TryGetValue("local_buffer_broker", out var element)
                    || element.ValueKind == JsonValueKind.Null
                    || element.ValueKind == JsonValueKind.Undefined)
                {
                    return null;
                }

                return element.Deserialize<LocalBufferBrokerConfig>(WorkflowJsonDefaults.SerializerOptions);
            }
        }
    }

    /// <summary>
    /// LocalBufferBroker 配置摘要。
    /// </summary>
    public sealed class LocalBufferBrokerConfig
    {
        [JsonPropertyName("enabled")]
        public bool Enabled { get; set; }

        [JsonPropertyName("root_dir")]
        public string RootDir { get; set; } = string.Empty;

        [JsonPropertyName("startup_timeout_seconds")]
        public double StartupTimeoutSeconds { get; set; }

        [JsonPropertyName("request_timeout_seconds")]
        public double RequestTimeoutSeconds { get; set; }

        [JsonPropertyName("shutdown_timeout_seconds")]
        public double ShutdownTimeoutSeconds { get; set; }

        [JsonPropertyName("expire_interval_seconds")]
        public double ExpireIntervalSeconds { get; set; }

        [JsonPropertyName("default_pool_name")]
        public string DefaultPoolName { get; set; } = string.Empty;

        [JsonPropertyName("pools")]
        public List<LocalBufferBrokerPoolConfig> Pools { get; set; } = new List<LocalBufferBrokerPoolConfig>();
    }

    /// <summary>
    /// LocalBufferBroker mmap pool 配置摘要。
    /// </summary>
    public sealed class LocalBufferBrokerPoolConfig
    {
        [JsonPropertyName("pool_name")]
        public string PoolName { get; set; } = string.Empty;

        [JsonPropertyName("slot_size_bytes")]
        public long SlotSizeBytes { get; set; }

        [JsonPropertyName("slot_count")]
        public int SlotCount { get; set; }

        [JsonPropertyName("flush_on_write")]
        public bool FlushOnWrite { get; set; }

        [JsonPropertyName("file_name")]
        public string FileName { get; set; } = string.Empty;

        [JsonPropertyName("file_size_bytes")]
        public long FileSizeBytes { get; set; }
    }
}
