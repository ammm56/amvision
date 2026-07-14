using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console.ModelDeployment
{
/// <summary>
/// 使用配置默认输入创建模型异步推理任务。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 使用 config_*.json 中的默认输入创建异步推理任务。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务提交响应。</returns>
    public Task<ModelInferenceTaskSubmissionResponse> RunConfiguredModelDeploymentAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        return BuildConfiguredInput(
            configuredModelDeployment,
            request => client.CreateModelInferenceTaskResponseAsync(
                modelDeployment.TaskType,
                request,
                cancellationToken),
            uploadRequest => client.CreateModelInferenceTaskUploadResponseAsync(
                modelDeployment.TaskType,
                uploadRequest,
                cancellationToken));
    }
}
}
