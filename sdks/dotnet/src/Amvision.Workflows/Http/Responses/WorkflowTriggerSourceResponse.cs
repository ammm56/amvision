using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json;

namespace Amvision.Workflows
{

    /// <summary>
    /// WorkflowTriggerSource 响应模型。
    /// </summary>
    public sealed class WorkflowTriggerSourceResponse
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonProperty("trigger_source_id")]
        public string TriggerSourceId { get; set; } = string.Empty;

        [JsonProperty("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonProperty("display_name")]
        public string DisplayName { get; set; } = string.Empty;

        [JsonProperty("trigger_kind")]
        public string TriggerKind { get; set; } = string.Empty;

        [JsonProperty("workflow_runtime_id")]
        public string WorkflowRuntimeId { get; set; } = string.Empty;

        [JsonProperty("submit_mode")]
        public string SubmitMode { get; set; } = string.Empty;

        [JsonProperty("enabled")]
        public bool Enabled { get; set; }

        [JsonProperty("desired_state")]
        public string DesiredState { get; set; } = string.Empty;

        [JsonProperty("observed_state")]
        public string ObservedState { get; set; } = string.Empty;

        [JsonProperty("transport_config")]
        public IDictionary<string, JToken> TransportConfig { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("input_binding_mapping")]
        public IDictionary<string, JToken> InputBindingMapping { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("result_mapping")]
        public JToken? ResultMapping { get; set; }

        [JsonProperty("health_summary")]
        public IDictionary<string, JToken> HealthSummary { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("last_triggered_at")]
        public string? LastTriggeredAt { get; set; }

        [JsonProperty("last_error")]
        public JToken? LastError { get; set; }

        [JsonProperty("metadata")]
        public IDictionary<string, JToken> Metadata { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("created_at")]
        public string CreatedAt { get; set; } = string.Empty;

        [JsonProperty("updated_at")]
        public string UpdatedAt { get; set; } = string.Empty;
    }
}
