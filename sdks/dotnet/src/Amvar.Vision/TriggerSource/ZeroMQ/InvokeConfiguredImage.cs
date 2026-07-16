using System;
using Amvar.Vision;
using System.Threading;
using Amvar.Vision.Configuration;

namespace Amvar.Vision.TriggerSource.ZeroMQ
{
/// <summary>
/// 使用配置中的图片路径执行 ZeroMQ 图片触发。
/// </summary>
internal sealed partial class ZeroMqTriggerOperations
{
    /// <summary>
    /// 从关联 runtime 的 invoke.image_path 读取图片，并通过 ZeroMQ multipart 第二帧发送图片 bytes。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public TriggerResult InvokeConfiguredImage(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var imagePath = ConfigValidation.NormalizeOptional(catalog.GetRuntime(configuredTriggerSource.Runtime.Name).Invoke.ImagePath);
        if (imagePath == null)
        {
            throw new InvalidOperationException($"TriggerSource {triggerSourceName} does not have a configured runtime invoke.image_path.");
        }

        var result = InvokeImageFromFile(
            triggerSourceName,
            imagePath,
            mediaType: null,
            cancellationToken);
        return result;
    }
}
}
