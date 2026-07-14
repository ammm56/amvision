using System;
using System.Collections.Generic;
using System.IO;

namespace Amvision.Workflows
{

    /// <summary>
    /// 描述一次按 image-base64.v1 调用 WorkflowAppRuntime 的请求。
    /// </summary>
    public sealed class WorkflowRuntimeImageInvokeRequest
    {
        /// <summary>
        /// 要编码为 image_base64 的图片 bytes。
        /// </summary>
        public byte[] ImageBytes { get; set; } = Array.Empty<byte>();

        /// <summary>
        /// 输入 binding 名称。
        /// </summary>
        public string InputBinding { get; set; } = "request_image_base64";

        /// <summary>
        /// 图片 media type。
        /// </summary>
        public string MediaType { get; set; } = "image/octet-stream";

        /// <summary>
        /// 可选 timeout_seconds。
        /// </summary>
        public int? TimeoutSeconds { get; set; }

        /// <summary>
        /// 写入 execution_metadata 的附加字段。
        /// </summary>
        public IDictionary<string, object?> ExecutionMetadata { get; } = new Dictionary<string, object?>();

        /// <summary>
        /// 除图片输入外额外写入 input_bindings 的字段。
        /// </summary>
        public IDictionary<string, object?> AdditionalInputBindings { get; } = new Dictionary<string, object?>();

        /// <summary>
        /// 是否把 input binding 直接写成顶层公开 input 字段。
        /// </summary>
        public bool UseDirectInputBindings { get; set; }

        /// <summary>
        /// 从已有图片 bytes 创建 HTTP image-base64 runtime 调用请求。
        /// </summary>
        /// <param name="imageBytes">图片编码 bytes，通常来自工业相机 SDK、内存缓存或已读取的文件。</param>
        /// <param name="mediaType">MIME media type，例如 image/jpeg。</param>
        /// <param name="inputBinding">WorkflowApp input binding 名称。</param>
        /// <returns>image-base64 runtime 调用请求。</returns>
        public static WorkflowRuntimeImageInvokeRequest FromBytes(
            byte[] imageBytes,
            string mediaType = "image/octet-stream",
            string inputBinding = "request_image_base64")
        {
            if (imageBytes is null || imageBytes.Length == 0)
            {
                throw new ArgumentException("imageBytes cannot be empty.", nameof(imageBytes));
            }

            return new WorkflowRuntimeImageInvokeRequest
            {
                ImageBytes = imageBytes,
                MediaType = NormalizeMediaType(mediaType),
                InputBinding = NormalizeInputBinding(inputBinding)
            };
        }

        /// <summary>
        /// 从本机图片文件创建 HTTP image-base64 runtime 调用请求。
        /// </summary>
        /// <param name="filePath">图片文件路径。</param>
        /// <param name="mediaType">可选 MIME media type；为空时按扩展名推断。</param>
        /// <param name="inputBinding">WorkflowApp input binding 名称。</param>
        /// <returns>image-base64 runtime 调用请求。</returns>
        public static WorkflowRuntimeImageInvokeRequest FromFile(
            string filePath,
            string? mediaType = null,
            string inputBinding = "request_image_base64")
        {
            if (string.IsNullOrWhiteSpace(filePath))
            {
                throw new ArgumentException("filePath cannot be empty.", nameof(filePath));
            }

            var normalizedPath = filePath.Trim();
            return FromBytes(
                File.ReadAllBytes(normalizedPath),
                mediaType ?? InferMediaType(normalizedPath),
                inputBinding);
        }

