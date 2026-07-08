using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console;

/// <summary>
/// WorkflowOperationRunner 中面向模型 DeploymentInstance 的调用入口。
/// </summary>
public sealed partial class WorkflowOperationRunner
{
    /// <summary>
    /// 启动模型 DeploymentInstance runtime。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 状态响应。</returns>
    public Task<ModelDeploymentRuntimeStatusResponse> StartModelDeploymentRuntimeAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.StartModelDeploymentRuntimeAsync(modelDeploymentName, cancellationToken);
    }

    /// <summary>
    /// 停止模型 DeploymentInstance runtime。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 状态响应。</returns>
    public Task<ModelDeploymentRuntimeStatusResponse> StopModelDeploymentRuntimeAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.StopModelDeploymentRuntimeAsync(modelDeploymentName, cancellationToken);
    }

    /// <summary>
    /// 重置模型 DeploymentInstance runtime。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 状态响应。</returns>
    public Task<ModelDeploymentRuntimeStatusResponse> ResetModelDeploymentRuntimeAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.ResetModelDeploymentRuntimeAsync(modelDeploymentName, cancellationToken);
    }

    /// <summary>
    /// 预热模型 DeploymentInstance runtime。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 预热响应。</returns>
    public Task<ModelDeploymentRuntimeWarmupResponse> WarmupModelDeploymentRuntimeAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.WarmupModelDeploymentRuntimeAsync(modelDeploymentName, cancellationToken);
    }

    /// <summary>
    /// 读取模型 DeploymentInstance runtime 状态。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 状态响应。</returns>
    public Task<ModelDeploymentRuntimeStatusResponse> GetModelDeploymentRuntimeStatusAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.GetModelDeploymentRuntimeStatusAsync(modelDeploymentName, cancellationToken);
    }

    /// <summary>
    /// 读取模型 DeploymentInstance runtime health。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime health 响应。</returns>
    public Task<ModelDeploymentRuntimeHealthResponse> GetModelDeploymentRuntimeHealthAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.GetModelDeploymentRuntimeHealthAsync(modelDeploymentName, cancellationToken);
    }

    /// <summary>
    /// 使用配置中的默认输入执行模型同步推理。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>同步推理响应。</returns>
    public Task<ModelDeploymentInferenceResponse> InvokeConfiguredModelDeploymentAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.InvokeConfiguredModelDeploymentAsync(modelDeploymentName, cancellationToken);
    }

    /// <summary>
    /// 使用 base64 图片执行模型同步推理。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="imageBase64">图片 base64 或 data URL。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>同步推理响应。</returns>
    public Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithImageBase64Async(
        string modelDeploymentName,
        string imageBase64,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.InvokeModelDeploymentWithImageBase64Async(
            modelDeploymentName,
            imageBase64,
            cancellationToken);
    }

    /// <summary>
    /// 使用图片 bytes 执行模型同步推理。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="imageBytes">图片编码 bytes，通常来自工业相机 SDK 或内存缓存。</param>
    /// <param name="fileName">可选文件名；为空时使用 config_*.json 中的 default_file_name。</param>
    /// <param name="mediaType">可选 media type；为空时使用 config_*.json 中的 default_media_type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>同步推理响应。</returns>
    public Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithImageBytesAsync(
        string modelDeploymentName,
        byte[] imageBytes,
        string? fileName = null,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.InvokeModelDeploymentWithImageBytesAsync(
            modelDeploymentName,
            imageBytes,
            fileName,
            mediaType,
            cancellationToken);
    }

    /// <summary>
    /// 使用磁盘图片文件执行模型同步推理。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="imagePath">图片路径；相对路径会按 config_*.json 所在目录解析。</param>
    /// <param name="mediaType">可选 media type；为空时按扩展名推断。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>同步推理响应。</returns>
    public Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithImageFromFileAsync(
        string modelDeploymentName,
        string imagePath,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.InvokeModelDeploymentWithImageFromFileAsync(
            modelDeploymentName,
            imagePath,
            mediaType,
            cancellationToken);
    }

    /// <summary>
    /// 使用 input_uri 执行模型同步推理。
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
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.InvokeModelDeploymentWithInputUriAsync(
            modelDeploymentName,
            inputUri,
            cancellationToken);
    }

    /// <summary>
    /// 使用 input_file_id 执行模型同步推理。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="inputFileId">后端对象存储或文件表中的 input file id。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>同步推理响应。</returns>
    public Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithInputFileIdAsync(
        string modelDeploymentName,
        string inputFileId,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.InvokeModelDeploymentWithInputFileIdAsync(
            modelDeploymentName,
            inputFileId,
            cancellationToken);
    }

    /// <summary>
    /// 使用配置中的默认输入创建模型异步推理任务。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务提交响应。</returns>
    public Task<ModelInferenceTaskSubmissionResponse> RunConfiguredModelDeploymentAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.RunConfiguredModelDeploymentAsync(modelDeploymentName, cancellationToken);
    }

    /// <summary>
    /// 使用 base64 图片创建模型异步推理任务。
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
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.RunModelDeploymentWithImageBase64Async(
            modelDeploymentName,
            imageBase64,
            cancellationToken);
    }

    /// <summary>
    /// 使用图片 bytes 创建模型异步推理任务。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="imageBytes">图片编码 bytes，通常来自工业相机 SDK 或内存缓存。</param>
    /// <param name="fileName">可选文件名；为空时使用 config_*.json 中的 default_file_name。</param>
    /// <param name="mediaType">可选 media type；为空时使用 config_*.json 中的 default_media_type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务提交响应。</returns>
    public Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithImageBytesAsync(
        string modelDeploymentName,
        byte[] imageBytes,
        string? fileName = null,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.RunModelDeploymentWithImageBytesAsync(
            modelDeploymentName,
            imageBytes,
            fileName,
            mediaType,
            cancellationToken);
    }

    /// <summary>
    /// 使用磁盘图片文件创建模型异步推理任务。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="imagePath">图片路径；相对路径会按 config_*.json 所在目录解析。</param>
    /// <param name="mediaType">可选 media type；为空时按扩展名推断。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务提交响应。</returns>
    public Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithImageFromFileAsync(
        string modelDeploymentName,
        string imagePath,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.RunModelDeploymentWithImageFromFileAsync(
            modelDeploymentName,
            imagePath,
            mediaType,
            cancellationToken);
    }

    /// <summary>
    /// 使用 input_uri 创建模型异步推理任务。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="inputUri">后端可读取的图片 URI。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务提交响应。</returns>
    public Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithInputUriAsync(
        string modelDeploymentName,
        string inputUri,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.RunModelDeploymentWithInputUriAsync(
            modelDeploymentName,
            inputUri,
            cancellationToken);
    }

    /// <summary>
    /// 使用 input_file_id 创建模型异步推理任务。
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
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.RunModelDeploymentWithInputFileIdAsync(
            modelDeploymentName,
            inputFileId,
            cancellationToken);
    }

    /// <summary>
    /// 读取模型异步推理任务详情。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="inferenceTaskId">异步推理任务 id。</param>
    /// <param name="includeEvents">是否带回任务事件。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务详情。</returns>
    public Task<ModelInferenceTaskDetailResponse> GetModelInferenceTaskAsync(
        string modelDeploymentName,
        string inferenceTaskId,
        bool includeEvents = false,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.GetModelInferenceTaskAsync(
            modelDeploymentName,
            inferenceTaskId,
            includeEvents,
            cancellationToken);
    }

    /// <summary>
    /// 读取模型异步推理任务结果。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="inferenceTaskId">异步推理任务 id。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>异步推理任务结果。</returns>
    public Task<ModelInferenceTaskResultResponse> GetModelInferenceTaskResultAsync(
        string modelDeploymentName,
        string inferenceTaskId,
        CancellationToken cancellationToken = default)
    {
        RequireModelDeployment(modelDeploymentName);
        return modelDeploymentOperations.GetModelInferenceTaskResultAsync(
            modelDeploymentName,
            inferenceTaskId,
            cancellationToken);
    }
}
