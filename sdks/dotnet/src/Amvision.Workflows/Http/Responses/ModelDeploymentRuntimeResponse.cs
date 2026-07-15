using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json;

namespace Amvision.Workflows
{

    /// <summary>
    /// 模型部署 runtime 进程状态响应。
    /// </summary>
    public class ModelDeploymentRuntimeStatusResponse
    {
        [JsonProperty("deployment_instance_id")]
        public string DeploymentInstanceId { get; set; } = string.Empty;

        [JsonProperty("display_name")]
        public string? DisplayName { get; set; }

        [JsonProperty("runtime_mode")]
        public string RuntimeMode { get; set; } = string.Empty;

        [JsonProperty("desired_state")]
        public string DesiredState { get; set; } = string.Empty;

        [JsonProperty("process_state")]
        public string ProcessState { get; set; } = string.Empty;

        [JsonProperty("process_id")]
        public int? ProcessId { get; set; }

        [JsonProperty("auto_restart")]
        public bool? AutoRestart { get; set; }

        [JsonProperty("restart_count")]
        public int? RestartCount { get; set; }

        [JsonProperty("restart_count_rollover_count")]
        public int? RestartCountRolloverCount { get; set; }

        [JsonProperty("last_exit_code")]
        public int? LastExitCode { get; set; }

        [JsonProperty("last_error")]
        public string? LastError { get; set; }

        [JsonProperty("instance_count")]
        public int? InstanceCount { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JToken> ExtensionData { get; set; } = new Dictionary<string, JToken>();
    }

    /// <summary>
    /// 模型部署 runtime health 响应。
    /// </summary>
    public sealed class ModelDeploymentRuntimeHealthResponse : ModelDeploymentRuntimeStatusResponse
    {
        [JsonProperty("healthy_instance_count")]
        public int? HealthyInstanceCount { get; set; }

        [JsonProperty("warmed_instance_count")]
        public int? WarmedInstanceCount { get; set; }

        [JsonProperty("pinned_output_total_bytes")]
        public long? PinnedOutputTotalBytes { get; set; }

        [JsonProperty("instances")]
        public IList<ModelDeploymentRuntimeInstanceHealthResponse> Instances { get; set; } = new List<ModelDeploymentRuntimeInstanceHealthResponse>();

        [JsonProperty("keep_warm")]
        public IDictionary<string, JToken> KeepWarm { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("local_buffer_broker")]
        public IDictionary<string, JToken> LocalBufferBroker { get; set; } = new Dictionary<string, JToken>();
    }

    /// <summary>
    /// 模型部署 runtime 单个实例 health 响应。
    /// </summary>
    public sealed class ModelDeploymentRuntimeInstanceHealthResponse
    {
        [JsonProperty("instance_id")]
        public string InstanceId { get; set; } = string.Empty;

        [JsonProperty("healthy")]
        public bool? Healthy { get; set; }

        [JsonProperty("warmed")]
        public bool? Warmed { get; set; }

        [JsonProperty("busy")]
        public bool? Busy { get; set; }

        [JsonProperty("last_error")]
        public string? LastError { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JToken> ExtensionData { get; set; } = new Dictionary<string, JToken>();
    }

    /// <summary>
    /// 模型部署 runtime 预热响应。
    /// </summary>
    public sealed class ModelDeploymentRuntimeWarmupResponse
    {
        [JsonProperty("deployment_instance_id")]
        public string DeploymentInstanceId { get; set; } = string.Empty;

        [JsonProperty("runtime_mode")]
        public string RuntimeMode { get; set; } = string.Empty;

        [JsonProperty("warmed_instance_count")]
        public int? WarmedInstanceCount { get; set; }

        [JsonProperty("pinned_output_total_bytes")]
        public long? PinnedOutputTotalBytes { get; set; }

        [JsonProperty("status")]
        public string? Status { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JToken> ExtensionData { get; set; } = new Dictionary<string, JToken>();
    }
}
