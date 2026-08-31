using System;
using Amvar.Vision;
using System.IO;
using System.Threading;

namespace Amvar.Vision.TriggerSource.ZeroMQ
{
/// <summary>
/// ZeroMQ 图片文件触发操作。
/// </summary>
internal sealed partial class ZeroMqTriggerOperations
{
    /// <summary>
    /// 从磁盘读取图片文件，并把文件 bytes 作为 ZeroMQ multipart 第二帧发送。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="imagePath">图片路径，可为相对配置文件目录的路径。</param>
    /// <param name="mediaType">可选 media type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public TriggerResult InvokeImageFromFile(
        string triggerSourceName,
        string imagePath,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        return InvokeImageFromFile(
            triggerSourceName,
            imagePath,
            mediaType,
            inputs: null,
            cancellationToken);
    }

    /// <summary>发送图片文件，并在同一 envelope 附带规范 JSON/文本输入。</summary>
    public TriggerResult InvokeImageFromFile(
        string triggerSourceName,
        string imagePath,
        string? mediaType,
        WorkflowTriggerInputs? inputs,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var resolvedImagePath = ResolveConfiguredPath(configuredTriggerSource, imagePath);
        var fileInfo = new FileInfo(resolvedImagePath);
        EnsureImageByteCount(fileInfo.Length, configuredTriggerSource, nameof(imagePath));
        var request = ImageTriggerRequest.FromFile(resolvedImagePath, mediaType);
        ApplyImageDefaults(request, configuredTriggerSource);
        ApplyTriggerInputs(inputs, request.Payload);
        var client = GetClient(configuredTriggerSource);
        cancellationToken.ThrowIfCancellationRequested();
        var result = client.InvokeImage(request);
        return result;
    }
}
}
