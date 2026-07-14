using System;
using System.Collections.Generic;

namespace Amvision.Workflows
{

    /// <summary>
    /// 模型任务类型常量。
    /// </summary>
    public static class ModelTaskTypes
    {
        /// <summary>
        /// Detection 模型。
        /// </summary>
        public const string Detection = "detection";

        /// <summary>
        /// Classification 模型。
        /// </summary>
        public const string Classification = "classification";

        /// <summary>
        /// Segmentation 模型。
        /// </summary>
        public const string Segmentation = "segmentation";

        /// <summary>
        /// Pose 模型。
        /// </summary>
        public const string Pose = "pose";

        /// <summary>
        /// OBB 模型。
        /// </summary>
        public const string Obb = "obb";

        private static readonly HashSet<string> AllowedValues = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            Detection,
            Classification,
            Segmentation,
            Pose,
            Obb
        };

        /// <summary>
        /// 校验并规范化模型任务类型。
        /// </summary>
        /// <param name="taskType">模型任务类型。</param>
        /// <returns>后端 API 使用的小写任务类型。</returns>
        public static string Normalize(string taskType)
        {
            if (string.IsNullOrWhiteSpace(taskType))
            {
                throw new ArgumentException("taskType cannot be empty.", nameof(taskType));
            }

            var normalized = taskType.Trim().ToLowerInvariant();
            if (!AllowedValues.Contains(normalized))
            {
                throw new ArgumentException($"Unsupported model task type: {taskType}.", nameof(taskType));
            }

            return normalized;
        }
    }
}
