using System;
using System.Text.Json.Serialization;

namespace Amvision.Workflows.Net461Console.Model;

/// <summary>
/// WorkflowAppRuntime invoke 和 WorkflowRun 创建时使用的请求配置。
/// </summary>
internal sealed class InvokeConfig
{
    /// <summary>
    /// 可选图片路径；为空时走普通 JSON 调用，填写后走图片 helper 调用。
    /// </summary>
    [JsonPropertyName("image_path")]
    public string? ImagePath { get; set; }

    /// <summary>
    /// HTTP image-base64 调用写入的 input binding 名称。
    /// </summary>
    [JsonPropertyName("image_input_binding")]
    public string ImageInputBinding { get; set; } = "request_image_base64";

    /// <summary>
    /// runtime invoke 或 WorkflowRun 请求的超时时间，单位为秒。
    /// </summary>
    [JsonPropertyName("timeout_seconds")]
    public int TimeoutSeconds { get; set; } = 30;

    /// <summary>
    /// 读取事件列表时的最大条数。
    /// </summary>
    [JsonPropertyName("event_limit")]
    public int EventLimit { get; set; } = 20;

    /// <summary>
    /// 控制台输出事件预览时展示的条数。
    /// </summary>
    [JsonPropertyName("event_preview_count")]
    public int EventPreviewCount { get; set; } = 5;

    /// <summary>
    /// 写入 execution_metadata 的调用来源标识。
    /// </summary>
    [JsonPropertyName("source")]
    public string Source { get; set; } = "amvision-net461-console";

    /// <summary>
    /// 同步 invoke 场景名，写入 execution_metadata。
    /// </summary>
    [JsonPropertyName("sync_scenario")]
    public string SyncScenario { get; set; } = "sync-invoke";

    /// <summary>
    /// 异步 WorkflowRun 场景名，写入 execution_metadata。
    /// </summary>
    [JsonPropertyName("async_scenario")]
    public string AsyncScenario { get; set; } = "async-run";

    /// <summary>
    /// 是否把 input binding 直接写到请求 JSON 顶层。
    /// </summary>
    [JsonPropertyName("use_direct_input_bindings")]
    public bool UseDirectInputBindings { get; set; }

    /// <summary>
    /// 校验 invoke 配置是否满足当前调用要求。
    /// </summary>
    /// <param name="path">配置字段路径，用于生成清晰的错误信息。</param>
    public void Validate(string path)
    {
        ConfigValidation.RequireText(ImageInputBinding, $"{path}.image_input_binding");
        ConfigValidation.RequireText(Source, $"{path}.source");
        ConfigValidation.RequireText(SyncScenario, $"{path}.sync_scenario");
        ConfigValidation.RequireText(AsyncScenario, $"{path}.async_scenario");
        if (TimeoutSeconds <= 0)
        {
            throw new InvalidOperationException($"{path}.timeout_seconds must be greater than zero.");
        }

        if (EventLimit <= 0)
        {
            throw new InvalidOperationException($"{path}.event_limit must be greater than zero.");
        }

        if (EventPreviewCount <= 0)
        {
            throw new InvalidOperationException($"{path}.event_preview_count must be greater than zero.");
        }
    }
}
