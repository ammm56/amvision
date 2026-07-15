using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.ModelDeployment
{
/// <summary>
/// 使用配置默认输入执行模型同步推理。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 使用 config_*.json 中的默认输入执行同步推理。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>同步推理响应。</returns>
    public Task<ModelDeploymentInferenceResponse> InvokeConfiguredModelDeploymentAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        var deploymentInstanceId = RequireDeploymentInstanceId(configuredModelDeployment);
        return BuildConfiguredInput(
            configuredModelDeployment,
            request => client.InferModelDeploymentResponseAsync(
                modelDeployment.TaskType,
                deploymentInstanceId,
                request,
                cancellationToken),
            uploadRequest => client.InferModelDeploymentUploadResponseAsync(
                modelDeployment.TaskType,
                deploymentInstanceId,
                uploadRequest,
                cancellationToken));
    }
}
}
