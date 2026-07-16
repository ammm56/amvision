using Amvar.Vision;
using System;
using System.Collections.Generic;
using System.IO;

namespace Amvar.Vision.Tools
{
/// <summary>
/// 解析 config*.json 和代码入参中的本地文件路径，统一处理开发态和 bin 输出目录。
/// </summary>
internal static class ConfiguredPathResolver
{
    /// <summary>
    /// 将本地文件路径解析为存在的绝对路径；相对路径会按程序目录、当前目录、Config 上级目录、Config 目录依次查找。
    /// </summary>
    /// <param name="configuredPath">配置或代码中传入的路径。</param>
    /// <param name="sourceFile">配置文件路径；代码直接传入路径时可为空。</param>
    /// <param name="message">文件不存在时的错误提示。</param>
    /// <returns>存在的绝对文件路径。</returns>
    public static string ResolveExistingFile(string configuredPath, string? sourceFile, string message)
    {
        var candidates = new List<string>();
        foreach (var candidate in EnumerateCandidates(configuredPath, sourceFile))
        {
            candidates.Add(candidate);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        var firstCandidate = candidates.Count > 0 ? candidates[0] : configuredPath;
        throw new FileNotFoundException(
            $"{message} Searched paths: {string.Join("; ", candidates)}",
            firstCandidate);
    }

    /// <summary>
    /// 将路径解析为绝对路径；文件是否存在由调用方决定。
    /// </summary>
    /// <param name="configuredPath">配置或代码中传入的路径。</param>
    /// <param name="sourceFile">配置文件路径；代码直接传入路径时可为空。</param>
    /// <returns>优先级最高的绝对路径候选。</returns>
    public static string ResolvePath(string configuredPath, string? sourceFile)
    {
        foreach (var candidate in EnumerateCandidates(configuredPath, sourceFile))
        {
            return candidate;
        }

        throw new ArgumentException("configuredPath cannot be empty.", nameof(configuredPath));
    }

    /// <summary>
    /// 枚举路径候选，避免 Config 目录和程序资源目录之间的相对路径误判。
    /// </summary>
    /// <param name="configuredPath">配置或代码中传入的路径。</param>
    /// <param name="sourceFile">配置文件路径；代码直接传入路径时可为空。</param>
    /// <returns>去重后的绝对路径候选。</returns>
    private static IEnumerable<string> EnumerateCandidates(string configuredPath, string? sourceFile)
    {
        var normalizedPath = RequireText(configuredPath, nameof(configuredPath));
        if (Path.IsPathRooted(normalizedPath))
        {
            yield return Path.GetFullPath(normalizedPath);
            yield break;
        }

        var emitted = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var baseDirectory in EnumerateBaseDirectories(sourceFile))
        {
            var candidate = Path.GetFullPath(Path.Combine(baseDirectory, normalizedPath));
            if (emitted.Add(candidate))
            {
                yield return candidate;
            }
        }
    }

    /// <summary>
    /// 枚举相对路径的基准目录，优先匹配发布输出目录中的 Resources。
    /// </summary>
    /// <param name="sourceFile">配置文件路径；代码直接传入路径时可为空。</param>
    /// <returns>基准目录序列。</returns>
    private static IEnumerable<string> EnumerateBaseDirectories(string? sourceFile)
    {
        yield return AppDomain.CurrentDomain.BaseDirectory;
        yield return Environment.CurrentDirectory;

        if (!string.IsNullOrWhiteSpace(sourceFile))
        {
            var sourceDirectory = Path.GetDirectoryName(Path.GetFullPath(sourceFile));
            if (!string.IsNullOrWhiteSpace(sourceDirectory))
            {
                var parentDirectory = Directory.GetParent(sourceDirectory);
                if (parentDirectory != null)
                {
                    yield return parentDirectory.FullName;
                }

                yield return sourceDirectory;
            }
        }
    }

    /// <summary>
    /// 校验字符串参数不为空并去除首尾空白。
    /// </summary>
    /// <param name="value">参数值。</param>
    /// <param name="parameterName">参数名。</param>
    /// <returns>清理后的字符串。</returns>
    private static string RequireText(string value, string parameterName)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException($"{parameterName} cannot be empty.", parameterName);
        }

        return value.Trim();
    }
}
}
