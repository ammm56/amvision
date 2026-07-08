using System;
using System.Collections.Generic;

namespace Amvision.Workflows;

/// <summary>
/// 模型部署 runtime 模式常量。
/// </summary>
public static class ModelDeploymentRuntimeModes
{
    /// <summary>
    /// 同步推理 runtime。
    /// </summary>
    public const string Sync = "sync";

    /// <summary>
    /// 异步推理 runtime。
    /// </summary>
    public const string Async = "async";

    private static readonly HashSet<string> AllowedValues = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        Sync,
        Async
    };

    /// <summary>
    /// 校验并规范化模型部署 runtime 模式。
    /// </summary>
    /// <param name="runtimeMode">runtime 模式。</param>
    /// <returns>后端 API 使用的小写 runtime 模式。</returns>
    public static string Normalize(string runtimeMode)
    {
        if (string.IsNullOrWhiteSpace(runtimeMode))
        {
            throw new ArgumentException("runtimeMode cannot be empty.", nameof(runtimeMode));
        }

        var normalized = runtimeMode.Trim().ToLowerInvariant();
        if (!AllowedValues.Contains(normalized))
        {
            throw new ArgumentException($"Unsupported model deployment runtime mode: {runtimeMode}.", nameof(runtimeMode));
        }

        return normalized;
    }
}
