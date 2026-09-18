using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision
{
    /// <summary>视觉服务当前状态；执行中、满载与长任务不影响 Ready。</summary>
    public sealed class ServiceStatusResponse
    {
        [JsonProperty("ready", Required = Required.Always)]
        public bool Ready { get; set; }

        [JsonProperty("state", Required = Required.Always)]
        public string State { get; set; } = string.Empty;

        [JsonProperty("instance_id", Required = Required.Always)]
        public string InstanceId { get; set; } = string.Empty;

        [JsonProperty("checked_at", Required = Required.AllowNull)]
        public string? CheckedAt { get; set; }

        /// <summary>资源数量；尚未获得可信清单时为 null，不代表零个资源。</summary>
        [JsonProperty("summary", Required = Required.AllowNull)]
        public IDictionary<string, ServiceStatusCount>? Summary { get; set; }

        [JsonProperty("blockers", Required = Required.Always)]
        public IList<ServiceStatusBlocker> Blockers { get; set; } = new List<ServiceStatusBlocker>();

        /// <summary>仅 details=true 且具有管理员权限时返回资源明细。</summary>
        [JsonProperty("resources")]
        public IList<JObject>? Resources { get; set; }
    }

    /// <summary>要求运行与已就绪的数量，不是空闲实例数量。</summary>
    public sealed class ServiceStatusCount
    {
        [JsonProperty("expected", Required = Required.Always)]
        public int Expected { get; set; }
        [JsonProperty("ready", Required = Required.Always)]
        public int Ready { get; set; }
    }

    /// <summary>尚未就绪的组件类型和稳定原因码。</summary>
    public sealed class ServiceStatusBlocker
    {
        [JsonProperty("kind", Required = Required.Always)]
        public string Kind { get; set; } = string.Empty;
        [JsonProperty("code", Required = Required.Always)]
        public string Code { get; set; } = string.Empty;
    }
}
