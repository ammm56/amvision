using System.Collections.Generic;
using System.IO;
using Amvision.Workflows.Net461Console.Model;

namespace Amvision.Workflows.Net461Console.TriggerSource.ZeroMQ;

/// <summary>
/// ZeroMQ TriggerSource 协议调用操作集合。
/// </summary>
internal sealed partial class ZeroMqTriggerOperations
{
    /// <summary>
    /// runtime 和 TriggerSource 配置索引。
    /// </summary>
    private readonly WorkflowConfigurationCatalog catalog;

    /// <summary>
    /// 初始化 ZeroMQ 触发操作对象。
    /// </summary>
    /// <param name="catalog">配置 catalog。</param>
    public ZeroMqTriggerOperations(WorkflowConfigurationCatalog catalog)
    {
        this.catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
    }

    /// <summary>
    /// 按 TriggerSource key 获取配置。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <returns>TriggerSource 配置。</returns>
    private ConfiguredTriggerSource GetConfiguredTriggerSource(string triggerSourceName)
    {
        return catalog.GetTriggerSource(triggerSourceName);
    }

    /// <summary>
    /// 根据 TriggerSource 配置构造 ZeroMQ SDK client。
    /// </summary>
    /// <param name="configuredTriggerSource">已展开的 TriggerSource 配置。</param>
    /// <returns>ZeroMQ TriggerSource client。</returns>
    private static AmvisionTriggerClient CreateClient(ConfiguredTriggerSource configuredTriggerSource)
    {
        return new AmvisionTriggerClient(new AmvisionTriggerClientOptions
        {
            Endpoint = configuredTriggerSource.TriggerSource.ZeroMq.BindEndpoint,
            TriggerSourceId = configuredTriggerSource.TriggerSource.TriggerSourceId,
            DefaultInputBinding = configuredTriggerSource.TriggerSource.ZeroMq.DefaultInputBinding,
            Timeout = TimeSpan.FromSeconds(configuredTriggerSource.TriggerSource.ZeroMq.TimeoutSeconds)
        });
    }

    /// <summary>
    /// 将配置文件中的相对路径解析为绝对路径。
    /// </summary>
    /// <param name="configuredTriggerSource">TriggerSource 配置。</param>
    /// <param name="configuredPath">配置中的路径。</param>
    /// <returns>绝对路径。</returns>
    private static string ResolveConfiguredPath(ConfiguredTriggerSource configuredTriggerSource, string configuredPath)
    {
        var normalizedPath = ConfigValidation.RequireText(configuredPath, nameof(configuredPath));
        return Path.IsPathRooted(normalizedPath)
            ? normalizedPath
            : Path.GetFullPath(Path.Combine(Path.GetDirectoryName(configuredTriggerSource.SourceFile) ?? ".", normalizedPath));
    }

    /// <summary>
    /// 为 ZeroMQ 图片请求补齐 input binding、runtime name 和 request_id。
    /// </summary>
    /// <param name="request">图片触发请求。</param>
    /// <param name="configuredTriggerSource">TriggerSource 配置。</param>
    private static void ApplyImageDefaults(ImageTriggerRequest request, ConfiguredTriggerSource configuredTriggerSource)
    {
        request.InputBinding = configuredTriggerSource.TriggerSource.ZeroMq.DefaultInputBinding;
        request.Metadata["trigger_source_name"] = configuredTriggerSource.TriggerSource.Name;
        request.Metadata["runtime_name"] = configuredTriggerSource.Runtime.Name;
        request.Payload["request_id"] = request.EventId ?? $"request-{Guid.NewGuid():N}";
    }

    /// <summary>
    /// 为 ZeroMQ 纯事件请求补齐 runtime name 和 request_id。
    /// </summary>
    /// <param name="request">纯事件触发请求。</param>
    /// <param name="configuredTriggerSource">TriggerSource 配置。</param>
    private static void ApplyEventDefaults(TriggerEventRequest request, ConfiguredTriggerSource configuredTriggerSource)
    {
        request.Metadata["trigger_source_name"] = configuredTriggerSource.TriggerSource.Name;
        request.Metadata["runtime_name"] = configuredTriggerSource.Runtime.Name;
        if (!request.Payload.ContainsKey("request_id"))
        {
            request.Payload["request_id"] = request.EventId ?? $"request-{Guid.NewGuid():N}";
        }
    }

    /// <summary>
    /// 根据可选 payload 创建 ZeroMQ 纯事件请求。
    /// </summary>
    /// <param name="payload">事件 payload；为空时创建空 payload 触发。</param>
    /// <returns>纯事件请求。</returns>
    private static TriggerEventRequest BuildEventRequest(IDictionary<string, object?>? payload)
    {
        return payload is null ? TriggerEventRequest.Empty() : TriggerEventRequest.FromPayload(payload);
    }
}
