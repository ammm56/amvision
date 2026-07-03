using System;
using System.IO;
using Amvision.Workflows.Net461Console.Model;

namespace Amvision.Workflows.Net461Console.Runtime;

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
        if (!File.Exists(resolvedImagePath))
        {
            throw new FileNotFoundException("Input image file does not exist.", resolvedImagePath);
        }

        var request = new WorkflowRuntimeImageInvokeRequest
        {
            ImageBytes = File.ReadAllBytes(resolvedImagePath),
            InputBinding = configuredRuntime.Invoke.ImageInputBinding,
            MediaType = InferImageMediaType(resolvedImagePath),
            TimeoutSeconds = configuredRuntime.Invoke.TimeoutSeconds,
            UseDirectInputBindings = configuredRuntime.Invoke.UseDirectInputBindings
        };
        request.ExecutionMetadata["source"] = configuredRuntime.Invoke.Source;
        request.ExecutionMetadata["scenario"] = scenario;
        request.ExecutionMetadata["runtime_name"] = configuredRuntime.Runtime.Name;
        request.ExecutionMetadata["request_id"] = $"request-{Guid.NewGuid():N}";
        return request;
    }
}
