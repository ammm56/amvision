using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision
{
    /// <summary>
    /// 解析统一 Workflow Trigger Result v1 及其可选二进制图片帧。
    /// </summary>
    internal static class ZeroMqTriggerResultParser
    {
        public static TriggerResult Parse(IReadOnlyList<byte[]> replyFrames)
        {
            if (replyFrames == null || replyFrames.Count == 0)
            {
                throw InvalidReply("ZeroMQ TriggerSource reply is empty.");
            }

            var json = Encoding.UTF8.GetString(replyFrames[0]);
            TriggerResult? result;
            JObject root;
            try
            {
                root = JObject.Parse(json);
                result = WorkflowJsonDefaults.Deserialize<TriggerResult>(json);
            }
            catch (JsonException exception)
            {
                throw InvalidReply("ZeroMQ TriggerSource reply is not valid JSON.", json, exception);
            }

            if (result == null)
            {
                throw InvalidReply("ZeroMQ TriggerSource reply cannot be parsed.", json);
            }
            if (!string.Equals(result.FormatId, AMVisionTriggerClient.TriggerResultFormatId, StringComparison.Ordinal))
            {
                throw InvalidReply($"Unexpected TriggerResult format_id: {result.FormatId}.", json);
            }

            result.ImageAttachments = ParseAttachments(root, replyFrames, json);
            return result;
        }

        private static IReadOnlyList<TriggerImageAttachment> ParseAttachments(
            JObject root,
            IReadOnlyList<byte[]> replyFrames,
            string rawJson)
        {
            var responsePayload = root["response_payload"] as JObject;
            var rawPayloads = responsePayload?["payloads"] as JArray;
            var rawAttachments = responsePayload?["attachments"] as JArray;
            if (rawPayloads == null || rawPayloads.Count == 0)
            {
                if (replyFrames.Count != 1)
                {
                    throw InvalidReply("JSON-only Result contains undeclared binary frames.", rawJson);
                }
                if (rawAttachments != null && rawAttachments.Count != 0)
                {
                    throw InvalidReply("Result attachments reference no physical payloads.", rawJson);
                }
                return Array.Empty<TriggerImageAttachment>();
            }

            var physicalById = new Dictionary<string, PhysicalImage>(StringComparer.Ordinal);
            var declaredFrameIndexes = new HashSet<int>();
            foreach (var token in rawPayloads)
            {
                var payload = token.ToObject<ZeroMqPhysicalPayload>();
                if (payload == null || string.IsNullOrWhiteSpace(payload.PayloadId))
                {
                    throw InvalidReply("Result physical payload is invalid.", rawJson);
                }
                if (!string.Equals(payload.DeliveryKind, "zeromq-frame", StringComparison.Ordinal))
                {
                    throw InvalidReply("ZeroMQ Result contains a non-frame physical payload.", rawJson);
                }
                if (string.IsNullOrWhiteSpace(payload.MediaType)
                    || payload.ContentLength <= 0
                    || string.IsNullOrWhiteSpace(payload.ChecksumAlgorithm)
                    || string.IsNullOrWhiteSpace(payload.Checksum))
                {
                    throw InvalidReply("Result physical payload metadata is incomplete.", rawJson);
                }
                if (payload.FrameIndex <= 0 || payload.FrameIndex >= replyFrames.Count)
                {
                    throw InvalidReply("Result physical payload frame_index is out of range.", rawJson);
                }
                if (!declaredFrameIndexes.Add(payload.FrameIndex))
                {
                    throw InvalidReply("Multiple physical payloads declare the same frame_index.", rawJson);
                }
                var content = replyFrames[payload.FrameIndex];
                if (content.LongLength != payload.ContentLength)
                {
                    throw InvalidReply("Result image frame length does not match the manifest.", rawJson);
                }
                ValidateChecksum(payload, content, rawJson);
                if (physicalById.ContainsKey(payload.PayloadId))
                {
                    throw InvalidReply("Result contains duplicate payload_id values.", rawJson);
                }
                physicalById.Add(payload.PayloadId, new PhysicalImage(payload, content));
            }
            if (declaredFrameIndexes.Count != replyFrames.Count - 1)
            {
                throw InvalidReply("Result contains undeclared binary frames.", rawJson);
            }
            if (rawAttachments == null || rawAttachments.Count == 0)
            {
                throw InvalidReply("Result physical payloads have no logical attachments.", rawJson);
            }

            var attachments = new List<TriggerImageAttachment>();
            var referencedPayloadIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (var token in rawAttachments ?? new JArray())
            {
                var logical = token.ToObject<ZeroMqLogicalAttachment>();
                if (logical == null
                    || string.IsNullOrWhiteSpace(logical.AttachmentId)
                    || string.IsNullOrWhiteSpace(logical.BindingId)
                    || logical.ItemIndex < 0
                    || !physicalById.TryGetValue(logical.PayloadId, out var physical))
                {
                    throw InvalidReply("Result attachment references an unknown payload_id.", rawJson);
                }
                referencedPayloadIds.Add(logical.PayloadId);
                attachments.Add(new TriggerImageAttachment
                {
                    AttachmentId = logical.AttachmentId,
                    BindingId = logical.BindingId,
                    ItemIndex = logical.ItemIndex,
                    PayloadId = logical.PayloadId,
                    MediaType = physical.Payload.MediaType,
                    Content = physical.Content,
                    Width = physical.Payload.Width,
                    Height = physical.Payload.Height,
                    Shape = physical.Payload.Shape,
                    DType = physical.Payload.DType,
                    Layout = physical.Payload.Layout,
                    PixelFormat = physical.Payload.PixelFormat
                });
            }
            if (referencedPayloadIds.Count != physicalById.Count)
            {
                throw InvalidReply("Result contains an unreferenced physical payload.", rawJson);
            }
            return attachments;
        }

        private static void ValidateChecksum(ZeroMqPhysicalPayload payload, byte[] content, string rawJson)
        {
            string actual;
            if (string.Equals(payload.ChecksumAlgorithm, "crc32", StringComparison.Ordinal))
            {
                actual = ComputeCrc32(content).ToString("x8", CultureInfo.InvariantCulture);
            }
            else if (string.Equals(payload.ChecksumAlgorithm, "sha256", StringComparison.Ordinal))
            {
                using (var sha256 = SHA256.Create())
                {
                    actual = string.Concat(sha256.ComputeHash(content).Select(value => value.ToString("x2", CultureInfo.InvariantCulture)));
                }
            }
            else
            {
                throw InvalidReply("Result image frame uses an unsupported checksum algorithm.", rawJson);
            }
            if (!string.Equals(actual, payload.Checksum, StringComparison.OrdinalIgnoreCase))
            {
                throw InvalidReply("Result image frame checksum does not match the manifest.", rawJson);
            }
        }

        private static uint ComputeCrc32(byte[] content)
        {
            uint crc = 0xffffffff;
            foreach (var value in content)
            {
                crc ^= value;
                for (var bit = 0; bit < 8; bit++)
                {
                    crc = (crc >> 1) ^ ((crc & 1) == 0 ? 0u : 0xedb88320u);
                }
            }
            return ~crc;
        }

        private static AMVisionTriggerException InvalidReply(
            string message,
            string? rawJson = null,
            Exception? innerException = null)
        {
            return new AMVisionTriggerException("invalid_reply", message, null, innerException, rawJson);
        }

        private sealed class PhysicalImage
        {
            public PhysicalImage(ZeroMqPhysicalPayload payload, byte[] content)
            {
                Payload = payload;
                Content = content;
            }

            public ZeroMqPhysicalPayload Payload { get; }
            public byte[] Content { get; }
        }

        private sealed class ZeroMqPhysicalPayload
        {
            [JsonProperty("payload_id")]
            public string PayloadId { get; set; } = string.Empty;

            [JsonProperty("delivery_kind")]
            public string DeliveryKind { get; set; } = string.Empty;

            [JsonProperty("frame_index")]
            public int FrameIndex { get; set; }

            [JsonProperty("media_type")]
            public string MediaType { get; set; } = string.Empty;

            [JsonProperty("content_length")]
            public long ContentLength { get; set; }

            [JsonProperty("checksum_algorithm")]
            public string ChecksumAlgorithm { get; set; } = string.Empty;

            [JsonProperty("checksum")]
            public string Checksum { get; set; } = string.Empty;

            [JsonProperty("width")]
            public int? Width { get; set; }

            [JsonProperty("height")]
            public int? Height { get; set; }

            [JsonProperty("shape")]
            public List<int> Shape { get; set; } = new List<int>();

            [JsonProperty("dtype")]
            public string? DType { get; set; }

            [JsonProperty("layout")]
            public string? Layout { get; set; }

            [JsonProperty("pixel_format")]
            public string? PixelFormat { get; set; }
        }

        private sealed class ZeroMqLogicalAttachment
        {
            [JsonProperty("attachment_id")]
            public string AttachmentId { get; set; } = string.Empty;

            [JsonProperty("binding_id")]
            public string BindingId { get; set; } = string.Empty;

            [JsonProperty("item_index")]
            public int ItemIndex { get; set; }

            [JsonProperty("payload_id")]
            public string PayloadId { get; set; } = string.Empty;
        }
    }
}
