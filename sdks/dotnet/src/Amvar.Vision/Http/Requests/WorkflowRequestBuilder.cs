using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Newtonsoft.Json;

namespace Amvar.Vision
{
    /// <summary>
    /// 描述一个不带 binding id、可在每次发送时独立打开 stream 的上传文件。
    /// </summary>
    public sealed class WorkflowUploadFile
    {
        private WorkflowUploadFile(
            Func<Stream> streamFactory,
            string fileName,
            string mediaType,
            long? contentLength)
        {
            StreamFactory = streamFactory ?? throw new ArgumentNullException(nameof(streamFactory));
            FileName = RequireText(fileName, nameof(fileName));
            MediaType = RequireText(mediaType, nameof(mediaType));
            if (contentLength != null && contentLength.Value <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(contentLength));
            }
            ContentLength = contentLength;
        }

        /// <summary>每次发送创建独立可读 stream 的工厂。</summary>
        public Func<Stream> StreamFactory { get; }

        /// <summary>公开文件名。</summary>
        public string FileName { get; }

        /// <summary>文件 MIME media type。</summary>
        public string MediaType { get; }

        /// <summary>可选内容长度。</summary>
        public long? ContentLength { get; }

        /// <summary>从独立 stream factory 创建上传文件。</summary>
        public static WorkflowUploadFile FromStreamFactory(
            Func<Stream> streamFactory,
            string fileName,
            string mediaType = "application/octet-stream",
            long? contentLength = null)
        {
            return new WorkflowUploadFile(streamFactory, fileName, mediaType, contentLength);
        }

        /// <summary>从文件路径创建发送时才打开的上传文件。</summary>
        public static WorkflowUploadFile FromFile(
            string filePath,
            string mediaType = "application/octet-stream")
        {
            var normalizedPath = RequireText(filePath, nameof(filePath));
            var fileInfo = new FileInfo(normalizedPath);
            if (!fileInfo.Exists)
            {
                throw new FileNotFoundException("Upload file does not exist.", normalizedPath);
            }
            return FromStreamFactory(
                () => new FileStream(
                    normalizedPath,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.Read,
                    1024 * 1024,
                    FileOptions.SequentialScan),
                Path.GetFileName(normalizedPath),
                mediaType,
                fileInfo.Length);
        }

        internal WorkflowRuntimeMultipartFile Bind(string bindingId)
        {
            return WorkflowRuntimeMultipartFile.FromStreamFactory(
                RequireText(bindingId, nameof(bindingId)),
                StreamFactory,
                FileName,
                MediaType,
                ContentLength);
        }

