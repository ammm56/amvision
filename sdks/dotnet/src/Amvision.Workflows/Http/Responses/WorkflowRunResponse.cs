using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.Workflows
{

    /// <summary>
    /// WorkflowRun 响应模型。
    /// </summary>
    public sealed class WorkflowRunResponse
    {
        [JsonPropertyName("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonPropertyName("workflow_run_id")]
        public string WorkflowRunId { get; set; } = string.Empty;

        [JsonPropertyName("workflow_runtime_id")]
        public string? WorkflowRuntimeId { get; set; }

        [JsonPropertyName("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonPropertyName("application_id")]
        public string ApplicationId { get; set; } = string.Empty;

        [JsonPropertyName("state")]
        public string State { get; set; } = string.Empty;

        [JsonPropertyName("input_payload")]
        public IDictionary<string, JsonElement> InputPayload { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("outputs")]
        public IDictionary<string, JsonElement> Outputs { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("template_outputs")]
        public IDictionary<string, JsonElement> TemplateOutputs { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("node_records")]
        public IList<JsonElement> NodeRecords { get; set; } = new List<JsonElement>();

        [JsonPropertyName("error_message")]
        public string? ErrorMessage { get; set; }

        [JsonPropertyName("metadata")]
        public IDictionary<string, JsonElement> Metadata { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("created_at")]
        public string CreatedAt { get; set; } = string.Empty;

        [JsonPropertyName("updated_at")]
        public string UpdatedAt { get; set; } = string.Empty;
    }

    /// <summary>
    /// WorkflowRun 事件响应模型。
    /// </summary>
    public sealed class WorkflowRunEventResponse
    {
        [JsonPropertyName("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonPropertyName("workflow_run_id")]
        public string WorkflowRunId { get; set; } = string.Empty;

        [JsonPropertyName("sequence")]
        public long Sequence { get; set; }

        [JsonPropertyName("event_type")]
        public string EventType { get; set; } = string.Empty;

        [JsonPropertyName("occurred_at")]
        public string OccurredAt { get; set; } = string.Empty;

        [JsonPropertyName("payload")]
        public IDictionary<string, JsonElement> Payload { get; set; } = new Dictionary<string, JsonElement>();
    }
}
