using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.TriggerSource.ZeroMQ;

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
    public async Task<TriggerResult> InvokeImageBytesAsync(
        string triggerSourceName,
        byte[] imageBytes,
        string mediaType = "image/octet-stream",
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var request = ImageTriggerRequest.FromBytes(imageBytes, mediaType);
        ApplyImageDefaults(request, configuredTriggerSource);
        using var client = CreateClient(configuredTriggerSource);
        var result = await client.InvokeImageAsync(request, cancellationToken).ConfigureAwait(false);
        Console.WriteLine($"ZeroMQ image bytes invoked: {triggerSourceName} | {result.State}");
        return result;
    }
}
