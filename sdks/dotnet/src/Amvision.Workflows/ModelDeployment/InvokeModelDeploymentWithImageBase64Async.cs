using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.ModelDeployment
{
/// <summary>
/// 使用 base64 图片执行模型同步推理。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 使用调用方传入的 base64 图片执行同步推理。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="imageBase64">图片 base64 或 data URL。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>同步推理响应。</returns>
    public async Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithImageBase64Async(
        string modelDeploymentName,
        string imageBase64,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        var deploymentInstanceId = RequireDeploymentInstanceId(configuredModelDeployment);
        var request = BuildJsonRequestFromBase64(configuredModelDeployment, imageBase64);
        var response = await client.InferModelDeploymentResponseAsync(
            modelDeployment.TaskType,
            deploymentInstanceId,
            request,
            cancellationToken).ConfigureAwait(false);
        return response;
    }
}
}
