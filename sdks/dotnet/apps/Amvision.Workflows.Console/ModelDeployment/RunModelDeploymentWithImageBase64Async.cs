using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console.ModelDeployment;

/// <summary>
/// 使用 base64 图片创建模型异步推理任务。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 使用调用方传入的 base64 图片创建异步推理任务。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="imageBase64">图片 base64 或 data URL。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务提交响应。</returns>
    public Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithImageBase64Async(
        string modelDeploymentName,
        string imageBase64,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        return client.CreateModelInferenceTaskResponseAsync(
            modelDeployment.TaskType,
            BuildJsonRequestFromBase64(configuredModelDeployment, imageBase64),
            cancellationToken);
    }
}
