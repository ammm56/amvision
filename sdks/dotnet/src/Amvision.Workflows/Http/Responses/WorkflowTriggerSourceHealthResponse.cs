using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.Workflows
{

    /// <summary>
    /// WorkflowTriggerSource health 摘要。
    /// </summary>
    public sealed class WorkflowTriggerSourceHealthSummary
    {
        [JsonPropertyName("adapter_configured")]
        public bool AdapterConfigured { get; set; }

        [JsonPropertyName("adapter_running")]
        public bool AdapterRunning { get; set; }

        [JsonPropertyName("request_count")]
        public int RequestCount { get; set; }

        [JsonPropertyName("success_count")]
        public int SuccessCount { get; set; }

        [JsonPropertyName("error_count")]
        public int ErrorCount { get; set; }

        [JsonPropertyName("timeout_count")]
        public int TimeoutCount { get; set; }

        [JsonPropertyName("recent_error")]
        public JsonElement? RecentError { get; set; }

        [JsonPropertyName("supervisor")]
        public IDictionary<string, JsonElement> Supervisor { get; set; } = new Dictionary<string, JsonElement>();
    }

    /// <summary>
    /// WorkflowTriggerSource health 响应模型。
    /// </summary>
    public sealed class WorkflowTriggerSourceHealthResponse
    {
        [JsonPropertyName("trigger_source_id")]
        public string TriggerSourceId { get; set; } = string.Empty;

        [JsonPropertyName("enabled")]
        public bool Enabled { get; set; }

        [JsonPropertyName("desired_state")]
        public string DesiredState { get; set; } = string.Empty;

        [JsonPropertyName("observed_state")]
        public string ObservedState { get; set; } = string.Empty;

        [JsonPropertyName("last_triggered_at")]
        public string? LastTriggeredAt { get; set; }

        [JsonPropertyName("last_error")]
        public JsonElement? LastError { get; set; }

        [JsonPropertyName("health_summary")]
        public WorkflowTriggerSourceHealthSummary HealthSummary { get; set; } = new WorkflowTriggerSourceHealthSummary();
    }
}
