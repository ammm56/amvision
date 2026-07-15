using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.ModelDeployment
{
/// <summary>
/// 模型异步推理任务详情读取操作。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 和 inference_task_id 读取异步推理任务详情。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="inferenceTaskId">异步推理任务 id。</param>
    /// <param name="includeEvents">是否带回任务事件。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务详情。</returns>
    public async Task<ModelInferenceTaskDetailResponse> GetModelInferenceTaskAsync(
        string modelDeploymentName,
        string inferenceTaskId,
        bool includeEvents = false,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var taskType = configuredModelDeployment.ModelDeployment.TaskType;
        var response = await client.GetModelInferenceTaskResponseAsync(
            taskType,
            inferenceTaskId,
            includeEvents,
            cancellationToken).ConfigureAwait(false);
        return response;
    }
}
}
