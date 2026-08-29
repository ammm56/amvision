using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading;

namespace Amvar.Vision
{

    /// <summary>
    /// 描述一次 WorkflowAppRuntime multipart/form-data 调用请求。
    /// </summary>
    public sealed class WorkflowRuntimeMultipartInvokeRequest
    {
        /// <summary>
        /// input_bindings_json 对象；用于非文件输入绑定。
        /// </summary>
        public IDictionary<string, object?> InputBindings { get; } = new Dictionary<string, object?>();

        /// <summary>
        /// execution_metadata_json 对象。
        /// </summary>
        public IDictionary<string, object?> ExecutionMetadata { get; } = new Dictionary<string, object?>();

        /// <summary>
        /// 需要作为 multipart 文件字段上传的输入绑定。
        /// </summary>
        public IList<WorkflowRuntimeMultipartFile> Files { get; } = new List<WorkflowRuntimeMultipartFile>();

        /// <summary>
        /// 可选 timeout_seconds。
        /// </summary>
        public int? TimeoutSeconds { get; set; }

        /// <summary>
        /// 构造 backend-service 兼容的 multipart/form-data content。
        /// </summary>
        /// <returns>HTTP multipart content。</returns>
        internal MultipartFormDataContent ToMultipartContent()
        {
            Validate();
            var content = new MultipartFormDataContent();
            if (InputBindings.Count > 0)
            {
                content.Add(
                    new StringContent(WorkflowJsonDefaults.Serialize(InputBindings), Encoding.UTF8, "application/json"),
                    "input_bindings_json");
            }

            if (ExecutionMetadata.Count > 0)
            {
                content.Add(
                    new StringContent(WorkflowJsonDefaults.Serialize(ExecutionMetadata), Encoding.UTF8, "application/json"),
                    "execution_metadata_json");
            }

            if (TimeoutSeconds != null)
            {
                content.Add(new StringContent(TimeoutSeconds.Value.ToString(System.Globalization.CultureInfo.InvariantCulture)), "timeout_seconds");
            }

            foreach (var file in Files)
            {
                var fileContent = file.ToHttpContent();
                content.Add(fileContent, file.BindingId, file.FileName);
            }

            return content;
        }

        /// <summary>
        /// 校验当前 multipart 请求的基础字段。
        /// </summary>
        internal void Validate()
        {
            if (TimeoutSeconds != null && TimeoutSeconds.Value <= 0)
            {
                throw new InvalidOperationException("TimeoutSeconds must be greater than zero.");
            }

            foreach (var file in Files)
            {
                file.Validate();
            }
        }
    }

    /// <summary>
    /// WorkflowAppRuntime multipart 文件输入绑定。
    /// </summary>
    public sealed class WorkflowRuntimeMultipartFile
    {
        /// <summary>
        /// 文件字段对应的 application input binding id。
        /// </summary>
        public string BindingId { get; set; } = string.Empty;

        /// <summary>
        /// 上传文件名。
        /// </summary>
        public string FileName { get; set; } = "upload.bin";

        /// <summary>
        /// 文件 MIME media type。
        /// </summary>
        public string MediaType { get; set; } = "application/octet-stream";

        /// <summary>
        /// 可选文件内容 bytes；只用于调用方已经持有 bytes 的兼容入口。
        /// </summary>
        public byte[]? ContentBytes { get; set; }

        /// <summary>
        /// 每次发送时创建独立可读 stream 的工厂。
        /// </summary>
        public Func<Stream>? StreamFactory { get; set; }

        /// <summary>
        /// 可选内容长度；已知时写入 Content-Length，不会预读 stream。
        /// </summary>
        public long? ContentLength { get; set; }

        /// <summary>
        /// 从 bytes 创建 multipart 文件绑定。
        /// </summary>
        public static WorkflowRuntimeMultipartFile FromBytes(
            string bindingId,
            byte[] contentBytes,
            string fileName,
            string mediaType = "application/octet-stream")
        {
            return new WorkflowRuntimeMultipartFile
            {
                BindingId = bindingId,
                ContentBytes = contentBytes,
                ContentLength = contentBytes?.LongLength,
                FileName = fileName,
                MediaType = mediaType
            };
        }

