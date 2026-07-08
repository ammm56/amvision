using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows;

public sealed partial class AmvisionWorkflowClient
{
    private const string ModelApiPrefix = "api/v1/models";

    /// <summary>
    /// 启动模型部署 runtime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> StartModelDeploymentRuntimeAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return SendModelDeploymentRuntimeCommandAsync(
            HttpMethod.Post,
            taskType,
            deploymentInstanceId,
            runtimeMode,
            "start",
            cancellationToken);
    }

    /// <summary>
    /// 启动模型部署 runtime，并返回 typed response。
    /// </summary>
    public async Task<ModelDeploymentRuntimeStatusResponse> StartModelDeploymentRuntimeResponseAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<ModelDeploymentRuntimeStatusResponse>(
            await StartModelDeploymentRuntimeAsync(taskType, deploymentInstanceId, runtimeMode, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 停止模型部署 runtime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> StopModelDeploymentRuntimeAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return SendModelDeploymentRuntimeCommandAsync(
            HttpMethod.Post,
            taskType,
            deploymentInstanceId,
            runtimeMode,
            "stop",
            cancellationToken);
    }

    /// <summary>
    /// 停止模型部署 runtime，并返回 typed response。
    /// </summary>
    public async Task<ModelDeploymentRuntimeStatusResponse> StopModelDeploymentRuntimeResponseAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<ModelDeploymentRuntimeStatusResponse>(
            await StopModelDeploymentRuntimeAsync(taskType, deploymentInstanceId, runtimeMode, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 重置模型部署 runtime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> ResetModelDeploymentRuntimeAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return SendModelDeploymentRuntimeCommandAsync(
            HttpMethod.Post,
            taskType,
            deploymentInstanceId,
            runtimeMode,
            "reset",
            cancellationToken);
    }

    /// <summary>
    /// 重置模型部署 runtime，并返回 typed response。
    /// </summary>
    public async Task<ModelDeploymentRuntimeStatusResponse> ResetModelDeploymentRuntimeResponseAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<ModelDeploymentRuntimeStatusResponse>(
            await ResetModelDeploymentRuntimeAsync(taskType, deploymentInstanceId, runtimeMode, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 预热模型部署 runtime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> WarmupModelDeploymentRuntimeAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return SendModelDeploymentRuntimeCommandAsync(
            HttpMethod.Post,
            taskType,
            deploymentInstanceId,
            runtimeMode,
            "warmup",
            cancellationToken);
    }

    /// <summary>
    /// 预热模型部署 runtime，并返回 typed response。
    /// </summary>
    public async Task<ModelDeploymentRuntimeWarmupResponse> WarmupModelDeploymentRuntimeResponseAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<ModelDeploymentRuntimeWarmupResponse>(
            await WarmupModelDeploymentRuntimeAsync(taskType, deploymentInstanceId, runtimeMode, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 读取模型部署 runtime 状态。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> GetModelDeploymentRuntimeStatusAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return SendModelDeploymentRuntimeCommandAsync(
            HttpMethod.Get,
            taskType,
            deploymentInstanceId,
            runtimeMode,
            "status",
            cancellationToken);
    }

    /// <summary>
    /// 读取模型部署 runtime 状态，并返回 typed response。
    /// </summary>
    public async Task<ModelDeploymentRuntimeStatusResponse> GetModelDeploymentRuntimeStatusResponseAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<ModelDeploymentRuntimeStatusResponse>(
            await GetModelDeploymentRuntimeStatusAsync(taskType, deploymentInstanceId, runtimeMode, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 读取模型部署 runtime health。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> GetModelDeploymentRuntimeHealthAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return SendModelDeploymentRuntimeCommandAsync(
            HttpMethod.Get,
            taskType,
            deploymentInstanceId,
            runtimeMode,
            "health",
            cancellationToken);
    }

    /// <summary>
    /// 读取模型部署 runtime health，并返回 typed response。
    /// </summary>
    public async Task<ModelDeploymentRuntimeHealthResponse> GetModelDeploymentRuntimeHealthResponseAsync(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<ModelDeploymentRuntimeHealthResponse>(
            await GetModelDeploymentRuntimeHealthAsync(taskType, deploymentInstanceId, runtimeMode, cancellationToken).ConfigureAwait(false));
    }

    private Task<AmvisionWorkflowApiResponse> SendModelDeploymentRuntimeCommandAsync(
        HttpMethod method,
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        string action,
        CancellationToken cancellationToken)
    {
        var path = BuildModelDeploymentRuntimePath(taskType, deploymentInstanceId, runtimeMode, action);
        return SendAsync(method, path, content: null, cancellationToken);
    }

    private static string BuildModelDeploymentRuntimePath(
        string taskType,
        string deploymentInstanceId,
        string runtimeMode,
        string action)
    {
        return $"{ModelApiPrefix}/{ModelTaskTypes.Normalize(taskType)}/deployment-instances/{EncodePathSegment(RequireId(deploymentInstanceId, nameof(deploymentInstanceId)))}/{ModelDeploymentRuntimeModes.Normalize(runtimeMode)}/{action}";
    }
}
