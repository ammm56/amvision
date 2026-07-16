using System;
using Amvar.Vision;
using System.Drawing;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision.Configuration;
using Amvar.Vision.Tools;

namespace Amvar.Vision.TriggerSource.ZeroMQ
{
/// <summary>
/// ZeroMQ BGR24 raw 图片触发操作。
/// </summary>
internal sealed partial class ZeroMqTriggerOperations
{
    /// <summary>
    /// 直接把连续 HWC BGR24 像素 bytes 作为 ZeroMQ multipart 第二帧发送。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="bgr24Bytes">连续 B/G/R 像素 bytes。</param>
    /// <param name="width">图片宽度。</param>
    /// <param name="height">图片高度。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public async Task<TriggerResult> InvokeBgr24Async(
        string triggerSourceName,
        byte[] bgr24Bytes,
        int width,
        int height,
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        ImageConversionTools.ValidateBgr24Bytes(bgr24Bytes, width, height, nameof(bgr24Bytes));
        EnsureImageByteCount(bgr24Bytes.LongLength, configuredTriggerSource, nameof(bgr24Bytes));
        var request = ImageTriggerRequest.FromBgr24(bgr24Bytes, width, height);
        ApplyImageDefaults(request, configuredTriggerSource);
        var client = GetClient(configuredTriggerSource);
        var triggerResult = await client.InvokeImageAsync(request, cancellationToken).ConfigureAwait(false);
        return triggerResult;
    }

    /// <summary>
    /// 把 Windows 原生 Bitmap 转换为 BGR24 后通过 ZeroMQ 触发。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="bitmap">System.Drawing.Bitmap 对象。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public async Task<TriggerResult> InvokeBgr24FromBitmapAsync(
        string triggerSourceName,
        Bitmap bitmap,
        CancellationToken cancellationToken = default)
    {
        var frame = ImageConversionTools.BitmapToBgr24(bitmap);
        var triggerResult = await InvokeBgr24Async(
            triggerSourceName,
            frame.Bytes,
            frame.Width,
            frame.Height,
            cancellationToken).ConfigureAwait(false);
        return triggerResult;
    }

    /// <summary>
    /// 从磁盘图片文件转换为 BGR24 后通过 ZeroMQ 触发。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="imagePath">图片路径，可为相对配置文件目录的路径。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public async Task<TriggerResult> InvokeBgr24FromFileAsync(
        string triggerSourceName,
        string imagePath,
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var resolvedImagePath = ResolveConfiguredPath(configuredTriggerSource, imagePath);
        var frame = ImageConversionTools.ImageFileToBgr24(resolvedImagePath);
        var triggerResult = await InvokeBgr24Async(
            triggerSourceName,
            frame.Bytes,
            frame.Width,
            frame.Height,
            cancellationToken).ConfigureAwait(false);
        return triggerResult;
    }

    /// <summary>
    /// 从关联 runtime 的 invoke.image_path 转换 BGR24 后通过 ZeroMQ 触发。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public async Task<TriggerResult> InvokeConfiguredBgr24ImageAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var imagePath = ConfigValidation.NormalizeOptional(catalog.GetRuntime(configuredTriggerSource.Runtime.Name).Invoke.ImagePath);
        if (imagePath == null)
        {
            throw new InvalidOperationException($"TriggerSource {triggerSourceName} does not have a configured runtime invoke.image_path.");
        }

        var triggerResult = await InvokeBgr24FromFileAsync(
            triggerSourceName,
            imagePath,
            cancellationToken).ConfigureAwait(false);
        return triggerResult;
    }
}
}
