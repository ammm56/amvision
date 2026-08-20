using System;
using Newtonsoft.Json;

namespace Amvar.Vision
{

    /// <summary>
    /// WorkflowAppRuntime 停机选择版本请求。
    /// </summary>
    public sealed class WorkflowAppRuntimeSelectVersionRequest
    {
        [JsonProperty("workflow_app_version_id")]
        public string WorkflowAppVersionId { get; set; } = string.Empty;

        [JsonProperty("expected_generation")]
        public int ExpectedGeneration { get; set; }

        [JsonProperty("allow_breaking_contract")]
        public bool AllowBreakingContract { get; set; }

        [JsonProperty("breaking_change_reason")]
        public string? BreakingChangeReason { get; set; }

        /// <summary>
        /// 校验停机版本选择的公开请求边界。
        /// </summary>
        internal void Validate()
        {
            if (string.IsNullOrWhiteSpace(WorkflowAppVersionId))
            {
                throw new ArgumentException(
                    "WorkflowAppVersionId cannot be empty.",
                    nameof(WorkflowAppVersionId));
            }

            if (ExpectedGeneration < 0)
            {
                throw new ArgumentOutOfRangeException(
                    nameof(ExpectedGeneration),
                    "ExpectedGeneration cannot be negative.");
            }

            if (BreakingChangeReason != null && BreakingChangeReason.Length > 2048)
            {
                throw new ArgumentException(
                    "BreakingChangeReason cannot exceed 2048 characters.",
                    nameof(BreakingChangeReason));
            }
        }
    }
}
