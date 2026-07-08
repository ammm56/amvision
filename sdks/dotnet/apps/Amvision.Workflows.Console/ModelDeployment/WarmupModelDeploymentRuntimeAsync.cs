using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console.ModelDeployment;

/// <summary>
/// 模型 DeploymentInstance runtime 预热操作。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 预热已存在的模型 DeploymentInstance runtime。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 预热响应。</returns>
    public Task<ModelDeploymentRuntimeWarmupResponse> WarmupModelDeploymentRuntimeAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        return client.WarmupModelDeploymentRuntimeResponseAsync(
            modelDeployment.TaskType,
            RequireDeploymentInstanceId(configuredModelDeployment),
            modelDeployment.RuntimeMode,
            cancellationToken);
    }
}
