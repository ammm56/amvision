using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.Workflows
{

    /// <summary>
    /// 模型部署 runtime 进程状态响应。
    /// </summary>
    public class ModelDeploymentRuntimeStatusResponse
    {
        [JsonPropertyName("deployment_instance_id")]
        public string DeploymentInstanceId { get; set; } = string.Empty;

        [JsonPropertyName("display_name")]
        public string? DisplayName { get; set; }

        [JsonPropertyName("runtime_mode")]
        public string RuntimeMode { get; set; } = string.Empty;

        [JsonPropertyName("desired_state")]
        public string DesiredState { get; set; } = string.Empty;

        [JsonPropertyName("process_state")]
        public string ProcessState { get; set; } = string.Empty;

        [JsonPropertyName("process_id")]
        public int? ProcessId { get; set; }

        [JsonPropertyName("auto_restart")]
        public bool? AutoRestart { get; set; }

        [JsonPropertyName("restart_count")]
        public int? RestartCount { get; set; }

        [JsonPropertyName("restart_count_rollover_count")]
        public int? RestartCountRolloverCount { get; set; }

        [JsonPropertyName("last_exit_code")]
        public int? LastExitCode { get; set; }

        [JsonPropertyName("last_error")]
        public string? LastError { get; set; }

        [JsonPropertyName("instance_count")]
        public int? InstanceCount { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JsonElement> ExtensionData { get; set; } = new Dictionary<string, JsonElement>();
    }

    /// <summary>
    /// 模型部署 runtime health 响应。
    /// </summary>
    public sealed class ModelDeploymentRuntimeHealthResponse : ModelDeploymentRuntimeStatusResponse
    {
        [JsonPropertyName("healthy_instance_count")]
        public int? HealthyInstanceCount { get; set; }

        [JsonPropertyName("warmed_instance_count")]
        public int? WarmedInstanceCount { get; set; }

        [JsonPropertyName("pinned_output_total_bytes")]
        public long? PinnedOutputTotalBytes { get; set; }

        [JsonPropertyName("instances")]
        public IList<ModelDeploymentRuntimeInstanceHealthResponse> Instances { get; set; } = new List<ModelDeploymentRuntimeInstanceHealthResponse>();

        [JsonPropertyName("keep_warm")]
        public IDictionary<string, JsonElement> KeepWarm { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("local_buffer_broker")]
        public IDictionary<string, JsonElement> LocalBufferBroker { get; set; } = new Dictionary<string, JsonElement>();
    }

    /// <summary>
    /// 模型部署 runtime 单个实例 health 响应。
    /// </summary>
    public sealed class ModelDeploymentRuntimeInstanceHealthResponse
    {
        [JsonPropertyName("instance_id")]
        public string InstanceId { get; set; } = string.Empty;

        [JsonPropertyName("healthy")]
        public bool? Healthy { get; set; }

        [JsonPropertyName("warmed")]
        public bool? Warmed { get; set; }

        [JsonPropertyName("busy")]
        public bool? Busy { get; set; }

        [JsonPropertyName("last_error")]
        public string? LastError { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JsonElement> ExtensionData { get; set; } = new Dictionary<string, JsonElement>();
    }

    /// <summary>
    /// 模型部署 runtime 预热响应。
    /// </summary>
    public sealed class ModelDeploymentRuntimeWarmupResponse
    {
        [JsonPropertyName("deployment_instance_id")]
        public string DeploymentInstanceId { get; set; } = string.Empty;

        [JsonPropertyName("runtime_mode")]
        public string RuntimeMode { get; set; } = string.Empty;

        [JsonPropertyName("warmed_instance_count")]
        public int? WarmedInstanceCount { get; set; }

        [JsonPropertyName("pinned_output_total_bytes")]
        public long? PinnedOutputTotalBytes { get; set; }

        [JsonPropertyName("status")]
        public string? Status { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JsonElement> ExtensionData { get; set; } = new Dictionary<string, JsonElement>();
    }
}
