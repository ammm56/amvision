using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;

namespace Amvision.Workflows
{

    /// <summary>
    /// 模型部署 multipart/form-data 推理请求。
    /// </summary>
    public sealed class ModelDeploymentInferenceUploadRequest
    {
        /// <summary>
        /// 异步推理任务所属 Project id。
        /// </summary>
        public string? ProjectId { get; set; }

        /// <summary>
        /// 异步推理任务使用的 DeploymentInstance id。
        /// </summary>
        public string? DeploymentInstanceId { get; set; }

        /// <summary>
        /// 模型类型；通常不需要设置，后端可从 DeploymentInstance 解析。
        /// </summary>
        public string? ModelType { get; set; }

        /// <summary>
        /// 输入图片 bytes。
        /// </summary>
        public byte[] ImageBytes { get; set; } = Array.Empty<byte>();

        /// <summary>
        /// 上传文件名。
        /// </summary>
        public string FileName { get; set; } = "input-image.bin";

        /// <summary>
        /// 图片 media type。
        /// </summary>
        public string MediaType { get; set; } = "application/octet-stream";

        /// <summary>
        /// 输入传输模式。
        /// </summary>
        public string InputTransportMode { get; set; } = "memory";

        /// <summary>
        /// detection/segmentation/pose/obb 常用 score threshold。
        /// </summary>
        public double? ScoreThreshold { get; set; }

        /// <summary>
        /// classification top-k。
        /// </summary>
        public int? TopK { get; set; }

        /// <summary>
        /// segmentation mask threshold。
        /// </summary>
        public double? MaskThreshold { get; set; }

        /// <summary>
        /// pose keypoint confidence threshold。
        /// </summary>
        public double? KeypointConfidenceThreshold { get; set; }

        /// <summary>
        /// 是否保存结果预览图。
        /// </summary>
        public bool? SaveResultImage { get; set; }

        /// <summary>
        /// 是否返回预览图 base64。
        /// </summary>
        public bool? ReturnPreviewImageBase64 { get; set; }

        /// <summary>
        /// 异步推理任务显示名称。
        /// </summary>
        public string? DisplayName { get; set; }

        /// <summary>
        /// 任务特定的扩展选项。
        /// </summary>
        public IDictionary<string, object?> ExtraOptions { get; } = new Dictionary<string, object?>();

        /// <summary>
        /// 从图片 bytes 创建上传请求。
        /// </summary>
        public static ModelDeploymentInferenceUploadRequest FromBytes(
            byte[] imageBytes,
            string fileName = "input-image.bin",
            string mediaType = "application/octet-stream")
        {
            if (imageBytes is null || imageBytes.Length == 0)
            {
                throw new ArgumentException("imageBytes cannot be empty.", nameof(imageBytes));
            }

            return new ModelDeploymentInferenceUploadRequest
            {
                ImageBytes = imageBytes,
                FileName = string.IsNullOrWhiteSpace(fileName) ? "input-image.bin" : fileName.Trim(),
                MediaType = string.IsNullOrWhiteSpace(mediaType) ? "application/octet-stream" : mediaType.Trim()
            };
        }

        /// <summary>
        /// 从本机图片文件创建上传请求。
        /// </summary>
        public static ModelDeploymentInferenceUploadRequest FromFile(string filePath, string? mediaType = null)
        {
            if (string.IsNullOrWhiteSpace(filePath))
            {
                throw new ArgumentException("filePath cannot be empty.", nameof(filePath));
            }

            var normalizedPath = filePath.Trim();
            return FromBytes(
                File.ReadAllBytes(normalizedPath),
                Path.GetFileName(normalizedPath),
                mediaType ?? InferMediaType(normalizedPath));
        }

        /// <summary>
        /// 从 stream 创建上传请求。
        /// </summary>
        public static ModelDeploymentInferenceUploadRequest FromStream(
            Stream stream,
            string fileName,
            string mediaType = "application/octet-stream")
        {
            if (stream is null)
            {
                throw new ArgumentNullException(nameof(stream));
            }

            using var memoryStream = new MemoryStream();
            stream.CopyTo(memoryStream);
            return FromBytes(memoryStream.ToArray(), fileName, mediaType);
        }

        /// <summary>
        /// 构造直接推理 multipart content。
        /// </summary>
        internal MultipartFormDataContent ToDirectInferenceContent()
        {
            return ToMultipartContent(includeTaskFields: false);
        }

