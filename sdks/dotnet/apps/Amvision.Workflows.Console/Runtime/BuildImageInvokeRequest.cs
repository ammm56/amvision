using System;
using Amvision.Workflows;
using System.IO;
using Amvision.Workflows.Console.Model;

namespace Amvision.Workflows.Console.Runtime
{
/// <summary>
/// 构建 HTTP image-base64 runtime invoke 请求。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 从配置的图片路径读取 bytes，并构建 image-base64.v1 输入。
    /// </summary>
    /// <param name="configuredRuntime">runtime 配置。</param>
    /// <param name="scenario">写入 execution_metadata 的场景名。</param>
    /// <returns>图片 invoke 请求。</returns>
    private static WorkflowRuntimeImageInvokeRequest BuildImageInvokeRequest(
        ConfiguredRuntime configuredRuntime,
        string scenario)
    {
        var imagePath = ConfigValidation.NormalizeOptional(configuredRuntime.Invoke.ImagePath)
            ?? throw new InvalidOperationException($"Runtime {configuredRuntime.Runtime.Name} invoke.image_path is required.");
        var resolvedImagePath = ResolveConfiguredPath(configuredRuntime, imagePath);

        return BuildImageInvokeRequestFromFile(configuredRuntime, resolvedImagePath, InferImageMediaType(resolvedImagePath), scenario);
    }

    /// <summary>
    /// 从调用方传入的 base64 或 data URL 构建 image-base64.v1 输入。
    /// </summary>
    /// <param name="configuredRuntime">runtime 配置。</param>
    /// <param name="imageBase64">图片 base64 或 data URL。</param>
    /// <param name="mediaType">可选 media type；data URL 会优先使用自身声明。</param>
    /// <param name="scenario">写入 execution_metadata 的场景名。</param>
    /// <returns>图片 invoke 请求。</returns>
    private static WorkflowRuntimeImageInvokeRequest BuildImageInvokeRequestFromBase64(
        ConfiguredRuntime configuredRuntime,
        string imageBase64,
        string? mediaType,
        string scenario)
    {
        return ApplyImageInvokeDefaults(
            WorkflowRuntimeImageInvokeRequest.FromBase64(
                imageBase64,
                mediaType,
                configuredRuntime.Invoke.ImageInputBinding),
            configuredRuntime,
            scenario);
    }

    /// <summary>
    /// 从调用方传入的图片 bytes 构建 image-base64.v1 输入。
    /// </summary>
    /// <param name="configuredRuntime">runtime 配置。</param>
    /// <param name="imageBytes">图片编码 bytes。</param>
    /// <param name="mediaType">media type。</param>
    /// <param name="scenario">写入 execution_metadata 的场景名。</param>
    /// <returns>图片 invoke 请求。</returns>
    private static WorkflowRuntimeImageInvokeRequest BuildImageInvokeRequestFromBytes(
        ConfiguredRuntime configuredRuntime,
        byte[] imageBytes,
        string mediaType,
        string scenario)
    {
        return ApplyImageInvokeDefaults(
            WorkflowRuntimeImageInvokeRequest.FromBytes(
                imageBytes,
                mediaType,
                configuredRuntime.Invoke.ImageInputBinding),
            configuredRuntime,
            scenario);
    }

    /// <summary>
    /// 从调用方传入的图片文件路径构建 image-base64.v1 输入。
    /// </summary>
    /// <param name="configuredRuntime">runtime 配置。</param>
    /// <param name="imagePath">图片文件路径。</param>
    /// <param name="mediaType">可选 media type；为空时按扩展名推断。</param>
    /// <param name="scenario">写入 execution_metadata 的场景名。</param>
    /// <returns>图片 invoke 请求。</returns>
    private static WorkflowRuntimeImageInvokeRequest BuildImageInvokeRequestFromFile(
        ConfiguredRuntime configuredRuntime,
        string imagePath,
        string? mediaType,
        string scenario)
    {
        var resolvedImagePath = ResolveConfiguredPath(configuredRuntime, imagePath);
        return ApplyImageInvokeDefaults(
            WorkflowRuntimeImageInvokeRequest.FromFile(
                resolvedImagePath,
                mediaType,
                configuredRuntime.Invoke.ImageInputBinding),
            configuredRuntime,
            scenario);
    }

    /// <summary>
    /// 写入 runtime 调用公共参数，保持 config 中 timeout、binding 和 metadata 语义一致。
    /// </summary>
    /// <param name="request">待补充默认值的图片请求。</param>
    /// <param name="configuredRuntime">runtime 配置。</param>
    /// <param name="scenario">写入 execution_metadata 的场景名。</param>
    /// <returns>已补全默认值的图片请求。</returns>
    private static WorkflowRuntimeImageInvokeRequest ApplyImageInvokeDefaults(
        WorkflowRuntimeImageInvokeRequest request,
        ConfiguredRuntime configuredRuntime,
        string scenario)
    {
        request.TimeoutSeconds = configuredRuntime.Invoke.TimeoutSeconds;
        request.UseDirectInputBindings = configuredRuntime.Invoke.UseDirectInputBindings;
        request.ExecutionMetadata["source"] = configuredRuntime.Invoke.Source;
        request.ExecutionMetadata["scenario"] = scenario;
        request.ExecutionMetadata["runtime_name"] = configuredRuntime.Runtime.Name;
        request.ExecutionMetadata["request_id"] = $"request-{System.Guid.NewGuid():N}";
        return request;
    }
}
}
