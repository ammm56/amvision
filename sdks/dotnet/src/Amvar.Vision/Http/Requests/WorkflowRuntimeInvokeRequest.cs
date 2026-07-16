using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision
{

    /// <summary>
    /// 描述一次 WorkflowAppRuntime invoke HTTP JSON 请求。
    /// </summary>
    public sealed class WorkflowRuntimeInvokeRequest
    {
        /// <summary>
        /// input_bindings 对象。
        /// </summary>
        public IDictionary<string, object?> InputBindings { get; } = new Dictionary<string, object?>();

        /// <summary>
        /// 是否把 InputBindings 直接写成顶层公开 input 字段。
        /// </summary>
        public bool UseDirectInputBindings { get; set; }

        /// <summary>
        /// execution_metadata 对象。
        /// </summary>
        public IDictionary<string, object?> ExecutionMetadata { get; } = new Dictionary<string, object?>();

        /// <summary>
        /// 可选 timeout_seconds。
        /// </summary>
        public int? TimeoutSeconds { get; set; }

        /// <summary>
        /// 将当前请求对象序列化为 backend-service 兼容 JSON。
        /// </summary>
        /// <returns>请求 JSON 文本。</returns>
        public string ToJson()
        {
            Validate();
            var payload = UseDirectInputBindings
                ? new Dictionary<string, object?>(InputBindings)
                : new Dictionary<string, object?>
                {
                    ["input_bindings"] = new Dictionary<string, object?>(InputBindings)
                };
            payload["execution_metadata"] = new Dictionary<string, object?>(ExecutionMetadata);
            if (TimeoutSeconds != null)
            {
                payload["timeout_seconds"] = TimeoutSeconds.Value;
            }

            return WorkflowJsonDefaults.Serialize(payload);
        }

        /// <summary>
        /// 从原始 JSON 文本解析出 invoke 请求对象。
        /// </summary>
        /// <param name="json">原始请求 JSON。</param>
        /// <returns>解析后的请求对象。</returns>
        public static WorkflowRuntimeInvokeRequest Parse(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                throw new ArgumentException("json cannot be empty.", nameof(json));
            }

            var root = JObject.Parse(json);
            if (root.Type != JTokenType.Object)
            {
                throw new InvalidOperationException("Workflow runtime invoke JSON must be an object.");
            }

            var request = new WorkflowRuntimeInvokeRequest();
            if (root.TryGetValue("input_bindings", StringComparison.OrdinalIgnoreCase, out var inputBindingsElement))
            {
                if (!(inputBindingsElement is JObject inputBindingsObject))
                {
                    throw new InvalidOperationException("input_bindings must be an object.");
                }

                foreach (var property in root.Properties())
                {
                    if (!string.Equals(property.Name, "input_bindings", StringComparison.OrdinalIgnoreCase)
                        && !string.Equals(property.Name, "execution_metadata", StringComparison.OrdinalIgnoreCase)
                        && !string.Equals(property.Name, "timeout_seconds", StringComparison.OrdinalIgnoreCase))
                    {
                        throw new InvalidOperationException(
                            "Workflow runtime invoke JSON cannot mix input_bindings with direct input fields.");
                    }
                }

                foreach (var property in inputBindingsObject.Properties())
                {
                    request.InputBindings[property.Name] = property.Value.DeepClone();
                }
            }
            else
            {
                request.UseDirectInputBindings = true;
                foreach (var property in root.Properties())
                {
                    if (string.Equals(property.Name, "execution_metadata", StringComparison.OrdinalIgnoreCase)
                        || string.Equals(property.Name, "timeout_seconds", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    request.InputBindings[property.Name] = property.Value.DeepClone();
                }
            }

            if (root.TryGetValue("execution_metadata", StringComparison.OrdinalIgnoreCase, out var executionMetadataElement))
            {
                if (!(executionMetadataElement is JObject executionMetadataObject))
                {
                    throw new InvalidOperationException("execution_metadata must be an object.");
                }

                foreach (var property in executionMetadataObject.Properties())
                {
                    request.ExecutionMetadata[property.Name] = property.Value.DeepClone();
                }
            }

            if (root.TryGetValue("timeout_seconds", StringComparison.OrdinalIgnoreCase, out var timeoutElement))
            {
                if (!TryReadPositiveInteger(timeoutElement, out var timeoutSeconds))
                {
                    throw new InvalidOperationException("timeout_seconds must be a positive integer.");
                }

                request.TimeoutSeconds = timeoutSeconds;
            }

            request.Validate();
            return request;
        }

        /// <summary>
        /// 校验当前 invoke 请求的基础字段。
        /// </summary>
        internal void Validate()
        {
            if (TimeoutSeconds != null && TimeoutSeconds.Value <= 0)
            {
                throw new InvalidOperationException("TimeoutSeconds must be greater than zero.");
            }
        }

        private static bool TryReadPositiveInteger(JToken token, out int value)
        {
            value = 0;
            if (token.Type != JTokenType.Integer)
            {
                return false;
            }

            try
            {
                value = token.Value<int>();
            }
            catch (OverflowException)
            {
                return false;
            }

            return value > 0;
        }
    }
}
