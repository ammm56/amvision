using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision
{

    /// <summary>
    /// 不可变 Workflow App 发布版本响应。
    /// </summary>
    public sealed class WorkflowAppVersionResponse
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonProperty("workflow_app_version_id")]
        public string WorkflowAppVersionId { get; set; } = string.Empty;

        [JsonProperty("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonProperty("application_id")]
        public string ApplicationId { get; set; } = string.Empty;

        [JsonProperty("version_number")]
        public int VersionNumber { get; set; }

        [JsonProperty("display_version")]
        public string DisplayVersion { get; set; } = string.Empty;

        [JsonProperty("release_notes")]
        public string ReleaseNotes { get; set; } = string.Empty;

        [JsonProperty("application_snapshot_object_key")]
        public string ApplicationSnapshotObjectKey { get; set; } = string.Empty;

        [JsonProperty("template_snapshot_object_key")]
        public string TemplateSnapshotObjectKey { get; set; } = string.Empty;

        [JsonProperty("contract_snapshot_object_key")]
        public string ContractSnapshotObjectKey { get; set; } = string.Empty;

        [JsonProperty("dependency_manifest_object_key")]
        public string DependencyManifestObjectKey { get; set; } = string.Empty;

        [JsonProperty("content_fingerprint")]
        public string ContentFingerprint { get; set; } = string.Empty;

        [JsonProperty("contract_fingerprint")]
        public string ContractFingerprint { get; set; } = string.Empty;

        [JsonProperty("state")]
        public string State { get; set; } = string.Empty;

        [JsonProperty("created_at")]
        public string CreatedAt { get; set; } = string.Empty;

        [JsonProperty("created_by")]
        public string? CreatedBy { get; set; }

        [JsonProperty("completed_at")]
        public string? CompletedAt { get; set; }

        [JsonProperty("error")]
        public JToken? Error { get; set; }
    }
}
