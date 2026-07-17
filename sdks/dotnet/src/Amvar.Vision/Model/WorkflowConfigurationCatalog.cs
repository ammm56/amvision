using Amvar.Vision;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;

namespace Amvar.Vision.Configuration
{
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
    /// <param name="modelDeployments">模型 deployment key 到配置的映射。</param>
    public WorkflowConfigurationCatalog(
        IDictionary<string, ConfiguredRuntime> runtimes,
        IDictionary<string, ConfiguredTriggerSource> triggerSources,
        IDictionary<string, ConfiguredModelDeployment> modelDeployments)
    {
        if (runtimes.Count == 0 && modelDeployments.Count == 0)
        {
            throw new InvalidOperationException("At least one runtime or model deployment config is required.");
        }

        Runtimes = new ReadOnlyDictionary<string, ConfiguredRuntime>(
            new Dictionary<string, ConfiguredRuntime>(runtimes, StringComparer.OrdinalIgnoreCase));
        TriggerSources = new ReadOnlyDictionary<string, ConfiguredTriggerSource>(
            new Dictionary<string, ConfiguredTriggerSource>(triggerSources, StringComparer.OrdinalIgnoreCase));
        ModelDeployments = new ReadOnlyDictionary<string, ConfiguredModelDeployment>(
            new Dictionary<string, ConfiguredModelDeployment>(modelDeployments, StringComparer.OrdinalIgnoreCase));
        DefaultBackend = Runtimes.Count > 0
            ? Runtimes.Values.First().Backend
            : ModelDeployments.Values.First().Backend;
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
    /// 按模型 deployment name 索引的 DeploymentInstance 调用配置。
    /// </summary>
    public IReadOnlyDictionary<string, ConfiguredModelDeployment> ModelDeployments { get; }

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
            throw new KeyNotFoundException($"Runtime config key does not exist: {key}. Available keys: {FormatKnownKeys(Runtimes.Keys)}");
        }

        return runtime;
    }

    /// <summary>
    /// 通过 workflow_runtime_id 精确获取配置，不把 id 当作 name 猜测。
    /// </summary>
    public ConfiguredRuntime GetRuntimeById(string workflowRuntimeId)
    {
        var id = ConfigValidation.RequireText(workflowRuntimeId, nameof(workflowRuntimeId));
        var matches = Runtimes.Values
            .Where(item => string.Equals(item.Runtime.WorkflowRuntimeId, id, StringComparison.Ordinal))
            .ToArray();
        if (matches.Length != 1)
        {
            throw new KeyNotFoundException($"Workflow runtime id does not exist or is not unique: {id}.");
        }

        return matches[0];
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
            throw new KeyNotFoundException($"TriggerSource config key does not exist: {key}. Available keys: {FormatKnownKeys(TriggerSources.Keys)}");
        }

        return triggerSource;
    }

    /// <summary>
    /// 通过 trigger_source_id 精确获取配置，不把 id 当作 name 猜测。
    /// </summary>
    public ConfiguredTriggerSource GetTriggerSourceById(string triggerSourceId)
    {
        var id = ConfigValidation.RequireText(triggerSourceId, nameof(triggerSourceId));
        var matches = TriggerSources.Values
            .Where(item => string.Equals(item.TriggerSource.TriggerSourceId, id, StringComparison.Ordinal))
            .ToArray();
        if (matches.Length != 1)
        {
            throw new KeyNotFoundException($"TriggerSource id does not exist or is not unique: {id}.");
        }

        return matches[0];
    }

    /// <summary>
    /// 通过模型 deployment key 获取配置；key 不存在时抛出明确错误。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 字典 key。</param>
    /// <returns>对应的模型 deployment 配置。</returns>
    public ConfiguredModelDeployment GetModelDeployment(string modelDeploymentName)
    {
        var key = ConfigValidation.RequireText(modelDeploymentName, nameof(modelDeploymentName));
        if (!ModelDeployments.TryGetValue(key, out var modelDeployment))
        {
            throw new KeyNotFoundException($"Model deployment config key does not exist: {key}. Available keys: {FormatKnownKeys(ModelDeployments.Keys)}");
        }

        return modelDeployment;
    }

    /// <summary>
    /// 通过 deployment_instance_id 精确获取配置，不把 id 当作 name 猜测。
    /// </summary>
    public ConfiguredModelDeployment GetModelDeploymentById(
        string deploymentInstanceId,
        string runtimeMode)
    {
        var id = ConfigValidation.RequireText(deploymentInstanceId, nameof(deploymentInstanceId));
        var mode = ModelDeploymentRuntimeModes.Normalize(
            ConfigValidation.RequireText(runtimeMode, nameof(runtimeMode)));
        var matches = ModelDeployments.Values
            .Where(item =>
                string.Equals(item.ModelDeployment.DeploymentInstanceId, id, StringComparison.Ordinal)
                && string.Equals(item.ModelDeployment.RuntimeMode, mode, StringComparison.Ordinal))
            .ToArray();
        if (matches.Length != 1)
        {
            throw new KeyNotFoundException(
                $"Model deployment id/runtime mode does not exist or is not unique: {id} / {mode}.");
        }

        return matches[0];
    }

    /// <summary>
    /// 把已加载的配置 key 拼成错误提示，方便现场直接按提示修改 Program 中的常量。
    /// </summary>
    /// <param name="keys">已加载的配置 key 集合。</param>
    /// <returns>用于异常信息的 key 列表。</returns>
    private static string FormatKnownKeys(IEnumerable<string> keys)
    {
        var knownKeys = keys.OrderBy(key => key, StringComparer.OrdinalIgnoreCase).ToArray();
        return knownKeys.Length == 0 ? "<none>" : string.Join(", ", knownKeys);
    }
}
}
