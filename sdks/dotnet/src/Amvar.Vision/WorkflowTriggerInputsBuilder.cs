using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Text;
using Newtonsoft.Json;

namespace Amvar.Vision
{
    /// <summary>
    /// 一次高性能 Trigger 调用的 JSON/文本事件 payload。
    /// 图片由 ZeroMQ binary frame 或 LocalBuffer 图片参数单独提供。
    /// </summary>
    public sealed class WorkflowTriggerInputs
    {
        private readonly IReadOnlyDictionary<string, object?> payload;

        internal WorkflowTriggerInputs(IDictionary<string, object?> payload)
        {
            this.payload = new ReadOnlyDictionary<string, object?>(
                new Dictionary<string, object?>(payload, StringComparer.Ordinal));
        }

        /// <summary>按 TriggerSource mapping source 路径组织的事件 payload。</summary>
        public IReadOnlyDictionary<string, object?> Payload => payload;

        /// <summary>把输入复制到一个新事件 payload；不会覆盖已有字段。</summary>
        public void CopyTo(IDictionary<string, object?> destination)
        {
            if (destination is null) throw new ArgumentNullException(nameof(destination));
            foreach (var pair in payload)
            {
                if (destination.ContainsKey(pair.Key))
                {
                    throw new InvalidOperationException(
                        "Trigger payload field was already supplied: " + pair.Key);
                }
                destination[pair.Key] = pair.Value;
            }
        }
    }

    /// <summary>
    /// 依据固定 App Contract 和 TriggerSource mapping 构造高性能 Trigger 输入。
    /// 只提供 value.v1 和 text.v1；Base64 图片、文件和文件列表只能使用 HTTP Runtime。
    /// </summary>
    public sealed class WorkflowTriggerInputsBuilder
    {
        private readonly WorkflowAppContract contract;
        private readonly Dictionary<string, string> sourcePaths;
        private readonly Dictionary<string, object?> payload =
            new Dictionary<string, object?>(StringComparer.Ordinal);
        private readonly HashSet<string> suppliedBindingIds =
            new HashSet<string>(StringComparer.Ordinal);

        /// <summary>使用固定 App Contract 和 binding 到 payload source path 的映射创建 Builder。</summary>
        public WorkflowTriggerInputsBuilder(
            WorkflowAppContract contract,
            IDictionary<string, string> inputBindingSourcePaths)
        {
            this.contract = contract ?? throw new ArgumentNullException(nameof(contract));
            if (inputBindingSourcePaths is null)
            {
                throw new ArgumentNullException(nameof(inputBindingSourcePaths));
            }
            contract.Validate(nameof(contract));
            sourcePaths = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var pair in inputBindingSourcePaths)
            {
                var bindingId = RequireText(pair.Key, "bindingId");
                var sourcePath = NormalizeSourcePath(pair.Value);
                if (!contract.Inputs.Any(input => string.Equals(
                    input.BindingId,
                    bindingId,
                    StringComparison.Ordinal)))
                {
                    throw new InvalidOperationException(
                        "Unknown Workflow input binding: " + bindingId);
                }
                sourcePaths.Add(bindingId, sourcePath);
            }
        }

        /// <summary>增加 value.v1 JSON 输入。</summary>
        public WorkflowTriggerInputsBuilder AddJson(string bindingId, object? value)
        {
            var normalizedBindingId = RequireMappedBinding(bindingId, "value.v1");
            var bindingPayload = new Dictionary<string, object?> { ["value"] = value };
            ValidateInlineSize(normalizedBindingId, bindingPayload);
            AddMappedPayload(normalizedBindingId, bindingPayload);
            suppliedBindingIds.Add(normalizedBindingId);
            return this;
        }

        /// <summary>增加 text.v1 文本输入。</summary>
        public WorkflowTriggerInputsBuilder AddText(
            string bindingId,
            string text,
            string mediaType = "text/plain",
            string charset = "utf-8")
        {
            if (text is null) throw new ArgumentNullException(nameof(text));
            var normalizedBindingId = RequireMappedBinding(bindingId, "text.v1");
            var input = FindContractInput(normalizedBindingId);
            ValidateMediaType(input, mediaType);
            var normalizedCharset = RequireText(charset, nameof(charset));
            if (!string.IsNullOrWhiteSpace(input.Charset)
                && !string.Equals(input.Charset, normalizedCharset, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    "Charset is rejected by the published App Contract.");
            }
            var bindingPayload = new Dictionary<string, object?>
            {
                ["text"] = text,
                ["media_type"] = RequireText(mediaType, nameof(mediaType)),
                ["charset"] = normalizedCharset
            };
            ValidateInlineSize(normalizedBindingId, bindingPayload);
            AddMappedPayload(normalizedBindingId, bindingPayload);
            suppliedBindingIds.Add(normalizedBindingId);
            return this;
        }

