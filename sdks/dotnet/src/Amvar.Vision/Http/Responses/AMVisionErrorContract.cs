using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision
{
    /// <summary>
    /// backend-service 公开错误对象。
    /// </summary>
    public sealed class AMVisionErrorContract
    {
        /// <summary>稳定错误码。</summary>
        [JsonProperty("code")]
        public string Code { get; set; } = string.Empty;

        /// <summary>可直接显示的错误摘要。</summary>
        [JsonProperty("message")]
        public string Message { get; set; } = string.Empty;

        /// <summary>结构化错误详情。</summary>
        [JsonProperty("details")]
        public IDictionary<string, JToken> Details { get; set; }
            = new Dictionary<string, JToken>();
    }
}
