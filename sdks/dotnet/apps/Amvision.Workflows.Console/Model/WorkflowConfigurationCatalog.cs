using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;

namespace Amvision.Workflows.Console.Model;

/// <summary>
/// 控制台程序启动后常驻内存的配置目录索引。
/// </summary>
internal sealed class WorkflowConfigurationCatalog
{
    /// <summary>
    /// 创建按 runtime key 和 TriggerSource key 查询的只读配置索引。
    /// </summary>
    /// <param name="runtimes">runtime key 到配置的映射。</param>
    /// <param name="triggerSources">TriggerSource key 到配置的映射。</param>
    public WorkflowConfigurationCatalog(
        IDictionary<string, ConfiguredRuntime> runtimes,
        IDictionary<string, ConfiguredTriggerSource> triggerSources)
    {
        if (runtimes.Count == 0)
        {
            throw new InvalidOperationException("At least one runtime config is required.");
        }

        Runtimes = new ReadOnlyDictionary<string, ConfiguredRuntime>(
            new Dictionary<string, ConfiguredRuntime>(runtimes, StringComparer.OrdinalIgnoreCase));
        TriggerSources = new ReadOnlyDictionary<string, ConfiguredTriggerSource>(
            new Dictionary<string, ConfiguredTriggerSource>(triggerSources, StringComparer.OrdinalIgnoreCase));
        DefaultBackend = Runtimes.Values.First().Backend;
    }

    /// <summary>
    /// 按 runtime name 索引的 WorkflowAppRuntime 配置。
    /// </summary>
    public IReadOnlyDictionary<string, ConfiguredRuntime> Runtimes { get; }

    /// <summary>
    /// 按 TriggerSource name 索引的 TriggerSource 配置。
    /// </summary>
    public IReadOnlyDictionary<string, ConfiguredTriggerSource> TriggerSources { get; }

    /// <summary>
    /// 默认 backend 配置，用于初始化共享的 HTTP client。
    /// </summary>
    public BackendConfig DefaultBackend { get; }

    /// <summary>
    /// 通过 runtime key 获取配置；key 不存在时抛出明确错误。
    /// </summary>
    /// <param name="runtimeName">runtime 字典 key。</param>
    /// <returns>对应的 runtime 配置。</returns>
    public ConfiguredRuntime GetRuntime(string runtimeName)
    {
        var key = ConfigValidation.RequireText(runtimeName, nameof(runtimeName));
        if (!Runtimes.TryGetValue(key, out var runtime))
        {
            throw new KeyNotFoundException($"Runtime config key does not exist: {key}");
        }

        return runtime;
    }

    /// <summary>
    /// 通过 TriggerSource key 获取配置；key 不存在时抛出明确错误。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource 字典 key。</param>
    /// <returns>对应的 TriggerSource 配置。</returns>
    public ConfiguredTriggerSource GetTriggerSource(string triggerSourceName)
    {
        var key = ConfigValidation.RequireText(triggerSourceName, nameof(triggerSourceName));
        if (!TriggerSources.TryGetValue(key, out var triggerSource))
        {
            throw new KeyNotFoundException($"TriggerSource config key does not exist: {key}");
        }

        return triggerSource;
    }
}
