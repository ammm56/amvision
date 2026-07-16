using System;
using Amvar.Vision;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision.ModelDeployment
{
/// <summary>
/// 使用配置默认输入执行模型同步推理。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 使用 config*.json 中的默认输入执行同步推理。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>同步推理响应。</returns>
    public async Task<ModelDeploymentInferenceResponse> InvokeConfiguredModelDeploymentAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        var deploymentInstanceId = RequireDeploymentInstanceId(configuredModelDeployment);

        async Task<ModelDeploymentInferenceResponse> InvokeJsonRequestAsync(ModelDeploymentInferenceRequest request)
        {
            var response = await client.InferModelDeploymentResponseAsync(
                modelDeployment.TaskType,
                deploymentInstanceId,
                request,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        async Task<ModelDeploymentInferenceResponse> InvokeUploadRequestAsync(ModelDeploymentInferenceUploadRequest uploadRequest)
        {
            var response = await client.InferModelDeploymentUploadResponseAsync(
                modelDeployment.TaskType,
                deploymentInstanceId,
                uploadRequest,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        var inferenceResponse = await BuildConfiguredInput(
            configuredModelDeployment,
            InvokeJsonRequestAsync,
            InvokeUploadRequestAsync).ConfigureAwait(false);
        return inferenceResponse;
    }
}
}