        /// <summary>
        /// 构造异步推理任务 multipart content。
        /// </summary>
        internal MultipartFormDataContent ToInferenceTaskContent()
        {
            return ToMultipartContent(includeTaskFields: true);
        }

        private MultipartFormDataContent ToMultipartContent(bool includeTaskFields)
        {
            Validate(includeTaskFields);
            var content = new MultipartFormDataContent();
            if (includeTaskFields)
            {
                AddString(content, "project_id", ProjectId);
                AddString(content, "deployment_instance_id", DeploymentInstanceId);
                AddString(content, "display_name", DisplayName);
            }

            AddString(content, "model_type", ModelType);
            AddString(content, "input_transport_mode", InputTransportMode);
            AddString(content, "score_threshold", FormatInvariant(ScoreThreshold));
            AddString(content, "top_k", TopK?.ToString(CultureInfo.InvariantCulture));
            AddString(content, "mask_threshold", FormatInvariant(MaskThreshold));
            AddString(content, "keypoint_confidence_threshold", FormatInvariant(KeypointConfidenceThreshold));
            AddString(content, "save_result_image", SaveResultImage?.ToString().ToLowerInvariant());
            AddString(content, "return_preview_image_base64", ReturnPreviewImageBase64?.ToString().ToLowerInvariant());
            if (ExtraOptions.Count > 0)
            {
                AddString(content, "extra_options", WorkflowJsonDefaults.Serialize(ExtraOptions));
            }

            var imageContent = new ByteArrayContent(ImageBytes);
            imageContent.Headers.ContentType = MediaTypeHeaderValue.Parse(MediaType);
            content.Add(imageContent, "input_image", FileName);
            return content;
        }

        private void Validate(bool requireTaskFields)
        {
            if (requireTaskFields)
            {
                if (string.IsNullOrWhiteSpace(ProjectId))
                {
                    throw new InvalidOperationException("ProjectId cannot be empty when creating an inference task.");
                }

                if (string.IsNullOrWhiteSpace(DeploymentInstanceId))
                {
                    throw new InvalidOperationException("DeploymentInstanceId cannot be empty when creating an inference task.");
                }
            }

            if (ImageBytes is null || ImageBytes.Length == 0)
            {
                throw new InvalidOperationException("ImageBytes cannot be empty.");
            }

            if (string.IsNullOrWhiteSpace(FileName))
            {
                throw new InvalidOperationException("FileName cannot be empty.");
            }

            if (string.IsNullOrWhiteSpace(MediaType))
            {
                throw new InvalidOperationException("MediaType cannot be empty.");
            }

            if (string.IsNullOrWhiteSpace(InputTransportMode))
            {
                throw new InvalidOperationException("InputTransportMode cannot be empty.");
            }

            ValidateThreshold(ScoreThreshold, nameof(ScoreThreshold));
            ValidateThreshold(MaskThreshold, nameof(MaskThreshold));
            ValidateThreshold(KeypointConfidenceThreshold, nameof(KeypointConfidenceThreshold));
            if (TopK != null && TopK.Value <= 0)
            {
                throw new InvalidOperationException("TopK must be greater than zero.");
            }
        }

        private static void AddString(MultipartFormDataContent content, string name, string? value)
        {
            if (!string.IsNullOrWhiteSpace(value))
            {
                var normalized = value!.Trim();
                content.Add(new StringContent(normalized, Encoding.UTF8), name);
            }
        }

        private static string? FormatInvariant(double? value)
        {
            return value?.ToString(CultureInfo.InvariantCulture);
        }

        private static void ValidateThreshold(double? value, string name)
        {
            if (value != null && (value.Value < 0 || value.Value > 1))
            {
                throw new InvalidOperationException($"{name} must be between 0 and 1.");
            }
        }

        private static string InferMediaType(string filePath)
        {
            var extension = Path.GetExtension(filePath).ToLowerInvariant();
            switch (extension)
            {
                case ".jpg":
                case ".jpeg":
                    return "image/jpeg";
                case ".png":
                    return "image/png";
                case ".bmp":
                    return "image/bmp";
                case ".webp":
                    return "image/webp";
                case ".tif":
                case ".tiff":
                    return "image/tiff";
                default:
                    return "application/octet-stream";
            }
        }
    }
}
