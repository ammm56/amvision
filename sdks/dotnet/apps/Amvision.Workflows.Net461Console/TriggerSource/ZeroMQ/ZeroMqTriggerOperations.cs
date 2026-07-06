using System;
using System.Collections.Generic;
using System.IO;
using Amvision.Workflows.Net461Console.Model;
using Amvision.Workflows.Net461Console.Tools;

namespace Amvision.Workflows.Net461Console.TriggerSource.ZeroMQ;

/// <summary>
/// ZeroMQ TriggerSource 协议调用操作集合。
/// </summary>
internal sealed partial class ZeroMqTriggerOperations : IDisposable
{
    /// <summary>
    /// ZeroMQ client 缓存锁，避免并发创建同一个 TriggerSource client。
    /// </summary>
    private readonly object clientSyncRoot = new();

    /// <summary>
    /// runtime 和 TriggerSource 配置索引。
    /// </summary>
    private readonly WorkflowConfigurationCatalog catalog;

    /// <summary>
    /// 按 TriggerSource key 复用的 ZeroMQ SDK client。
    /// </summary>
    private readonly Dictionary<string, AmvisionTriggerClient> clients =
        new(StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// 标记当前操作对象是否已经释放。
    /// </summary>
    private bool disposed;

    /// <summary>
    /// 初始化 ZeroMQ 触发操作对象。
    /// </summary>
    /// <param name="catalog">配置 catalog。</param>
    public ZeroMqTriggerOperations(WorkflowConfigurationCatalog catalog)
    {
        this.catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
    }

    /// <summary>
    /// 释放所有复用的 ZeroMQ client 和底层 socket。
    /// </summary>
    public void Dispose()
    {
        lock (clientSyncRoot)
        {
            if (disposed)
            {
                return;
            }

            foreach (var client in clients.Values)
            {
                client.Dispose();
            }

            clients.Clear();
            disposed = true;
        }
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
    private AmvisionTriggerClient GetClient(ConfiguredTriggerSource configuredTriggerSource)
    {
        lock (clientSyncRoot)
        {
            if (disposed)
            {
                throw new ObjectDisposedException(nameof(ZeroMqTriggerOperations));
            }

            var key = configuredTriggerSource.TriggerSource.Name;
            if (!clients.TryGetValue(key, out var client))
            {
                client = new AmvisionTriggerClient(new AmvisionTriggerClientOptions
                {
                    Endpoint = configuredTriggerSource.TriggerSource.ZeroMq.BindEndpoint,
                    TriggerSourceId = configuredTriggerSource.TriggerSource.TriggerSourceId,
                    DefaultInputBinding = configuredTriggerSource.TriggerSource.ZeroMq.DefaultInputBinding,
                    Timeout = TimeSpan.FromSeconds(configuredTriggerSource.TriggerSource.ZeroMq.TimeoutSeconds)
                });
                clients[key] = client;
            }

            return client;
        }
    }

    /// <summary>
    /// 将配置文件中的相对路径解析为绝对路径。
    /// </summary>
    /// <param name="configuredTriggerSource">TriggerSource 配置。</param>
    /// <param name="configuredPath">配置中的路径。</param>
    /// <returns>绝对路径。</returns>
    private static string ResolveConfiguredPath(ConfiguredTriggerSource configuredTriggerSource, string configuredPath)
    {
        return ConfiguredPathResolver.ResolveExistingFile(
            configuredPath,
            configuredTriggerSource.SourceFile,
            "ZeroMQ image file does not exist.");
    }

    /// <summary>
    /// 校验图片 bytes 大小，避免误传超大文件导致内存压力。
    /// </summary>
    /// <param name="imageByteCount">图片 bytes 数量。</param>
    /// <param name="configuredTriggerSource">TriggerSource 配置。</param>
    /// <param name="sourceName">输入来源名称。</param>
    private static void EnsureImageByteCount(
        long imageByteCount,
        ConfiguredTriggerSource configuredTriggerSource,
        string sourceName)
    {
        if (imageByteCount <= 0)
        {
            throw new InvalidOperationException($"{sourceName} image bytes cannot be empty.");
        }

        var maxImageBytes = configuredTriggerSource.TriggerSource.ZeroMq.MaxImageBytes;
        if (imageByteCount > maxImageBytes)
        {
            throw new InvalidOperationException(
                $"{sourceName} image bytes {imageByteCount} exceeds zero_mq.max_image_bytes {maxImageBytes}.");
        }
    }

    /// <summary>
    /// 估算 base64 解码后的 bytes 大小，用于在真正解码前做输入大小防呆。
    /// </summary>
    /// <param name="imageBase64">图片 base64 或 data URL。</param>
    /// <returns>估算后的解码 bytes 数量。</returns>
    private static long EstimateBase64DecodedByteCount(string imageBase64)
    {
        var normalizedBase64 = ConfigValidation.RequireText(imageBase64, nameof(imageBase64));
        var commaIndex = normalizedBase64.IndexOf(',');
        if (normalizedBase64.StartsWith("data:", StringComparison.OrdinalIgnoreCase) && commaIndex > 0)
        {
            normalizedBase64 = normalizedBase64.Substring(commaIndex + 1);
        }

        long base64CharCount = 0;
        var paddingCount = 0;
        foreach (var character in normalizedBase64)
        {
            if (char.IsWhiteSpace(character))
            {
                continue;
            }

            base64CharCount++;
            if (character == '=')
            {
                paddingCount++;
            }
        }

        if (base64CharCount == 0)
        {
            return 0;
        }

        return ((base64CharCount + 3) / 4 * 3) - Math.Min(paddingCount, 2);
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
