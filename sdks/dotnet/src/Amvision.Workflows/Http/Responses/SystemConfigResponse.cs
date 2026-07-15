using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

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
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        /// <summary>
        /// 当前进程已解析并合并后的配置。敏感字段已由服务端遮蔽。
        /// </summary>
        [JsonProperty("config")]
        public IDictionary<string, JToken> Config { get; set; } = new Dictionary<string, JToken>();

        /// <summary>
        /// 配置快照附加信息。
        /// </summary>
        [JsonProperty("metadata")]
        public IDictionary<string, JToken> Metadata { get; set; } = new Dictionary<string, JToken>();

        /// <summary>
        /// LocalBufferBroker 配置；当前后端未返回该配置时为空。
        /// </summary>
        [JsonIgnore]
        public LocalBufferBrokerConfig? LocalBufferBroker
        {
            get
            {
                if (!Config.TryGetValue("local_buffer_broker", out var element)
                    || element.Type == JTokenType.Null
                    || element.Type == JTokenType.Undefined)
                {
                    return null;
                }

                return WorkflowJsonDefaults.ToObject<LocalBufferBrokerConfig>(element);
            }
        }
    }

    /// <summary>
    /// LocalBufferBroker 配置摘要。
    /// </summary>
    public sealed class LocalBufferBrokerConfig
    {
        [JsonProperty("enabled")]
        public bool Enabled { get; set; }

        [JsonProperty("root_dir")]
        public string RootDir { get; set; } = string.Empty;

        [JsonProperty("startup_timeout_seconds")]
        public double StartupTimeoutSeconds { get; set; }

        [JsonProperty("request_timeout_seconds")]
        public double RequestTimeoutSeconds { get; set; }

        [JsonProperty("shutdown_timeout_seconds")]
        public double ShutdownTimeoutSeconds { get; set; }

        [JsonProperty("expire_interval_seconds")]
        public double ExpireIntervalSeconds { get; set; }

        [JsonProperty("default_pool_name")]
        public string DefaultPoolName { get; set; } = string.Empty;

        [JsonProperty("pools")]
        public List<LocalBufferBrokerPoolConfig> Pools { get; set; } = new List<LocalBufferBrokerPoolConfig>();
    }

    /// <summary>
    /// LocalBufferBroker mmap pool 配置摘要。
    /// </summary>
    public sealed class LocalBufferBrokerPoolConfig
    {
        [JsonProperty("pool_name")]
        public string PoolName { get; set; } = string.Empty;

        [JsonProperty("slot_size_bytes")]
        public long SlotSizeBytes { get; set; }

        [JsonProperty("slot_count")]
        public int SlotCount { get; set; }

        [JsonProperty("flush_on_write")]
        public bool FlushOnWrite { get; set; }

        [JsonProperty("file_name")]
        public string FileName { get; set; } = string.Empty;

        [JsonProperty("file_size_bytes")]
        public long FileSizeBytes { get; set; }
    }
}
