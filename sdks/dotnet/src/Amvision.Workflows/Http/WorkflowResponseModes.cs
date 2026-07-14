using System;

namespace Amvision.Workflows
{

    /// <summary>
    /// Workflow runtime invoke 和 run 查询的响应模式常量。
    /// </summary>
    public static class WorkflowResponseModes
    {
        /// <summary>
        /// 只返回公开 App Result。
        /// </summary>
        public const string AppResult = "app-result";

        /// <summary>
        /// 返回 WorkflowRun 运行回执。
        /// </summary>
        public const string Run = "run";

        /// <summary>
        /// 返回完整调试 trace。
        /// </summary>
        public const string Debug = "debug";

        /// <summary>
        /// 规范化响应模式字符串。
        /// </summary>
        /// <param name="responseMode">原始响应模式。</param>
        /// <returns>后端接受的响应模式。</returns>
        public static string Normalize(string responseMode)
        {
            if (string.IsNullOrWhiteSpace(responseMode))
            {
                return Run;
            }

            var normalized = responseMode.Trim().ToLowerInvariant().Replace("_", "-");
            switch (normalized)
            {
                case AppResult:
                case "result":
                    return AppResult;
                case Run:
                    return Run;
                case Debug:
                    return Debug;
                default:
                    throw new ArgumentException(
                    "responseMode must be app-result, run, or debug.",
                    nameof(responseMode));
            }
        }
    }
}
