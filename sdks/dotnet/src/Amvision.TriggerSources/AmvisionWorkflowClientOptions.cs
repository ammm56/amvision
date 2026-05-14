using System;

namespace Amvision.TriggerSources;

/// <summary>
/// <see cref="AmvisionWorkflowClient" /> 使用的 backend-service HTTP 控制面参数。
/// </summary>
public sealed class AmvisionWorkflowClientOptions
{
    /// <summary>
    /// backend-service HTTP 根地址，例如 http://127.0.0.1:8000。
    /// </summary>
    public string BaseApiUrl { get; set; } = string.Empty;

    /// <summary>
    /// x-amvision-principal-id 请求头值。
    /// </summary>
    public string PrincipalId { get; set; } = string.Empty;

    /// <summary>
    /// x-amvision-project-ids 请求头值。
    /// </summary>
    public string ProjectIds { get; set; } = string.Empty;

    /// <summary>
    /// x-amvision-scopes 请求头值。
    /// </summary>
    public string Scopes { get; set; } = "workflows:read,workflows:write";

    /// <summary>
    /// HTTP 请求超时时间。
    /// </summary>
    public TimeSpan Timeout { get; set; } = TimeSpan.FromSeconds(10);

    /// <summary>
    /// 校验控制面参数是否完整。
    /// </summary>
    internal void Validate()
    {
        if (string.IsNullOrWhiteSpace(BaseApiUrl))
        {
            throw new ArgumentException("BaseApiUrl cannot be empty.", nameof(BaseApiUrl));
        }

        if (!Uri.TryCreate(BaseApiUrl.Trim(), UriKind.Absolute, out _))
        {
            throw new ArgumentException("BaseApiUrl must be an absolute URI.", nameof(BaseApiUrl));
        }

        if (string.IsNullOrWhiteSpace(PrincipalId))
        {
            throw new ArgumentException("PrincipalId cannot be empty.", nameof(PrincipalId));
        }

        if (string.IsNullOrWhiteSpace(ProjectIds))
        {
            throw new ArgumentException("ProjectIds cannot be empty.", nameof(ProjectIds));
        }

        if (string.IsNullOrWhiteSpace(Scopes))
        {
            throw new ArgumentException("Scopes cannot be empty.", nameof(Scopes));
        }

        if (Timeout <= TimeSpan.Zero)
        {
            throw new ArgumentException("Timeout must be greater than zero.", nameof(Timeout));
        }
    }
}