        private static string RequireText(string value, string parameterName)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                throw new ArgumentException(parameterName + " cannot be empty.", parameterName);
            }
            return value.Trim();
        }
    }

    /// <summary>
    /// 组合构造 JSON、文本、图片、单文件和有序多文件 Workflow 请求。
    /// </summary>
    public sealed class WorkflowRequestBuilder
    {
        private readonly WorkflowRuntimeMultipartInvokeRequest request = new WorkflowRuntimeMultipartInvokeRequest();
        private readonly WorkflowAppContract? contract;
        private readonly HashSet<string> suppliedBindingIds = new HashSet<string>(StringComparer.Ordinal);

        /// <summary>创建不绑定本地 contract 的请求 builder。</summary>
        public WorkflowRequestBuilder()
        {
        }

        /// <summary>创建使用 SDK 配置包冻结 contract 做调用前快速失败的 builder。</summary>
        public WorkflowRequestBuilder(WorkflowAppContract contract)
        {
            this.contract = contract ?? throw new ArgumentNullException(nameof(contract));
            contract.Validate(nameof(contract));
        }

        /// <summary>增加 value.v1 JSON 输入。</summary>
        public WorkflowRequestBuilder AddJson(string bindingId, object? value)
        {
            var normalizedBindingId = RequireBindingId(bindingId);
            var contractInput = RequireContractInput(normalizedBindingId, "value.v1");
            ValidateTransport(contractInput, "json");
            var payload = new Dictionary<string, object?>
            {
                ["value"] = value
            };
            ValidateInlineSize(contractInput, payload);
            ReserveBinding(normalizedBindingId);
            request.InputBindings[normalizedBindingId] = payload;
            return this;
        }

        /// <summary>增加 text.v1 输入。</summary>
        public WorkflowRequestBuilder AddText(
            string bindingId,
            string text,
            string mediaType = "text/plain",
            string charset = "utf-8")
        {
            if (text is null) throw new ArgumentNullException(nameof(text));
            var normalizedBindingId = RequireBindingId(bindingId);
            var contractInput = RequireContractInput(normalizedBindingId, "text.v1");
            ValidateMediaType(contractInput, mediaType);
            ValidateTransport(contractInput, "json");
            var normalizedCharset = RequireText(charset, nameof(charset));
            var publishedCharset = contractInput?.Charset;
            if (!string.IsNullOrWhiteSpace(publishedCharset)
                && !string.Equals(publishedCharset, normalizedCharset, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("Charset is rejected by the published App Contract.");
            }
            var payload = new Dictionary<string, object?>
            {
                ["text"] = text,
                ["media_type"] = RequireText(mediaType, nameof(mediaType)),
                ["charset"] = normalizedCharset
            };
            ValidateInlineSize(contractInput, payload);
            ReserveBinding(normalizedBindingId);
            request.InputBindings[normalizedBindingId] = payload;
            return this;
        }

        /// <summary>增加 image-ref.v1 multipart 图片输入。</summary>
        public WorkflowRequestBuilder AddImage(
            string bindingId,
            Func<Stream> streamFactory,
            string fileName,
            string mediaType,
            long? contentLength = null)
        {
            return AddUpload(
                bindingId,
                "image-ref.v1",
                streamFactory,
                fileName,
                mediaType,
                contentLength);
        }

        /// <summary>增加 file-ref.v1 multipart 文件输入。</summary>
        public WorkflowRequestBuilder AddFile(
            string bindingId,
            Func<Stream> streamFactory,
            string fileName,
            string mediaType = "application/octet-stream",
            long? contentLength = null)
        {
            return AddUpload(
                bindingId,
                "file-ref.v1",
                streamFactory,
                fileName,
                mediaType,
                contentLength);
        }

        /// <summary>按枚举顺序增加 file-refs.v1 multipart 文件输入。</summary>
        public WorkflowRequestBuilder AddFiles(
            string bindingId,
            IEnumerable<WorkflowUploadFile> orderedFiles)
        {
            if (orderedFiles is null) throw new ArgumentNullException(nameof(orderedFiles));
            var normalizedBindingId = RequireBindingId(bindingId);
            var contractInput = RequireContractInput(normalizedBindingId, "file-refs.v1");
            ValidateTransport(contractInput, "multipart-upload");
            var files = orderedFiles.ToList();
            if (files.Count == 0 || files.Any(file => file is null))
            {
                throw new ArgumentException("orderedFiles must contain at least one non-null file.", nameof(orderedFiles));
            }
            if (contractInput?.MaxFiles != null && files.Count > contractInput.MaxFiles.Value)
            {
                throw new InvalidOperationException("File count exceeds the published App Contract.");
            }
            foreach (var file in files)
            {
                ValidateUploadContract(contractInput, file!.MediaType, file.ContentLength);
            }
            ReserveBinding(normalizedBindingId);
            foreach (var file in files) request.Files.Add(file!.Bind(normalizedBindingId));
            return this;
        }

        /// <summary>增加执行元数据。</summary>
        public WorkflowRequestBuilder AddExecutionMetadata(string key, object? value)
        {
            request.ExecutionMetadata[RequireText(key, nameof(key))] = value;
            return this;
        }

        /// <summary>设置后端执行 timeout；不会增加 SDK 侧重试或等待队列。</summary>
        public WorkflowRequestBuilder WithTimeoutSeconds(int timeoutSeconds)
        {
            if (timeoutSeconds <= 0) throw new ArgumentOutOfRangeException(nameof(timeoutSeconds));
            request.TimeoutSeconds = timeoutSeconds;
            return this;
        }

        /// <summary>返回可交给 AMVisionClient multipart API 的请求。</summary>
        public WorkflowRuntimeMultipartInvokeRequest Build()
        {
            if (contract != null)
            {
                foreach (var input in contract.Inputs)
                {
                    if (input.Required && !suppliedBindingIds.Contains(input.BindingId))
                    {
                        throw new InvalidOperationException(
                            "Required Workflow input is missing: " + input.BindingId);
                    }
                }
            }
            request.Validate();
            return request;
        }

        private WorkflowRequestBuilder AddUpload(
            string bindingId,
            string payloadTypeId,
            Func<Stream> streamFactory,
            string fileName,
            string mediaType,
            long? contentLength)
        {
            var normalizedBindingId = RequireBindingId(bindingId);
            var contractInput = RequireContractInput(normalizedBindingId, payloadTypeId);
            ValidateTransport(contractInput, "multipart-upload");
            ValidateUploadContract(contractInput, mediaType, contentLength);
            var upload = WorkflowUploadFile.FromStreamFactory(
                streamFactory,
                fileName,
                mediaType,
                contentLength);
            ReserveBinding(normalizedBindingId);
            request.Files.Add(upload.Bind(normalizedBindingId));
            return this;
        }

        private WorkflowAppContractInput? RequireContractInput(
            string bindingId,
            string payloadTypeId)
        {
            if (contract is null) return null;
            var input = contract.Inputs.FirstOrDefault(
                item => string.Equals(item.BindingId, bindingId, StringComparison.Ordinal));
            if (input is null)
            {
                throw new InvalidOperationException("Unknown Workflow input binding: " + bindingId);
            }
            if (!string.Equals(input.PayloadTypeId, payloadTypeId, StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "Workflow input payload type mismatch for " + bindingId + ".");
            }
            return input;
        }

        private static void ValidateUploadContract(
            WorkflowAppContractInput? input,
            string mediaType,
            long? contentLength)
        {
            if (input is null) return;
            ValidateMediaType(input, mediaType);
            if (contentLength != null && input.MaxFileBytes != null
                && contentLength.Value > input.MaxFileBytes.Value)
            {
                throw new InvalidOperationException("File size exceeds the published App Contract.");
            }
        }

        private static void ValidateInlineSize(
            WorkflowAppContractInput? input,
            object payload)
        {
            if (input?.MaxInlineBytes is null) return;
            var encodedLength = Encoding.UTF8.GetByteCount(
                JsonConvert.SerializeObject(payload, Formatting.None));
            if (encodedLength > input.MaxInlineBytes.Value)
            {
                throw new InvalidOperationException("Inline value exceeds the published App Contract.");
            }
        }

        private static void ValidateTransport(
            WorkflowAppContractInput? input,
            string transport)
        {
            if (input is null || input.Transports.Count == 0) return;
            if (!input.Transports.Any(item => string.Equals(item, transport, StringComparison.Ordinal)))
            {
                throw new InvalidOperationException("Transport is rejected by the published App Contract.");
            }
        }

        private void ReserveBinding(string bindingId)
        {
            if (!suppliedBindingIds.Add(bindingId))
            {
                throw new InvalidOperationException(
                    "Workflow input binding was already supplied: " + bindingId);
            }
        }

        private static void ValidateMediaType(
            WorkflowAppContractInput? input,
            string mediaType)
        {
            if (input is null || input.AllowedMediaTypes.Count == 0) return;
            var normalized = RequireText(mediaType, nameof(mediaType)).ToLowerInvariant();
            var accepted = input.AllowedMediaTypes.Any(pattern =>
            {
                var rule = (pattern ?? string.Empty).Trim().ToLowerInvariant();
                return rule.EndsWith("/*", StringComparison.Ordinal)
                    ? normalized.StartsWith(rule.Substring(0, rule.Length - 1), StringComparison.Ordinal)
                    : normalized == rule;
            });
            if (!accepted)
            {
                throw new InvalidOperationException("Media type is rejected by the published App Contract.");
            }
        }

        private static string RequireBindingId(string value)
        {
            return RequireText(value, "bindingId");
        }

        private static string RequireText(string value, string parameterName)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                throw new ArgumentException(parameterName + " cannot be empty.", parameterName);
            }
            return value.Trim();
        }
    }
}
