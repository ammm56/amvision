using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.TriggerSource.ZeroMQ;

/// <summary>
/// ZeroMQ base64 图片触发操作。
/// </summary>
internal sealed partial class ZeroMqTriggerOperations
{
    /// <summary>
    /// 将 base64 图片解码为 bytes，再通过 ZeroMQ multipart 第二帧发送，避免把大图继续作为 JSON 字段传输。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="imageBase64">图片 base64 或 data URL。</param>
    /// <param name="mediaType">可选 media type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public async Task<TriggerResult> InvokeImageBase64Async(
        string triggerSourceName,
        string imageBase64,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        EnsureImageByteCount(EstimateBase64DecodedByteCount(imageBase64), configuredTriggerSource, nameof(imageBase64));
        var request = ImageTriggerRequest.FromBase64(imageBase64, mediaType);
        EnsureImageByteCount(request.ImageBytes.LongLength, configuredTriggerSource, nameof(imageBase64));
        ApplyImageDefaults(request, configuredTriggerSource);
        using var client = CreateClient(configuredTriggerSource);
        var result = await client.InvokeImageAsync(request, cancellationToken).ConfigureAwait(false);
        return result;
    }
}
