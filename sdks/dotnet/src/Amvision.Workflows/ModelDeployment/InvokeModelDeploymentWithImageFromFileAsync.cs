using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.ModelDeployment
{
/// <summary>
/// 使用磁盘图片执行模型同步推理。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 使用磁盘图片文件执行同步推理。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="imagePath">图片路径；相对路径会按 config_*.json 所在目录解析。</param>
    /// <param name="mediaType">可选 media type；为空时按扩展名推断。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>同步推理响应。</returns>
    public Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithImageFromFileAsync(
        string modelDeploymentName,
        string imagePath,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        return client.InferModelDeploymentUploadResponseAsync(
            modelDeployment.TaskType,
            RequireDeploymentInstanceId(configuredModelDeployment),
            BuildUploadRequestFromFile(configuredModelDeployment, imagePath, mediaType),
            cancellationToken);
    }
}
}
