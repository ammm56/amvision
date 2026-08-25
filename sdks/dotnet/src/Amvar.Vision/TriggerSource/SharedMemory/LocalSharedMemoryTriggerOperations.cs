using System;
using System.Collections.Generic;
using System.Drawing;
using Amvar.Vision.Configuration;
using Amvar.Vision.SharedMemory;
using Amvar.Vision.Tools;

namespace Amvar.Vision.TriggerSource.SharedMemory
{
    /// <summary>
    /// 按 SDK 配置包复用同机共享内存 Trigger client。
    /// </summary>
    internal sealed class LocalSharedMemoryTriggerOperations : IDisposable
    {
        private readonly object clientSyncRoot = new object();
        private readonly WorkflowConfigurationCatalog catalog;
        private readonly Dictionary<string, SharedMemoryTriggerClient> clients =
            new Dictionary<string, SharedMemoryTriggerClient>(StringComparer.OrdinalIgnoreCase);
        private bool disposed;

        internal LocalSharedMemoryTriggerOperations(WorkflowConfigurationCatalog catalog)
        {
            this.catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
        }

        internal SharedMemoryTriggerResult InvokeImageBytes(
            string triggerSourceName,
            byte[] imageBytes,
            string mediaType,
            SharedMemoryTriggerRequest? request)
        {
            var configured = RequireConfiguredSource(triggerSourceName);
            return GetClient(configured).InvokeImageBytes(
                imageBytes,
                mediaType,
                ApplyDefaults(request, configured));
        }

        internal SharedMemoryTriggerResult InvokeBgr24(
            string triggerSourceName,
            byte[] bgr24Bytes,
            int width,
            int height,
            int? rowStride,
            SharedMemoryTriggerRequest? request)
        {
            var configured = RequireConfiguredSource(triggerSourceName);
            var normalizedRequest = ApplyDefaults(request, configured);
            return rowStride.HasValue
                ? GetClient(configured).InvokeBgr24(
                    bgr24Bytes,
                    width,
                    height,
                    rowStride.Value,
                    normalizedRequest)
                : GetClient(configured).InvokeBgr24(
                    bgr24Bytes,
                    width,
                    height,
                    normalizedRequest);
        }

        internal SharedMemoryTriggerResult InvokeBgr24(
            string triggerSourceName,
            int width,
            int height,
            SharedMemoryTriggerBufferWriter fill,
            SharedMemoryTriggerRequest? request)
        {
            var configured = RequireConfiguredSource(triggerSourceName);
            return GetClient(configured).InvokeBgr24(
                width,
                height,
                fill,
                ApplyDefaults(request, configured));
        }

        internal SharedMemoryTriggerResult InvokeMono8(
            string triggerSourceName,
            byte[] mono8Bytes,
            int width,
            int height,
            int rowStride,
            SharedMemoryTriggerRequest? request)
        {
            var configured = RequireConfiguredSource(triggerSourceName);
            return GetClient(configured).InvokeMono8(
                mono8Bytes,
                width,
                height,
                rowStride,
                ApplyDefaults(request, configured));
        }

        internal SharedMemoryTriggerResult InvokeBitmap(
            string triggerSourceName,
            Bitmap bitmap,
            SharedMemoryTriggerRequest? request)
        {
            var configured = RequireConfiguredSource(triggerSourceName);
            return GetClient(configured).InvokeBitmap(
                bitmap,
                ApplyDefaults(request, configured));
        }

        internal SharedMemoryTriggerResult InvokeImageFromFile(
            string triggerSourceName,
            string imagePath,
            string? mediaType,
            SharedMemoryTriggerRequest? request)
        {
            var configured = RequireConfiguredSource(triggerSourceName);
            var fullPath = ConfiguredPathResolver.ResolveExistingFile(
                imagePath,
                configured.SourceFile,
                "Shared-memory image file does not exist.");
            return GetClient(configured).InvokeImageFromFile(
                fullPath,
                mediaType,
                ApplyDefaults(request, configured));
        }

        internal SharedMemoryTriggerResult InvokeImageBase64(
            string triggerSourceName,
            string imageBase64,
            string? mediaType,
            SharedMemoryTriggerRequest? request)
        {
            var configured = RequireConfiguredSource(triggerSourceName);
            return GetClient(configured).InvokeImageBase64(
                imageBase64,
                mediaType,
                ApplyDefaults(request, configured));
        }

        public void Dispose()
        {
            lock (clientSyncRoot)
            {
                if (disposed)
                {
                    return;
                }

                foreach (var client in clients.Values)
                {
                    client.Dispose();
                }

                clients.Clear();
                disposed = true;
            }
        }

        private ConfiguredTriggerSource RequireConfiguredSource(string triggerSourceName)
        {
            var configured = catalog.GetTriggerSource(triggerSourceName);
            if (!string.Equals(
                configured.TriggerSource.TriggerKind,
                "local-shared-memory",
                StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    $"TriggerSource {configured.TriggerSource.TriggerSourceId} is not local-shared-memory.");
            }

            return configured;
        }

        private SharedMemoryTriggerClient GetClient(ConfiguredTriggerSource configured)
        {
            lock (clientSyncRoot)
            {
                if (disposed)
                {
                    throw new ObjectDisposedException(nameof(LocalSharedMemoryTriggerOperations));
                }

                var key = configured.TriggerSource.Name;
                if (!clients.TryGetValue(key, out var client))
                {
                    var local = configured.TriggerSource.LocalSharedMemory;
                    client = new SharedMemoryTriggerClient(new SharedMemoryTriggerClientOptions
                    {
                        BuffersRoot = ConfiguredPathResolver.ResolvePath(
                            local.BuffersRoot,
                            configured.SourceFile),
                        TriggerSourceId = configured.TriggerSource.TriggerSourceId,
                        RouteGeneration = local.RouteGeneration,
                        DefaultInputBinding = local.DefaultInputBinding,
                        MaxImageBytes = local.MaxImageBytes,
                        Timeout = TimeSpan.FromSeconds(local.TimeoutSeconds)
                    });
                    clients[key] = client;
                }

                return client;
            }
        }

        private static SharedMemoryTriggerRequest ApplyDefaults(
            SharedMemoryTriggerRequest? request,
            ConfiguredTriggerSource configured)
        {
            var normalized = request ?? new SharedMemoryTriggerRequest();
            if (string.IsNullOrWhiteSpace(normalized.InputBinding))
            {
                normalized.InputBinding = configured.TriggerSource.LocalSharedMemory.DefaultInputBinding;
            }

            normalized.Metadata["trigger_source_name"] = configured.TriggerSource.Name;
            normalized.Metadata["runtime_name"] = configured.Runtime.Name;
            if (!normalized.Payload.ContainsKey("request_id"))
            {
                normalized.Payload["request_id"] = normalized.EventId ?? $"request-{Guid.NewGuid():N}";
            }

            return normalized;
        }
    }
}
