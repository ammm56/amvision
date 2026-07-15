using System;
using Amvision.Workflows;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.TriggerSource.ZeroMQ
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
    public async Task<TriggerResult> InvokeImageFromFileAsync(
        string triggerSourceName,
        string imagePath,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var resolvedImagePath = ResolveConfiguredPath(configuredTriggerSource, imagePath);
        var fileInfo = new FileInfo(resolvedImagePath);
        EnsureImageByteCount(fileInfo.Length, configuredTriggerSource, nameof(imagePath));
        var request = ImageTriggerRequest.FromFile(resolvedImagePath, mediaType);
        ApplyImageDefaults(request, configuredTriggerSource);
        var client = GetClient(configuredTriggerSource);
        var result = await client.InvokeImageAsync(request, cancellationToken).ConfigureAwait(false);
        return result;
    }
}
}
