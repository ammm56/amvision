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
    /// Authorization Bearer token 明文。
    /// </summary>
    public string AccessToken { get; set; } = string.Empty;

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

        if (string.IsNullOrWhiteSpace(AccessToken))
        {
            throw new ArgumentException("AccessToken cannot be empty.", nameof(AccessToken));
        }

        if (Timeout <= TimeSpan.Zero)
        {
            throw new ArgumentException("Timeout must be greater than zero.", nameof(Timeout));
        }
    }
}