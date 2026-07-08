using System;
using System.Collections.Generic;
using System.Globalization;

namespace Amvision.Workflows;

internal static class WorkflowHttpPath
{
    internal static string NormalizeBaseApiUrl(string baseApiUrl)
    {
        var trimmed = baseApiUrl.Trim();
        return trimmed.EndsWith("/", StringComparison.Ordinal) ? trimmed : $"{trimmed}/";
    }

    internal static string WithQuery(string relativePath, params (string Name, object? Value)[] query)
    {
        var items = new List<string>();
        foreach (var (name, value) in query)
        {
            if (value is null)
            {
                continue;
            }

            var text = value is bool boolValue
                ? boolValue.ToString().ToLowerInvariant()
                : Convert.ToString(value, CultureInfo.InvariantCulture);
            if (string.IsNullOrWhiteSpace(text))
            {
                continue;
            }

            items.Add($"{Uri.EscapeDataString(name)}={Uri.EscapeDataString(text)}");
        }

        return items.Count == 0 ? relativePath : $"{relativePath}?{string.Join("&", items)}";
    }

    internal static string RequireId(string value, string paramName)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException($"{paramName} cannot be empty.", paramName);
        }

        return value.Trim();
    }

    internal static string EncodePathSegment(string value)
    {
        return Uri.EscapeDataString(value);
    }
}
