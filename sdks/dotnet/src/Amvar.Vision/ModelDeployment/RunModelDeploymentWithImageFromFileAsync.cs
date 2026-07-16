using System;
using Amvar.Vision;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision.ModelDeployment
{
/// <summary>
/// 使用磁盘图片创建模型异步推理任务。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 使用磁盘图片文件创建异步推理任务。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="imagePath">图片路径；相对路径会按 config*.json 所在目录解析。</param>
    /// <param name="mediaType">可选 media type；为空时按扩展名推断。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务提交响应。</returns>
    public async Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithImageFromFileAsync(
        string modelDeploymentName,
        string imagePath,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        var request = BuildUploadRequestFromFile(configuredModelDeployment, imagePath, mediaType);
        var response = await client.CreateModelInferenceTaskUploadResponseAsync(
            modelDeployment.TaskType,
            request,
            cancellationToken).ConfigureAwait(false);
        return response;
    }
}
}
