using System;

namespace Amvision.Workflows.Net461Console.Model;

/// <summary>
/// 配置模型共用的校验和字符串归一化工具。
/// </summary>
internal static class ConfigValidation
{
    /// <summary>
    /// 要求字符串字段非空，并返回去除首尾空白后的值。
    /// </summary>
    /// <param name="value">待校验的字符串。</param>
    /// <param name="path">配置字段路径。</param>
    /// <returns>去除首尾空白后的字符串。</returns>
    public static string RequireText(string? value, string path)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new InvalidOperationException($"{path} cannot be empty.");
        }

        return value!.Trim();
    }

    /// <summary>
    /// 将可选字符串归一化为空值或去除首尾空白后的值。
    /// </summary>
    /// <param name="value">待归一化的字符串。</param>
    /// <returns>空白字符串返回 null，否则返回去除首尾空白后的值。</returns>
    public static string? NormalizeOptional(string? value)
    {
        if (value is null)
        {
            return null;
        }

        var normalized = value.Trim();
        return normalized.Length == 0 ? null : normalized;
    }
}
