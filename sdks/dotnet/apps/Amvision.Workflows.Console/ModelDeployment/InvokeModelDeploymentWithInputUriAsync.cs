using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console.ModelDeployment
{
/// <summary>
/// 使用 input_uri 执行模型同步推理。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 使用调用方传入的 input_uri 执行同步推理。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="inputUri">后端可读取的图片 URI。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>同步推理响应。</returns>
    public Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithInputUriAsync(
        string modelDeploymentName,
        string inputUri,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        return client.InferModelDeploymentResponseAsync(
            modelDeployment.TaskType,
            RequireDeploymentInstanceId(configuredModelDeployment),
            BuildJsonRequestFromInputUri(configuredModelDeployment, inputUri),
            cancellationToken);
    }
}
}
