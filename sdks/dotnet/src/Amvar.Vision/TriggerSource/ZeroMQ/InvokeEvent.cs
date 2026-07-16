using System;
using Amvar.Vision;
using System.Collections.Generic;
using System.Threading;

namespace Amvar.Vision.TriggerSource.ZeroMQ
{
/// <summary>
/// ZeroMQ 纯事件触发操作。
/// </summary>
internal sealed partial class ZeroMqTriggerOperations
{
    /// <summary>
    /// 发送只有 JSON envelope、没有图片第二帧的 ZeroMQ 触发请求。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="payload">可选事件 payload。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public TriggerResult InvokeEvent(
        string triggerSourceName,
        IDictionary<string, object?>? payload = null,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var request = BuildEventRequest(payload);
        ApplyEventDefaults(request, configuredTriggerSource);
        var client = GetClient(configuredTriggerSource);
        cancellationToken.ThrowIfCancellationRequested();
        var result = client.InvokeEvent(request);
        return result;
    }
}
}
