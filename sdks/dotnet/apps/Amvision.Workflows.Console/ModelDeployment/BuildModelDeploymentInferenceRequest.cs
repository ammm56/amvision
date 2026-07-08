using System.IO;
using Amvision.Workflows.Console.Model;

namespace Amvision.Workflows.Console.ModelDeployment;

/// <summary>
/// 构建模型 deployment 推理请求。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 使用配置中的默认输入构建 JSON 或 multipart 推理请求，并执行对应回调。
    /// </summary>
    /// <typeparam name="T">调用返回类型。</typeparam>
    /// <param name="configuredModelDeployment">模型 deployment 配置。</param>
    /// <param name="jsonCallback">JSON 请求回调。</param>
    /// <param name="uploadCallback">multipart 上传请求回调。</param>
    /// <returns>调用结果。</returns>
    private static T BuildConfiguredInput<T>(
        ConfiguredModelDeployment configuredModelDeployment,
        Func<ModelDeploymentInferenceRequest, T> jsonCallback,
        Func<ModelDeploymentInferenceUploadRequest, T> uploadCallback)
    {
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        var defaultImagePath = ConfigValidation.NormalizeOptional(modelDeployment.DefaultImagePath);
        var defaultInputUri = ConfigValidation.NormalizeOptional(modelDeployment.DefaultInputUri);
        var defaultInputFileId = ConfigValidation.NormalizeOptional(modelDeployment.DefaultInputFileId);
        var inputCount = 0;
        inputCount += defaultImagePath is null ? 0 : 1;
        inputCount += defaultInputUri is null ? 0 : 1;
        inputCount += defaultInputFileId is null ? 0 : 1;
        if (inputCount != 1)
        {
            throw new InvalidOperationException($"{modelDeployment.Name} must configure exactly one of default_image_path, default_input_uri or default_input_file_id before using configured input.");
        }

        if (defaultImagePath is not null)
        {
            return uploadCallback(BuildUploadRequestFromFile(configuredModelDeployment, defaultImagePath, null));
        }

        var request = defaultInputUri is not null
            ? BuildJsonRequestFromInputUri(configuredModelDeployment, defaultInputUri)
            : BuildJsonRequestFromInputFileId(configuredModelDeployment, defaultInputFileId!);
        return jsonCallback(request);
    }

    /// <summary>
    /// 从 base64 图片构建 JSON 推理请求。
    /// </summary>
    private static ModelDeploymentInferenceRequest BuildJsonRequestFromBase64(
        ConfiguredModelDeployment configuredModelDeployment,
        string imageBase64)
    {
        return ApplyJsonInferenceDefaults(
            ModelDeploymentInferenceRequest.FromBase64(imageBase64),
            configuredModelDeployment,
            useConfiguredTransportMode: true);
    }

    /// <summary>
    /// 从 input URI 构建 JSON 推理请求。
    /// </summary>
    private static ModelDeploymentInferenceRequest BuildJsonRequestFromInputUri(
        ConfiguredModelDeployment configuredModelDeployment,
        string inputUri)
    {
        var request = ApplyJsonInferenceDefaults(
            ModelDeploymentInferenceRequest.FromUri(inputUri),
            configuredModelDeployment,
            useConfiguredTransportMode: false);
        request.InputTransportMode = "storage";
        return request;
    }

    /// <summary>
    /// 从 input file id 构建 JSON 推理请求。
    /// </summary>
    private static ModelDeploymentInferenceRequest BuildJsonRequestFromInputFileId(
        ConfiguredModelDeployment configuredModelDeployment,
        string inputFileId)
    {
        var request = ApplyJsonInferenceDefaults(
            ModelDeploymentInferenceRequest.FromFileId(inputFileId),
            configuredModelDeployment,
            useConfiguredTransportMode: false);
        request.InputTransportMode = "storage";
        return request;
    }

    /// <summary>
    /// 从图片 bytes 构建 multipart 推理请求。
    /// </summary>
    private static ModelDeploymentInferenceUploadRequest BuildUploadRequestFromBytes(
        ConfiguredModelDeployment configuredModelDeployment,
        byte[] imageBytes,
        string? fileName,
        string? mediaType)
    {
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        return ApplyUploadInferenceDefaults(
            ModelDeploymentInferenceUploadRequest.FromBytes(
                imageBytes,
                ConfigValidation.NormalizeOptional(fileName) ?? modelDeployment.DefaultFileName,
                ConfigValidation.NormalizeOptional(mediaType) ?? modelDeployment.DefaultMediaType),
            configuredModelDeployment);
    }

    /// <summary>
    /// 从图片文件路径构建 multipart 推理请求。
    /// </summary>
    private static ModelDeploymentInferenceUploadRequest BuildUploadRequestFromFile(
        ConfiguredModelDeployment configuredModelDeployment,
        string imagePath,
        string? mediaType)
    {
        var resolvedImagePath = ResolveConfiguredPath(configuredModelDeployment, imagePath);
        return ApplyUploadInferenceDefaults(
            ModelDeploymentInferenceUploadRequest.FromFile(
                resolvedImagePath,
                mediaType ?? InferImageMediaType(resolvedImagePath)),
            configuredModelDeployment);
    }

    /// <summary>
    /// 写入 JSON 推理请求公共配置。
    /// </summary>
    private static ModelDeploymentInferenceRequest ApplyJsonInferenceDefaults(
        ModelDeploymentInferenceRequest request,
        ConfiguredModelDeployment configuredModelDeployment,
        bool useConfiguredTransportMode)
    {
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        request.ProjectId = configuredModelDeployment.Backend.ProjectId;
        request.DeploymentInstanceId = modelDeployment.DeploymentInstanceId;
        if (useConfiguredTransportMode)
        {
            request.InputTransportMode = modelDeployment.InputTransportMode;
        }

        request.ScoreThreshold = modelDeployment.ScoreThreshold;
        request.TopK = modelDeployment.TopK;
        request.MaskThreshold = modelDeployment.MaskThreshold;
        request.KeypointConfidenceThreshold = modelDeployment.KeypointConfidenceThreshold;
        request.SaveResultImage = modelDeployment.SaveResultImage;
        request.ReturnPreviewImageBase64 = modelDeployment.ReturnPreviewImageBase64;
        return request;
    }

    /// <summary>
    /// 写入 multipart 推理请求公共配置。
    /// </summary>
    private static ModelDeploymentInferenceUploadRequest ApplyUploadInferenceDefaults(
        ModelDeploymentInferenceUploadRequest request,
        ConfiguredModelDeployment configuredModelDeployment)
    {
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        request.ProjectId = configuredModelDeployment.Backend.ProjectId;
        request.DeploymentInstanceId = modelDeployment.DeploymentInstanceId;
        request.InputTransportMode = modelDeployment.InputTransportMode;
        request.ScoreThreshold = modelDeployment.ScoreThreshold;
        request.TopK = modelDeployment.TopK;
        request.MaskThreshold = modelDeployment.MaskThreshold;
        request.KeypointConfidenceThreshold = modelDeployment.KeypointConfidenceThreshold;
        request.SaveResultImage = modelDeployment.SaveResultImage;
        request.ReturnPreviewImageBase64 = modelDeployment.ReturnPreviewImageBase64;
        return request;
    }
}
