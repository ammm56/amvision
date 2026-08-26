using System;
using Newtonsoft.Json;

namespace Amvar.Vision.Configuration
{
    /// <summary>
    /// 同机共享内存 TriggerSource 的全局 mailbox 调用配置。
    /// </summary>
    internal sealed class TriggerSourceLocalSharedMemoryConfig
    {
        /// <summary>backend 发行实例的 data/buffers 绝对目录。</summary>
        [JsonProperty("buffers_root")]
        public string BuffersRoot { get; set; } = string.Empty;

        [JsonProperty("arena_id")]
        public string ArenaId { get; set; } = string.Empty;

        [JsonProperty("arena_path")]
        public string ArenaPath { get; set; } = string.Empty;

        [JsonProperty("allocator_path")]
        public string AllocatorPath { get; set; } = string.Empty;

        [JsonProperty("guard_path")]
        public string GuardPath { get; set; } = string.Empty;

        [JsonProperty("arena_size_bytes")]
        public long ArenaSizeBytes { get; set; }

        [JsonProperty("reader_guard_slots")]
        public int ReaderGuardSlots { get; set; }

        /// <summary>当前 TriggerSource 固定 response plan 的 generation。</summary>
        [JsonProperty("route_generation")]
        public long RouteGeneration { get; set; }

        /// <summary>默认图片 input binding。</summary>
        [JsonProperty("default_input_binding")]
        public string DefaultInputBinding { get; set; } = "request_image_ref";

        /// <summary>当前 source 允许写入的最大图片字节数。</summary>
        [JsonProperty("max_image_bytes")]
        public long MaxImageBytes { get; set; } = 1024L * 1024 * 1024;

        /// <summary>请求的相对 timeout；后端仍会按 source 权威上限裁剪。</summary>
        [JsonProperty("timeout_seconds")]
        public int TimeoutSeconds { get; set; } = 5;

        /// <summary>校验共享内存调用所需字段。</summary>
        public void Validate(string path)
        {
            BuffersRoot = ConfigValidation.RequireText(BuffersRoot, $"{path}.buffers_root");
            ArenaId = ConfigValidation.RequireText(ArenaId, $"{path}.arena_id");
            ArenaPath = ConfigValidation.RequireText(ArenaPath, $"{path}.arena_path");
            AllocatorPath = ConfigValidation.RequireText(AllocatorPath, $"{path}.allocator_path");
            GuardPath = ConfigValidation.RequireText(GuardPath, $"{path}.guard_path");
            DefaultInputBinding = ConfigValidation.RequireText(
                DefaultInputBinding,
                $"{path}.default_input_binding");
            if (RouteGeneration <= 0)
            {
                throw new InvalidOperationException($"{path}.route_generation must be greater than zero.");
            }

            if (MaxImageBytes <= 0)
            {
                throw new InvalidOperationException($"{path}.max_image_bytes must be greater than zero.");
            }

            if (TimeoutSeconds <= 0)
            {
                throw new InvalidOperationException($"{path}.timeout_seconds must be greater than zero.");
            }

            if (ArenaSizeBytes <= 0 || ReaderGuardSlots <= 0)
            {
                throw new InvalidOperationException($"{path}.arena_size_bytes and reader_guard_slots must be greater than zero.");
            }
        }
    }
}
