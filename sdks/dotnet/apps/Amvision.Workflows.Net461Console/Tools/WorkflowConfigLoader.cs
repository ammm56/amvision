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
    /// 根节点允许的字段；用于阻止旧配置字段被 JSON 反序列化静默忽略。
    /// </summary>
    private static readonly ISet<string> RootPropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "backend",
        "runtime",
        "invoke",
        "trigger_sources"
    };

    /// <summary>
    /// backend 节点允许的字段。
    /// </summary>
    private static readonly ISet<string> BackendPropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "base_api_url",
        "access_token",
        "project_id",
        "http_timeout_seconds"
    };

    /// <summary>
    /// runtime 节点允许的字段；创建参数不属于本程序职责。
    /// </summary>
    private static readonly ISet<string> RuntimePropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "name",
        "workflow_runtime_id"
    };

    /// <summary>
    /// invoke 节点允许的字段。
    /// </summary>
    private static readonly ISet<string> InvokePropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "image_path",
        "image_input_binding",
        "timeout_seconds",
        "event_limit",
        "event_preview_count",
        "source",
        "sync_scenario",
        "async_scenario",
        "use_direct_input_bindings"
    };

    /// <summary>
    /// trigger_sources[] 节点允许的字段；TriggerSource 创建参数由前端维护。
    /// </summary>
    private static readonly ISet<string> TriggerSourcePropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "name",
        "trigger_source_id",
        "zero_mq"
    };

    /// <summary>
    /// zero_mq 节点允许的调用字段。
    /// </summary>
    private static readonly ISet<string> ZeroMqPropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "bind_endpoint",
        "default_input_binding",
        "timeout_seconds"
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
            var runtime = new ConfiguredRuntime(config.Backend, config.Runtime, config.Invoke, file);
            if (runtimes.ContainsKey(config.Runtime.Name))
            {
                throw new InvalidOperationException($"Duplicate runtime config key: {config.Runtime.Name}");
            }

            runtimes[config.Runtime.Name] = runtime;
            foreach (var triggerSource in config.TriggerSources)
            {
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
        ValidateKnownProperties(configPath, json);
        var config = JsonSerializer.Deserialize<WorkflowAppConfigFile>(json, JsonOptions)
            ?? throw new InvalidOperationException($"Config file cannot be deserialized: {configPath}");
        config.Validate(Path.GetFileName(configPath));
        return config;
    }

    /// <summary>
    /// 校验配置文件只包含当前程序支持的字段，避免旧 config 字段被静默忽略。
    /// </summary>
    /// <param name="configPath">配置文件路径。</param>
    /// <param name="json">配置文件 JSON 内容。</param>
    private static void ValidateKnownProperties(string configPath, string json)
    {
        using var document = JsonDocument.Parse(
            json,
            new JsonDocumentOptions
            {
                CommentHandling = JsonCommentHandling.Skip,
                AllowTrailingCommas = true
            });

        var fileName = Path.GetFileName(configPath);
        ValidateObjectProperties(document.RootElement, RootPropertyNames, fileName);
        foreach (var property in document.RootElement.EnumerateObject())
        {
            var path = $"{fileName}.{property.Name}";
            switch (property.Name.ToLowerInvariant())
            {
                case "backend":
                    ValidateObjectProperties(property.Value, BackendPropertyNames, path);
                    break;
                case "runtime":
                    ValidateObjectProperties(property.Value, RuntimePropertyNames, path);
                    break;
                case "invoke":
                    ValidateObjectProperties(property.Value, InvokePropertyNames, path);
                    break;
                case "trigger_sources":
                    ValidateTriggerSourceArray(property.Value, path);
                    break;
            }
        }
    }

    /// <summary>
    /// 校验对象节点的字段集合是否都在允许列表内。
    /// </summary>
    /// <param name="element">JSON 节点。</param>
    /// <param name="allowedPropertyNames">允许的字段名集合。</param>
    /// <param name="path">错误提示中的字段路径。</param>
    private static void ValidateObjectProperties(JsonElement element, ISet<string> allowedPropertyNames, string path)
    {
        if (element.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidOperationException($"{path} must be a JSON object.");
        }

        foreach (var property in element.EnumerateObject())
        {
            if (!allowedPropertyNames.Contains(property.Name))
            {
                throw new InvalidOperationException($"{path}.{property.Name} is not supported by this console app.");
            }
        }
    }

    /// <summary>
    /// 校验 TriggerSource 数组和每个 ZeroMQ 调用配置。
    /// </summary>
    /// <param name="element">trigger_sources JSON 节点。</param>
    /// <param name="path">错误提示中的字段路径。</param>
    private static void ValidateTriggerSourceArray(JsonElement element, string path)
    {
        if (element.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidOperationException($"{path} must be a JSON array.");
        }

        var index = 0;
        foreach (var item in element.EnumerateArray())
        {
            var itemPath = $"{path}[{index}]";
            ValidateObjectProperties(item, TriggerSourcePropertyNames, itemPath);
            var hasZeroMq = false;
            foreach (var property in item.EnumerateObject())
            {
                if (string.Equals(property.Name, "zero_mq", StringComparison.OrdinalIgnoreCase))
                {
                    hasZeroMq = true;
                    ValidateObjectProperties(property.Value, ZeroMqPropertyNames, $"{itemPath}.zero_mq");
                }
            }

            if (!hasZeroMq)
            {
                throw new InvalidOperationException($"{itemPath}.zero_mq is required.");
            }

            index++;
        }
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
