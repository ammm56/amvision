using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.Workflows
{

    /// <summary>
    /// WorkflowAppRuntime 响应模型。
    /// </summary>
    public sealed class WorkflowAppRuntimeResponse
    {
        [JsonPropertyName("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonPropertyName("workflow_runtime_id")]
        public string WorkflowRuntimeId { get; set; } = string.Empty;

        [JsonPropertyName("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonPropertyName("application_id")]
        public string ApplicationId { get; set; } = string.Empty;

        [JsonPropertyName("execution_policy_id")]
        public string? ExecutionPolicyId { get; set; }

        [JsonPropertyName("display_name")]
        public string DisplayName { get; set; } = string.Empty;

        [JsonPropertyName("desired_state")]
        public string DesiredState { get; set; } = string.Empty;

        [JsonPropertyName("observed_state")]
        public string ObservedState { get; set; } = string.Empty;

        [JsonPropertyName("worker_process_id")]
        public int? WorkerProcessId { get; set; }

        [JsonPropertyName("last_started_at")]
        public string? LastStartedAt { get; set; }

        [JsonPropertyName("last_stopped_at")]
        public string? LastStoppedAt { get; set; }

        [JsonPropertyName("heartbeat_at")]
        public string? HeartbeatAt { get; set; }

        [JsonPropertyName("last_error")]
        public JsonElement? LastError { get; set; }

        [JsonPropertyName("health_summary")]
        public IDictionary<string, JsonElement> HealthSummary { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("metadata")]
        public IDictionary<string, JsonElement> Metadata { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("created_at")]
        public string CreatedAt { get; set; } = string.Empty;

        [JsonPropertyName("updated_at")]
        public string UpdatedAt { get; set; } = string.Empty;
    }

    /// <summary>
    /// WorkflowAppRuntime 事件响应模型。
    /// </summary>
    public sealed class WorkflowAppRuntimeEventResponse
    {
        [JsonPropertyName("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonPropertyName("workflow_runtime_id")]
        public string WorkflowRuntimeId { get; set; } = string.Empty;

        [JsonPropertyName("sequence")]
        public long Sequence { get; set; }

        [JsonPropertyName("event_type")]
        public string EventType { get; set; } = string.Empty;

        [JsonPropertyName("occurred_at")]
        public string OccurredAt { get; set; } = string.Empty;

        [JsonPropertyName("payload")]
        public IDictionary<string, JsonElement> Payload { get; set; } = new Dictionary<string, JsonElement>();
    }

    /// <summary>
    /// WorkflowAppRuntime worker instance 响应模型。
    /// </summary>
    public sealed class WorkflowAppRuntimeInstanceResponse
    {
        [JsonPropertyName("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonPropertyName("workflow_runtime_id")]
        public string WorkflowRuntimeId { get; set; } = string.Empty;

        [JsonPropertyName("instance_id")]
        public string InstanceId { get; set; } = string.Empty;

        [JsonPropertyName("state")]
        public string State { get; set; } = string.Empty;

        [JsonPropertyName("process_id")]
        public int? ProcessId { get; set; }

        [JsonPropertyName("health_summary")]
        public IDictionary<string, JsonElement> HealthSummary { get; set; } = new Dictionary<string, JsonElement>();
    }
}
