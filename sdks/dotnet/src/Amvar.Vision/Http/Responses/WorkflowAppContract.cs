using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision
{
    /// <summary>不可变 Workflow App 公开输入输出契约。</summary>
    public sealed class WorkflowAppContract
    {
        public const string V1FormatId = "amvision.workflow-app-contract.v1";

        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonProperty("application_id")]
        public string ApplicationId { get; set; } = string.Empty;

        [JsonProperty("inputs")]
        public List<WorkflowAppContractInput> Inputs { get; set; } = new List<WorkflowAppContractInput>();

        [JsonProperty("outputs")]
        public List<JObject> Outputs { get; set; } = new List<JObject>();

        /// <summary>校验 v1 公开契约的完整形状。</summary>
        public void Validate(string path)
        {
            if (FormatId != V1FormatId)
            {
                throw new InvalidOperationException(path + ".format_id is unsupported.");
            }
            if (string.IsNullOrWhiteSpace(ApplicationId))
            {
                throw new InvalidOperationException(path + ".application_id cannot be empty.");
            }
            Inputs ??= new List<WorkflowAppContractInput>();
            var ids = new HashSet<string>(StringComparer.Ordinal);
            for (var index = 0; index < Inputs.Count; index++)
            {
                Inputs[index].Validate(path + ".inputs[" + index + "]");
                if (!ids.Add(Inputs[index].BindingId))
                {
                    throw new InvalidOperationException(path + ".inputs contains duplicate binding_id.");
                }
            }
        }
    }

    /// <summary>Workflow App 一个公开输入 binding 的冻结规则。</summary>
    public sealed class WorkflowAppContractInput
    {
        [JsonProperty("binding_id")]
        public string BindingId { get; set; } = string.Empty;

        [JsonProperty("payload_type_id")]
        public string PayloadTypeId { get; set; } = string.Empty;

        [JsonProperty("required")]
        public bool Required { get; set; }

        [JsonProperty("payload_schema")]
        public JObject? PayloadSchema { get; set; }

        [JsonProperty("request_schema")]
        public JObject? RequestSchema { get; set; }

        [JsonProperty("allowed_media_types")]
        public List<string> AllowedMediaTypes { get; set; } = new List<string>();

        [JsonProperty("max_inline_bytes")]
        public long? MaxInlineBytes { get; set; }

        [JsonProperty("max_file_bytes")]
        public long? MaxFileBytes { get; set; }

        [JsonProperty("max_files")]
        public int? MaxFiles { get; set; }

        [JsonProperty("transports")]
        public List<string> Transports { get; set; } = new List<string>();

        [JsonProperty("charset")]
        public string? Charset { get; set; }

        internal void Validate(string path)
        {
            if (string.IsNullOrWhiteSpace(BindingId))
            {
                throw new InvalidOperationException(path + ".binding_id cannot be empty.");
            }
            BindingId = BindingId.Trim();
            if (string.IsNullOrWhiteSpace(PayloadTypeId))
            {
                throw new InvalidOperationException(path + ".payload_type_id cannot be empty.");
            }
            PayloadTypeId = PayloadTypeId.Trim();
            AllowedMediaTypes ??= new List<string>();
            Transports ??= new List<string>();
            if (PayloadSchema is null)
            {
                throw new InvalidOperationException(path + ".payload_schema is required.");
            }
            ValidatePositive(MaxInlineBytes, path + ".max_inline_bytes");
            ValidatePositive(MaxFileBytes, path + ".max_file_bytes");
            if (MaxFiles != null && MaxFiles.Value <= 0)
            {
                throw new InvalidOperationException(path + ".max_files must be greater than zero.");
            }
            if (Transports.Count == 0)
            {
                throw new InvalidOperationException(path + ".transports cannot be empty.");
            }
        }

        private static void ValidatePositive(long? value, string path)
        {
            if (value != null && value.Value <= 0)
            {
                throw new InvalidOperationException(path + " must be greater than zero.");
            }
        }
    }
}
