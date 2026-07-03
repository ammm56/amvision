using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace Amvision.Workflows;

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
                new StringContent(JsonSerializer.Serialize(InputBindings, WorkflowJsonDefaults.SerializerOptions), Encoding.UTF8, "application/json"),
                "input_bindings_json");
        }

        if (ExecutionMetadata.Count > 0)
        {
            content.Add(
                new StringContent(JsonSerializer.Serialize(ExecutionMetadata, WorkflowJsonDefaults.SerializerOptions), Encoding.UTF8, "application/json"),
                "execution_metadata_json");
        }

        if (TimeoutSeconds is not null)
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
        if (TimeoutSeconds is not null && TimeoutSeconds.Value <= 0)
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
    /// 文件内容 bytes。
    /// </summary>
    public byte[] ContentBytes { get; set; } = Array.Empty<byte>();

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
        return FromBytes(
            bindingId,
            File.ReadAllBytes(normalizedPath),
            Path.GetFileName(normalizedPath),
            normalizedMediaType);
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

        using var memoryStream = new MemoryStream();
        stream.CopyTo(memoryStream);
        return FromBytes(bindingId, memoryStream.ToArray(), fileName, mediaType);
    }

    /// <summary>
    /// 构造 HTTP 文件 content。
    /// </summary>
    internal HttpContent ToHttpContent()
    {
        Validate();
        var content = new ByteArrayContent(ContentBytes);
        content.Headers.ContentType = MediaTypeHeaderValue.Parse(MediaType);
        return content;
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

        if (ContentBytes is null || ContentBytes.Length == 0)
        {
            throw new InvalidOperationException("ContentBytes cannot be empty.");
        }
    }
}
