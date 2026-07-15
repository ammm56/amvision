using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.ModelDeployment
{
/// <summary>
/// 模型异步推理任务结果读取操作。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 和 inference_task_id 读取异步推理任务结果。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="inferenceTaskId">异步推理任务 id。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务结果。</returns>
    public async Task<ModelInferenceTaskResultResponse> GetModelInferenceTaskResultAsync(
        string modelDeploymentName,
        string inferenceTaskId,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var taskType = configuredModelDeployment.ModelDeployment.TaskType;
        var response = await client.GetModelInferenceTaskResultResponseAsync(
            taskType,
            inferenceTaskId,
            cancellationToken).ConfigureAwait(false);
        return response;
    }
}
}