        /// <summary>生成可复用于一次 Trigger 调用的输入对象。</summary>
        public WorkflowTriggerInputs Build()
        {
            return new WorkflowTriggerInputs(payload);
        }

        private string RequireMappedBinding(string bindingId, string payloadTypeId)
        {
            var normalizedBindingId = RequireText(bindingId, "bindingId");
            var input = FindContractInput(normalizedBindingId);
            if (!string.Equals(input.PayloadTypeId, payloadTypeId, StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "Workflow input payload type mismatch for " + normalizedBindingId + ".");
            }
            if (!sourcePaths.ContainsKey(normalizedBindingId))
            {
                throw new InvalidOperationException(
                    "Workflow input is not source-mapped by this TriggerSource: "
                    + normalizedBindingId);
            }
            if (suppliedBindingIds.Contains(normalizedBindingId))
            {
                throw new InvalidOperationException(
                    "Workflow Trigger input was already supplied: " + normalizedBindingId);
            }
            return normalizedBindingId;
        }

        private WorkflowAppContractInput FindContractInput(string bindingId)
        {
            var input = contract.Inputs.FirstOrDefault(item => string.Equals(
                item.BindingId,
                bindingId,
                StringComparison.Ordinal));
            return input ?? throw new InvalidOperationException(
                "Unknown Workflow input binding: " + bindingId);
        }

        private void AddMappedPayload(string bindingId, object? value)
        {
            var segments = sourcePaths[bindingId].Split('.').Skip(1).ToArray();
            IDictionary<string, object?> current = payload;
            for (var index = 0; index < segments.Length - 1; index++)
            {
                var segment = segments[index];
                if (!current.TryGetValue(segment, out var existing))
                {
                    var nested = new Dictionary<string, object?>(StringComparer.Ordinal);
                    current[segment] = nested;
                    current = nested;
                    continue;
                }
                if (!(existing is IDictionary<string, object?> existingObject))
                {
                    throw new InvalidOperationException(
                        "Trigger mapping source paths overlap at payload." + segment);
                }
                current = existingObject;
            }
            var leaf = segments[segments.Length - 1];
            if (current.ContainsKey(leaf))
            {
                throw new InvalidOperationException(
                    "Trigger mapping source paths resolve to the same payload field.");
            }
            current[leaf] = value;
        }

        private void ValidateInlineSize(string bindingId, object value)
        {
            var input = FindContractInput(bindingId);
            if (input.MaxInlineBytes is null) return;
            var encodedLength = Encoding.UTF8.GetByteCount(
                JsonConvert.SerializeObject(value, Formatting.None));
            if (encodedLength > input.MaxInlineBytes.Value)
            {
                throw new InvalidOperationException(
                    "Inline value exceeds the published App Contract.");
            }
        }

        private static void ValidateMediaType(
            WorkflowAppContractInput input,
            string mediaType)
        {
            if (input.AllowedMediaTypes.Count == 0) return;
            var normalized = RequireText(mediaType, nameof(mediaType)).ToLowerInvariant();
            var accepted = input.AllowedMediaTypes.Any(pattern =>
            {
                var rule = (pattern ?? string.Empty).Trim().ToLowerInvariant();
                return rule.EndsWith("/*", StringComparison.Ordinal)
                    ? normalized.StartsWith(
                        rule.Substring(0, rule.Length - 1),
                        StringComparison.Ordinal)
                    : normalized == rule;
            });
            if (!accepted)
            {
                throw new InvalidOperationException(
                    "Media type is rejected by the published App Contract.");
            }
        }

        private static string NormalizeSourcePath(string value)
        {
            var normalized = RequireText(value, "sourcePath");
            var segments = normalized.Split('.');
            if (segments.Length < 2
                || !string.Equals(segments[0], "payload", StringComparison.Ordinal)
                || segments.Any(string.IsNullOrWhiteSpace))
            {
                throw new InvalidOperationException(
                    "Trigger input source path must be a dotted payload field path.");
            }
            return normalized;
        }

        private static string RequireText(string value, string parameterName)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                throw new ArgumentException(
                    parameterName + " cannot be empty.",
                    parameterName);
            }
            return value.Trim();
        }
    }
}
