using System.Text.Json.Serialization;

namespace Amvision.Workflows.Net461Console.Model;

/// <summary>
/// runtime 调用完成后的清理策略配置。
/// </summary>
internal sealed class CleanupConfig
{
    /// <summary>
    /// 调用流程结束后是否停止 runtime；默认 false，避免误停现场常驻服务。
    /// </summary>
    [JsonPropertyName("stop_at_end")]
    public bool StopAtEnd { get; set; }

    /// <summary>
    /// 当 runtime 由本程序创建时，结束后是否删除该 runtime。
    /// </summary>
    [JsonPropertyName("delete_created_runtime")]
    public bool DeleteCreatedRuntime { get; set; }
}
