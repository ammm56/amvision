using System;
using Newtonsoft.Json;

namespace Amvar.Vision
{

    /// <summary>
    /// Workflow App 发布版本状态转换请求。
    /// </summary>
    public sealed class WorkflowAppVersionStateTransitionRequest
    {
        [JsonProperty("expected_state")]
        public string ExpectedState { get; set; } = string.Empty;

        /// <summary>
        /// 校验 archive/restore 的显式状态 CAS。
        /// </summary>
        internal void Validate(string requiredState)
        {
            if (!string.Equals(ExpectedState, requiredState, StringComparison.Ordinal))
            {
                throw new ArgumentException(
                    "ExpectedState must be '" + requiredState + "' for this operation.",
                    nameof(ExpectedState));
            }
        }
    }
}
