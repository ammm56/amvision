using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.ModelDeployment
{
/// <summary>
/// 使用图片 bytes 创建模型异步推理任务。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 使用调用方传入的图片 bytes 创建异步推理任务。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="imageBytes">图片编码 bytes，通常来自工业相机 SDK 或内存缓存。</param>
    /// <param name="fileName">可选文件名；为空时使用 config*.json 中的 default_file_name。</param>
    /// <param name="mediaType">可选 media type；为空时使用 config*.json 中的 default_media_type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务提交响应。</returns>
    public async Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithImageBytesAsync(
        string modelDeploymentName,
        byte[] imageBytes,
        string? fileName = null,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        var request = BuildUploadRequestFromBytes(configuredModelDeployment, imageBytes, fileName, mediaType);
        var response = await client.CreateModelInferenceTaskUploadResponseAsync(
            modelDeployment.TaskType,
            request,
            cancellationToken).ConfigureAwait(false);
        return response;
    }
}
}
