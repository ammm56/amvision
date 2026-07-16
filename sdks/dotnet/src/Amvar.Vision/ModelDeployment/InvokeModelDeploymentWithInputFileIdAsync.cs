using System;
using Amvar.Vision;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision.ModelDeployment
{
/// <summary>
/// 使用 input_file_id 执行模型同步推理。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 使用调用方传入的 input_file_id 执行同步推理。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="inputFileId">后端对象存储或文件表中的 input file id。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>同步推理响应。</returns>
    public async Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithInputFileIdAsync(
        string modelDeploymentName,
        string inputFileId,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        var deploymentInstanceId = RequireDeploymentInstanceId(configuredModelDeployment);
        var request = BuildJsonRequestFromInputFileId(configuredModelDeployment, inputFileId);
        var response = await client.InferModelDeploymentResponseAsync(
            modelDeployment.TaskType,
            deploymentInstanceId,
            request,
            cancellationToken).ConfigureAwait(false);
        return response;
    }
}
}
