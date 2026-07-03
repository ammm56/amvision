using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Amvision.Workflows.Net461Console.Model;

namespace Amvision.Workflows.Net461Console.Tools;

/// <summary>
/// 从 Config/config_*.json 读取全部现场配置，并构建 runtime / TriggerSource 配置索引。
/// </summary>
internal static class WorkflowConfigLoader
{
    /// <summary>
    /// System.Text.Json 反序列化选项，允许配置文件保留注释和尾逗号，方便现场维护。
    /// </summary>
    private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    /// <summary>
    /// 从默认 Config 目录加载全部 config_*.json。
    /// </summary>
    /// <returns>按 runtime key 和 TriggerSource key 索引好的配置 catalog。</returns>
    public static WorkflowConfigurationCatalog LoadDefault()
    {
        return LoadDirectory(FindConfigDirectory());
    }

    /// <summary>
    /// 从指定目录加载所有 config_*.json，并校验 key 唯一性和 runtime 关联。
    /// </summary>
    /// <param name="configDirectory">Config 目录路径。</param>
    /// <returns>按 key 查询的配置 catalog。</returns>
    public static WorkflowConfigurationCatalog LoadDirectory(string configDirectory)
    {
        var normalizedDirectory = Path.GetFullPath(ConfigValidation.RequireText(configDirectory, nameof(configDirectory)));
        if (!Directory.Exists(normalizedDirectory))
        {
            throw new DirectoryNotFoundException($"Config directory does not exist: {normalizedDirectory}");
        }

        var files = Directory.GetFiles(normalizedDirectory, "config_*.json")
            .OrderBy(item => item, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (files.Length == 0)
        {
            throw new FileNotFoundException("No config_*.json files were found in Config directory.", normalizedDirectory);
        }

        var runtimes = new Dictionary<string, ConfiguredRuntime>(StringComparer.OrdinalIgnoreCase);
        var triggerSources = new Dictionary<string, ConfiguredTriggerSource>(StringComparer.OrdinalIgnoreCase);
        foreach (var file in files)
        {
            var config = LoadFile(file);
            var runtime = new ConfiguredRuntime(config.Backend, config.Runtime, config.Invoke, config.Cleanup, file);
            if (runtimes.ContainsKey(config.Runtime.Name))
            {
                throw new InvalidOperationException($"Duplicate runtime config key: {config.Runtime.Name}");
            }

            runtimes[config.Runtime.Name] = runtime;
            foreach (var triggerSource in config.TriggerSources)
            {
                if (!string.Equals(triggerSource.WorkflowRuntimeName, config.Runtime.Name, StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidOperationException(
                        $"TriggerSource {triggerSource.Name} references runtime {triggerSource.WorkflowRuntimeName}, but the config file runtime is {config.Runtime.Name}.");
                }

                if (triggerSources.ContainsKey(triggerSource.Name))
                {
                    throw new InvalidOperationException($"Duplicate TriggerSource config key: {triggerSource.Name}");
                }

                triggerSources[triggerSource.Name] = new ConfiguredTriggerSource(
                    config.Backend,
                    config.Runtime,
                    triggerSource,
                    file);
            }
        }

        return new WorkflowConfigurationCatalog(runtimes, triggerSources);
    }

    /// <summary>
    /// 读取单个配置文件，并执行完整字段校验。
    /// </summary>
    /// <param name="configPath">配置文件路径。</param>
    /// <returns>反序列化后的配置文件模型。</returns>
    private static WorkflowAppConfigFile LoadFile(string configPath)
    {
        var json = File.ReadAllText(configPath);
        var config = JsonSerializer.Deserialize<WorkflowAppConfigFile>(json, JsonOptions)
            ?? throw new InvalidOperationException($"Config file cannot be deserialized: {configPath}");
        config.Validate(Path.GetFileName(configPath));
        return config;
    }

    /// <summary>
    /// 查找包含 config_*.json 的 Config 目录，兼容开发态和发布态路径。
    /// </summary>
    /// <returns>可用的 Config 目录路径。</returns>
    private static string FindConfigDirectory()
    {
        foreach (var candidate in EnumerateCandidateDirectories())
        {
            if (Directory.Exists(candidate)
                && Directory.GetFiles(candidate, "config_*.json").Length > 0)
            {
                return candidate;
            }
        }

        throw new DirectoryNotFoundException("Cannot find Config directory with config_*.json files.");
    }

    /// <summary>
    /// 按优先级枚举候选 Config 目录。
    /// </summary>
    /// <returns>候选目录路径序列。</returns>
    private static IEnumerable<string> EnumerateCandidateDirectories()
    {
        var baseDirectory = AppDomain.CurrentDomain.BaseDirectory;
        yield return Path.Combine(baseDirectory, "Config");
        yield return Path.Combine(Environment.CurrentDirectory, "Config");

        var directory = new DirectoryInfo(baseDirectory);
        while (directory is not null)
        {
            yield return Path.Combine(directory.FullName, "Config");
            directory = directory.Parent;
        }
    }
}