        /// <summary>
        /// 从 base64 或 data URL 创建 HTTP image-base64 runtime 调用请求。
        /// </summary>
        /// <param name="imageBase64">纯 base64 字符串，或 data:image/...;base64,...。</param>
        /// <param name="mediaType">可选 MIME media type；data URL 会优先使用自身声明。</param>
        /// <param name="inputBinding">WorkflowApp input binding 名称。</param>
        /// <returns>image-base64 runtime 调用请求。</returns>
        public static WorkflowRuntimeImageInvokeRequest FromBase64(
            string imageBase64,
            string? mediaType = null,
            string inputBinding = "request_image_base64")
        {
            if (string.IsNullOrWhiteSpace(imageBase64))
            {
                throw new ArgumentException("imageBase64 cannot be empty.", nameof(imageBase64));
            }

            var normalizedBase64 = imageBase64.Trim();
            var resolvedMediaType = mediaType;
            var commaIndex = normalizedBase64.IndexOf(',');
            if (normalizedBase64.StartsWith("data:", StringComparison.OrdinalIgnoreCase) && commaIndex > 0)
            {
                var header = normalizedBase64.Substring(5, commaIndex - 5);
                var separatorIndex = header.IndexOf(';');
                var headerMediaType = separatorIndex >= 0 ? header.Substring(0, separatorIndex) : header;
                if (!string.IsNullOrWhiteSpace(headerMediaType))
                {
                    resolvedMediaType = headerMediaType.Trim();
                }

                normalizedBase64 = normalizedBase64.Substring(commaIndex + 1);
            }

            return FromBytes(
                Convert.FromBase64String(normalizedBase64),
                resolvedMediaType ?? "image/octet-stream",
                inputBinding);
        }

        /// <summary>
        /// 从 stream 读取图片 bytes 创建 HTTP image-base64 runtime 调用请求。
        /// </summary>
        /// <param name="stream">包含图片编码数据的 stream。</param>
        /// <param name="mediaType">MIME media type，例如 image/jpeg。</param>
        /// <param name="inputBinding">WorkflowApp input binding 名称。</param>
        /// <returns>image-base64 runtime 调用请求。</returns>
        public static WorkflowRuntimeImageInvokeRequest FromStream(
            Stream stream,
            string mediaType = "image/octet-stream",
            string inputBinding = "request_image_base64")
        {
            if (stream is null)
            {
                throw new ArgumentNullException(nameof(stream));
            }

            using var memoryStream = new MemoryStream();
            stream.CopyTo(memoryStream);
            return FromBytes(memoryStream.ToArray(), mediaType, inputBinding);
        }

        /// <summary>
        /// 转换为通用 invoke 请求对象。
        /// </summary>
        /// <returns>通用 invoke 请求。</returns>
        public WorkflowRuntimeInvokeRequest ToWorkflowRuntimeInvokeRequest()
        {
            Validate();
            var request = new WorkflowRuntimeInvokeRequest
            {
                TimeoutSeconds = TimeoutSeconds,
                UseDirectInputBindings = UseDirectInputBindings
            };
            foreach (var pair in AdditionalInputBindings)
            {
                request.InputBindings[pair.Key] = pair.Value;
            }

            request.InputBindings[InputBinding.Trim()] = new Dictionary<string, object?>
            {
                ["image_base64"] = Convert.ToBase64String(ImageBytes),
                ["media_type"] = MediaType.Trim()
            };
            foreach (var pair in ExecutionMetadata)
            {
                request.ExecutionMetadata[pair.Key] = pair.Value;
            }

            return request;
        }

        /// <summary>
        /// 校验图片 invoke 请求的基础字段。
        /// </summary>
        internal void Validate()
        {
            if (ImageBytes is null || ImageBytes.Length == 0)
            {
                throw new InvalidOperationException("ImageBytes cannot be empty.");
            }

            if (string.IsNullOrWhiteSpace(InputBinding))
            {
                throw new InvalidOperationException("InputBinding cannot be empty.");
            }

            if (string.IsNullOrWhiteSpace(MediaType))
            {
                throw new InvalidOperationException("MediaType cannot be empty.");
            }

            if (TimeoutSeconds != null && TimeoutSeconds.Value <= 0)
            {
                throw new InvalidOperationException("TimeoutSeconds must be greater than zero.");
            }
        }

        private static string NormalizeInputBinding(string inputBinding)
        {
            if (string.IsNullOrWhiteSpace(inputBinding))
            {
                throw new ArgumentException("inputBinding cannot be empty.", nameof(inputBinding));
            }

            return inputBinding.Trim();
        }

        private static string NormalizeMediaType(string mediaType)
        {
            return string.IsNullOrWhiteSpace(mediaType) ? "image/octet-stream" : mediaType.Trim();
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
                    return "image/octet-stream";
            }
        }
    }
}
