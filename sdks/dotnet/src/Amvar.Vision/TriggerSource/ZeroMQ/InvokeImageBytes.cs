using Amvar.Vision;
using System;
using System.Threading;

namespace Amvar.Vision.TriggerSource.ZeroMQ
{
/// <summary>
/// ZeroMQ 图片 bytes 触发操作。
/// </summary>
internal sealed partial class ZeroMqTriggerOperations
{
    /// <summary>
    /// 直接把图片 bytes 作为 ZeroMQ multipart 第二帧发送。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="imageBytes">图片编码 bytes。</param>
    /// <param name="mediaType">media type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public TriggerResult InvokeImageBytes(
        string triggerSourceName,
        byte[] imageBytes,
        string mediaType = "image/octet-stream",
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        if (imageBytes == null)
        {
            throw new ArgumentNullException(nameof(imageBytes));
        }

        EnsureImageByteCount(imageBytes.LongLength, configuredTriggerSource, nameof(imageBytes));
        var request = ImageTriggerRequest.FromBytes(imageBytes, mediaType);
        ApplyImageDefaults(request, configuredTriggerSource);
        var client = GetClient(configuredTriggerSource);
        cancellationToken.ThrowIfCancellationRequested();
        var result = client.InvokeImage(request);
        return result;
    }
}
}
