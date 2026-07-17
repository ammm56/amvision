using System;
using Amvar.Vision;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision.ModelDeployment
{
/// <summary>
/// 模型 DeploymentInstance runtime 启动操作。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 启动已存在的模型 DeploymentInstance runtime。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>启动后的模型运行时状态；非 2xx 响应抛出 AMVisionApiException。</returns>
    public async Task<ModelDeploymentRuntimeStatusResponse> StartModelDeploymentRuntimeAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        var deploymentInstanceId = RequireDeploymentInstanceId(configuredModelDeployment);
        var response = await client.StartModelDeploymentRuntimeResponseAsync(
            modelDeployment.TaskType,
            deploymentInstanceId,
            modelDeployment.RuntimeMode,
            cancellationToken).ConfigureAwait(false);
        return response;
    }
}
}
