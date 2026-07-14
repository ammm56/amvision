using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.Workflows
{

    /// <summary>
    /// WorkflowTriggerSource 响应模型。
    /// </summary>
    public sealed class WorkflowTriggerSourceResponse
    {
        [JsonPropertyName("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonPropertyName("trigger_source_id")]
        public string TriggerSourceId { get; set; } = string.Empty;

        [JsonPropertyName("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonPropertyName("display_name")]
        public string DisplayName { get; set; } = string.Empty;

        [JsonPropertyName("trigger_kind")]
        public string TriggerKind { get; set; } = string.Empty;

        [JsonPropertyName("workflow_runtime_id")]
        public string WorkflowRuntimeId { get; set; } = string.Empty;

        [JsonPropertyName("submit_mode")]
        public string SubmitMode { get; set; } = string.Empty;

        [JsonPropertyName("enabled")]
        public bool Enabled { get; set; }

        [JsonPropertyName("desired_state")]
        public string DesiredState { get; set; } = string.Empty;

        [JsonPropertyName("observed_state")]
        public string ObservedState { get; set; } = string.Empty;

        [JsonPropertyName("transport_config")]
        public IDictionary<string, JsonElement> TransportConfig { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("input_binding_mapping")]
        public IDictionary<string, JsonElement> InputBindingMapping { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("result_mapping")]
        public JsonElement? ResultMapping { get; set; }

        [JsonPropertyName("health_summary")]
        public IDictionary<string, JsonElement> HealthSummary { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("last_triggered_at")]
        public string? LastTriggeredAt { get; set; }

        [JsonPropertyName("last_error")]
        public JsonElement? LastError { get; set; }

        [JsonPropertyName("metadata")]
        public IDictionary<string, JsonElement> Metadata { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("created_at")]
        public string CreatedAt { get; set; } = string.Empty;

        [JsonPropertyName("updated_at")]
        public string UpdatedAt { get; set; } = string.Empty;
    }
}
