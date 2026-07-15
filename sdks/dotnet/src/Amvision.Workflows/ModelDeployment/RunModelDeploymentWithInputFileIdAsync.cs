using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.ModelDeployment
{
/// <summary>
/// 使用 input_file_id 创建模型异步推理任务。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 使用调用方传入的 input_file_id 创建异步推理任务。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="inputFileId">后端对象存储或文件表中的 input file id。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务提交响应。</returns>
    public Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithInputFileIdAsync(
        string modelDeploymentName,
        string inputFileId,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        return client.CreateModelInferenceTaskResponseAsync(
            modelDeployment.TaskType,
            BuildJsonRequestFromInputFileId(configuredModelDeployment, inputFileId),
            cancellationToken);
    }
}
}
