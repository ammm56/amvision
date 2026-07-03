using System;
using System.IO;
using System.Text.Json;
using Amvision.Workflows.Examples.Net461Console.Model;

namespace Amvision.Workflows.Examples.Net461Console.Tools;

internal static class ExampleConfigLoader
{
    private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    public static ExampleConfig LoadDefault()
    {
        return Load(FindConfigPath());
    }

    public static ExampleConfig Load(string configPath)
    {
        if (string.IsNullOrWhiteSpace(configPath))
        {
            throw new ArgumentException("configPath cannot be empty.", nameof(configPath));
        }

        var normalizedPath = Path.GetFullPath(configPath.Trim());
        if (!File.Exists(normalizedPath))
        {
            throw new FileNotFoundException("Cannot find console example config.json.", normalizedPath);
        }

        var json = File.ReadAllText(normalizedPath);
        var config = JsonSerializer.Deserialize<ExampleConfig>(json, JsonOptions)
            ?? throw new InvalidOperationException("config.json cannot be deserialized.");
        config.Validate();
        return config;
    }

    private static string FindConfigPath()
    {
        var baseDirectory = AppDomain.CurrentDomain.BaseDirectory;
        var outputConfigPath = Path.Combine(baseDirectory, "config.json");
        if (File.Exists(outputConfigPath))
        {
            return outputConfigPath;
        }

        var currentConfigPath = Path.Combine(Environment.CurrentDirectory, "config.json");
        if (File.Exists(currentConfigPath))
        {
            return currentConfigPath;
        }

        var directory = new DirectoryInfo(baseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "config.json");
            if (File.Exists(candidate))
            {
                return candidate;
            }

            directory = directory.Parent;
        }

        throw new FileNotFoundException(
            "Cannot find config.json. Keep it beside the example project or copy it to the executable directory.",
            outputConfigPath);
    }
}
