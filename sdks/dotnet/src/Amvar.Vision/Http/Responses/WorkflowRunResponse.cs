using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json;

namespace Amvar.Vision
{

    /// <summary>
    /// WorkflowRun 响应模型。
    /// </summary>
    public sealed class WorkflowRunResponse
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonProperty("workflow_run_id")]
        public string WorkflowRunId { get; set; } = string.Empty;

        [JsonProperty("workflow_runtime_id")]
        public string? WorkflowRuntimeId { get; set; }

        [JsonProperty("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonProperty("application_id")]
        public string ApplicationId { get; set; } = string.Empty;

        [JsonProperty("state")]
        public string State { get; set; } = string.Empty;

        [JsonProperty("input_payload")]
        public IDictionary<string, JToken> InputPayload { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("outputs")]
        public IDictionary<string, JToken> Outputs { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("template_outputs")]
        public IDictionary<string, JToken> TemplateOutputs { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("node_records")]
        public IList<JToken> NodeRecords { get; set; } = new List<JToken>();

        [JsonProperty("error_message")]
        public string? ErrorMessage { get; set; }

        [JsonProperty("metadata")]
        public IDictionary<string, JToken> Metadata { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("created_at")]
        public string CreatedAt { get; set; } = string.Empty;

        [JsonProperty("updated_at")]
        public string UpdatedAt { get; set; } = string.Empty;
    }

    /// <summary>
    /// WorkflowRun 事件响应模型。
    /// </summary>
    public sealed class WorkflowRunEventResponse
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonProperty("workflow_run_id")]
        public string WorkflowRunId { get; set; } = string.Empty;

        [JsonProperty("sequence")]
        public long Sequence { get; set; }

        [JsonProperty("event_type")]
        public string EventType { get; set; } = string.Empty;

        [JsonProperty("occurred_at")]
        public string OccurredAt { get; set; } = string.Empty;

        [JsonProperty("payload")]
        public IDictionary<string, JToken> Payload { get; set; } = new Dictionary<string, JToken>();
    }
}