        /// <summary>
        /// 从本机文件创建 multipart 文件绑定。
        /// </summary>
        public static WorkflowRuntimeMultipartFile FromFile(
            string bindingId,
            string filePath,
            string? mediaType = null)
        {
            if (string.IsNullOrWhiteSpace(filePath))
            {
                throw new ArgumentException("filePath cannot be empty.", nameof(filePath));
            }

            var normalizedPath = filePath.Trim();
            var normalizedMediaType = string.IsNullOrWhiteSpace(mediaType)
                ? "application/octet-stream"
                : mediaType!.Trim();
            var fileInfo = new FileInfo(normalizedPath);
            if (!fileInfo.Exists)
            {
                throw new FileNotFoundException("Upload file does not exist.", normalizedPath);
            }
            return FromStreamFactory(
                bindingId,
                () => new FileStream(
                    normalizedPath,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.Read,
                    1024 * 1024,
                    FileOptions.SequentialScan),
                Path.GetFileName(normalizedPath),
                normalizedMediaType,
                fileInfo.Length);
        }

        /// <summary>
        /// 从 stream 创建 multipart 文件绑定。
        /// </summary>
        public static WorkflowRuntimeMultipartFile FromStream(
            string bindingId,
            Stream stream,
            string fileName,
            string mediaType = "application/octet-stream")
        {
            if (stream is null)
            {
                throw new ArgumentNullException(nameof(stream));
            }

            var opened = 0;
            return FromStreamFactory(
                bindingId,
                () => Interlocked.Exchange(ref opened, 1) == 0
                    ? stream
                    : throw new InvalidOperationException(
                        "FromStream creates a single-use upload. Use FromStreamFactory for each send."),
                fileName,
                mediaType,
                stream.CanSeek ? (long?)(stream.Length - stream.Position) : null);
        }

        /// <summary>
        /// 从每次发送独立创建的 stream factory 构造文件绑定。
        /// </summary>
        public static WorkflowRuntimeMultipartFile FromStreamFactory(
            string bindingId,
            Func<Stream> streamFactory,
            string fileName,
            string mediaType = "application/octet-stream",
            long? contentLength = null)
        {
            if (streamFactory is null)
            {
                throw new ArgumentNullException(nameof(streamFactory));
            }
            return new WorkflowRuntimeMultipartFile
            {
                BindingId = bindingId,
                StreamFactory = streamFactory,
                FileName = fileName,
                MediaType = mediaType,
                ContentLength = contentLength
            };
        }

        /// <summary>
        /// 构造 HTTP 文件 content。
        /// </summary>
        internal HttpContent ToHttpContent()
        {
            Validate();
            if (ContentBytes != null)
            {
                var bytesContent = new ByteArrayContent(ContentBytes);
                bytesContent.Headers.ContentType = MediaTypeHeaderValue.Parse(MediaType);
                return bytesContent;
            }

            var stream = StreamFactory!();
            if (stream is null || !stream.CanRead)
            {
                stream?.Dispose();
                throw new InvalidOperationException("StreamFactory must return a readable stream.");
            }
            try
            {
                var streamContent = new StreamContent(stream, 1024 * 1024);
                streamContent.Headers.ContentType = MediaTypeHeaderValue.Parse(MediaType);
                long? actualLength = null;
                if (stream.CanSeek)
                {
                    actualLength = stream.Length - stream.Position;
                }
                if (ContentLength != null && actualLength != null
                    && ContentLength.Value != actualLength.Value)
                {
                    streamContent.Dispose();
                    throw new InvalidOperationException(
                        "Upload stream length changed after the request was built.");
                }
                var resolvedContentLength = actualLength ?? ContentLength;
                if (resolvedContentLength != null)
                {
                    streamContent.Headers.ContentLength = resolvedContentLength.Value;
                }
                return streamContent;
            }
            catch
            {
                stream.Dispose();
                throw;
            }
        }

        /// <summary>
        /// 校验文件绑定字段。
        /// </summary>
        internal void Validate()
        {
            if (string.IsNullOrWhiteSpace(BindingId))
            {
                throw new InvalidOperationException("BindingId cannot be empty.");
            }

            if (string.IsNullOrWhiteSpace(FileName))
            {
                throw new InvalidOperationException("FileName cannot be empty.");
            }

            if (string.IsNullOrWhiteSpace(MediaType))
            {
                throw new InvalidOperationException("MediaType cannot be empty.");
            }

            if (ContentBytes != null && ContentBytes.Length == 0)
            {
                throw new InvalidOperationException("ContentBytes cannot be empty.");
            }
            if (ContentBytes is null && StreamFactory is null)
            {
                throw new InvalidOperationException("ContentBytes or StreamFactory is required.");
            }
            if (ContentLength != null && ContentLength.Value <= 0)
            {
                throw new InvalidOperationException("ContentLength must be greater than zero.");
            }
        }
    }
}
