using Amvision.Workflows;
using System;
using Newtonsoft.Json;

namespace Amvision.Workflows.Configuration
{
/// <summary>
/// 后端 HTTP API 连接配置，对应每个 config_*.json 中的 backend 节点。
/// </summary>
internal sealed class BackendConfig
{
    /// <summary>
    /// backend-service REST API 根地址，例如 http://127.0.0.1:8000。
    /// </summary>
    [JsonProperty("base_api_url")]
    public string BaseApiUrl { get; set; } = "http://127.0.0.1:8000";

    /// <summary>
    /// 调用 REST API 使用的 access token。
    /// </summary>
    [JsonProperty("access_token")]
    public string AccessToken { get; set; } = "amvision-default-user-token";

    /// <summary>
    /// 当前 runtime 和 TriggerSource 所属 Project id。
    /// </summary>
    [JsonProperty("project_id")]
    public string ProjectId { get; set; } = "project-1";

    /// <summary>
    /// HTTP client 请求超时时间，单位为秒。
    /// </summary>
    [JsonProperty("http_timeout_seconds")]
    public int HttpTimeoutSeconds { get; set; } = 60;

    /// <summary>
    /// 校验 backend 配置是否满足当前控制台程序启动和调用要求。
    /// </summary>
    /// <param name="path">配置字段路径，用于生成清晰的错误信息。</param>
    public void Validate(string path)
    {
        ConfigValidation.RequireText(BaseApiUrl, $"{path}.base_api_url");
        ConfigValidation.RequireText(AccessToken, $"{path}.access_token");
        ConfigValidation.RequireText(ProjectId, $"{path}.project_id");
        if (HttpTimeoutSeconds <= 0)
        {
            throw new InvalidOperationException($"{path}.http_timeout_seconds must be greater than zero.");
        }
    }
}
}
