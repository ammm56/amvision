using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Amvar.Vision.Configuration;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision.Tools
{
    /// <summary>
    /// 解析 SDK bootstrap，并以不可变 generation 管理 HTTP 配置快照。
    /// </summary>
    internal static class SdkConfigurationSnapshotManager
    {
        private const string BootstrapFileName = "sdk-bootstrap.json";
        private const string ManagedDirectoryName = ".managed";
        private const string CurrentPointerFileName = "current.json";
        private const long MaximumPackageBytes = 64L * 1024 * 1024;
        private const int MaximumConfigFiles = 4096;

        internal static void ThrowIfAutomaticSyncRequiresAsync(string configDirectory)
        {
            var bootstrap = LoadBootstrap(configDirectory);
            if (bootstrap != null && bootstrap.ConfigurationSync.Enabled)
            {
                throw new InvalidOperationException(
                    "SDK configuration_sync.enabled is true. Use CreateFromConfigAsync or CreateFromConfigDirectoryAsync so HTTP configuration synchronization is not silently ignored.");
            }
        }

        internal static async Task<string> ResolveConfigurationDirectoryAsync(
            string configDirectory,
            CancellationToken cancellationToken)
        {
            var normalizedDirectory = Path.GetFullPath(
                ConfigValidation.RequireText(configDirectory, nameof(configDirectory)));
            var bootstrap = LoadBootstrap(normalizedDirectory);
            if (bootstrap == null || !bootstrap.ConfigurationSync.Enabled)
            {
                return normalizedDirectory;
            }

            try
            {
                return await SynchronizeAsync(
                    normalizedDirectory,
                    bootstrap,
                    cancellationToken).ConfigureAwait(false);
            }
            catch (Exception error) when (!(error is OperationCanceledException))
            {
                if (!bootstrap.ConfigurationSync.UseLastKnownGood)
                {
                    throw;
                }

                var managedDirectory = TryResolveCurrentManagedDirectory(normalizedDirectory);
                if (managedDirectory != null)
                {
                    Trace.TraceWarning(
                        "SDK configuration synchronization failed; using last-known-good managed snapshot. {0}",
                        error.Message);
                    return managedDirectory;
                }

                if (Directory.GetFiles(normalizedDirectory, "config*.json").Length > 0)
                {
                    Trace.TraceWarning(
                        "SDK configuration synchronization failed; using manually installed config files. {0}",
                        error.Message);
                    return normalizedDirectory;
                }

                throw new InvalidOperationException(
                    "SDK configuration synchronization failed and no valid local configuration is available.",
                    error);
            }
        }

        private static SdkBootstrapConfig? LoadBootstrap(string configDirectory)
        {
            var normalizedDirectory = Path.GetFullPath(
                ConfigValidation.RequireText(configDirectory, nameof(configDirectory)));
            var path = Path.Combine(normalizedDirectory, BootstrapFileName);
            if (!File.Exists(path))
            {
                return null;
            }

            var bootstrap = JsonConvert.DeserializeObject<SdkBootstrapConfig>(
                File.ReadAllText(path, Encoding.UTF8));
            if (bootstrap == null)
            {
                throw new InvalidOperationException($"SDK bootstrap is empty: {path}");
            }

            bootstrap.Validate(path);
            return bootstrap;
        }

        private static async Task<string> SynchronizeAsync(
            string configDirectory,
            SdkBootstrapConfig bootstrap,
            CancellationToken cancellationToken)
        {
            var currentRevision = TryReadCurrentRevision(configDirectory);
            using (var client = new HttpClient
            {
                Timeout = TimeSpan.FromSeconds(bootstrap.Backend.HttpTimeoutSeconds)
            })
            using (var request = new HttpRequestMessage(
                HttpMethod.Get,
                BuildConfigurationUri(bootstrap.Backend)))
            {
                request.Headers.Authorization = new AuthenticationHeaderValue(
                    "Bearer",
                    bootstrap.Backend.AccessToken);
                if (!string.IsNullOrWhiteSpace(currentRevision))
                {
                    request.Headers.IfNoneMatch.Add(
                        new EntityTagHeaderValue($"\"{currentRevision}\""));
                }

                using (var response = await client.SendAsync(
                    request,
                    HttpCompletionOption.ResponseHeadersRead,
                    cancellationToken).ConfigureAwait(false))
                {
                    if (response.StatusCode == HttpStatusCode.NotModified)
                    {
                        return RequireCurrentManagedDirectory(configDirectory);
                    }

                    response.EnsureSuccessStatusCode();
                    var declaredLength = response.Content.Headers.ContentLength;
                    if (declaredLength.HasValue && declaredLength.Value > MaximumPackageBytes)
                    {
                        throw new InvalidOperationException(
                            "SDK configuration package exceeds the maximum allowed size.");
                    }

                    var packageBytes = await response.Content.ReadAsByteArrayAsync()
                        .ConfigureAwait(false);
                    cancellationToken.ThrowIfCancellationRequested();
                    if (packageBytes.LongLength > MaximumPackageBytes)
                    {
                        throw new InvalidOperationException(
                            "SDK configuration package exceeds the maximum allowed size.");
                    }

                    return PublishPackage(
                        configDirectory,
                        bootstrap,
                        packageBytes,
                        ReadRequiredRevisionHeader(response));
                }
            }
        }

        private static Uri BuildConfigurationUri(SdkBootstrapBackendConfig backend)
        {
            var baseUri = new Uri(backend.BaseApiUrl.TrimEnd('/') + "/", UriKind.Absolute);
            return new Uri(baseUri, backend.ConfigurationPath.TrimStart('/'));
        }

        private static string ReadRequiredRevisionHeader(HttpResponseMessage response)
        {
            IEnumerable<string> values;
            if (!response.Headers.TryGetValues("X-AmVision-Config-Revision", out values))
            {
                throw new InvalidOperationException(
                    "SDK configuration response is missing X-AmVision-Config-Revision.");
            }

            return RequireRevision(values.FirstOrDefault(), "response revision");
        }

        private static string PublishPackage(
            string configDirectory,
            SdkBootstrapConfig bootstrap,
            byte[] packageBytes,
            string responseRevision)
        {
            var managedRoot = Path.Combine(configDirectory, ManagedDirectoryName);
            Directory.CreateDirectory(managedRoot);
            var finalDirectory = Path.Combine(managedRoot, responseRevision);
            if (!Directory.Exists(finalDirectory))
            {
                var stagingDirectory = Path.Combine(
                    managedRoot,
                    $".staging-{Guid.NewGuid():N}");
                Directory.CreateDirectory(stagingDirectory);
                try
                {
                    ExtractAndValidatePackage(
                        stagingDirectory,
                        bootstrap,
                        packageBytes,
                        responseRevision);
                    WorkflowConfigLoader.LoadDirectory(stagingDirectory);
                    Directory.Move(stagingDirectory, finalDirectory);
                }
                finally
                {
                    if (Directory.Exists(stagingDirectory))
                    {
                        Directory.Delete(stagingDirectory, true);
                    }
                }
            }

            PublishCurrentPointer(configDirectory, responseRevision);
            return finalDirectory;
        }

        private static void ExtractAndValidatePackage(
            string stagingDirectory,
            SdkBootstrapConfig bootstrap,
            byte[] packageBytes,
            string responseRevision)
        {
            using (var stream = new MemoryStream(packageBytes, false))
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Read, false))
            {
                var manifestEntry = archive.GetEntry("manifest.json");
                if (manifestEntry == null)
                {
                    throw new InvalidOperationException(
                        "SDK configuration package does not contain manifest.json.");
                }

                JObject manifest;
                using (var reader = new StreamReader(
                    manifestEntry.Open(), Encoding.UTF8, true, 4096, false))
                {
                    manifest = JObject.Parse(reader.ReadToEnd());
                }

                if (!string.Equals(
                    (string?)manifest["format_id"],
                    "amvision.sdk-config-package.v1",
                    StringComparison.Ordinal))
                {
                    throw new InvalidOperationException(
                        "SDK configuration package format_id is not supported.");
                }

                var manifestRevision = RequireRevision(
                    (string?)manifest["configuration_revision"],
                    "manifest revision");
                if (!string.Equals(
                    manifestRevision,
                    responseRevision,
                    StringComparison.Ordinal))
                {
                    throw new InvalidOperationException(
                        "SDK configuration response and manifest revisions do not match.");
                }

                var files = manifest["files"] as JArray;
                if (files == null || files.Count == 0 || files.Count > MaximumConfigFiles)
                {
                    throw new InvalidOperationException(
                        "SDK configuration manifest file count is invalid.");
                }

                var writtenNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (var item in files.OfType<JObject>())
                {
                    var path = (string?)item["path"];
                    var expectedChecksum = (string?)item["sha256"];
                    ValidateArchivePath(path);
                    var entry = archive.GetEntry(path!);
                    if (entry == null)
                    {
                        throw new InvalidOperationException(
                            $"SDK configuration package is missing {path}.");
                    }

                    byte[] content;
                    using (var input = entry.Open())
                    using (var output = new MemoryStream())
                    {
                        input.CopyTo(output);
                        content = output.ToArray();
                    }

                    if (!string.Equals(
                        Sha256Hex(content),
                        expectedChecksum,
                        StringComparison.OrdinalIgnoreCase))
                    {
                        throw new InvalidOperationException(
                            $"SDK configuration checksum failed for {path}.");
                    }

                    var fileName = Path.GetFileName(path);
                    if (!fileName.StartsWith("config", StringComparison.OrdinalIgnoreCase)
                        || !fileName.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    if (!writtenNames.Add(fileName))
                    {
                        throw new InvalidOperationException(
                            $"SDK configuration package contains duplicate file name {fileName}.");
                    }

                    var payload = JObject.Parse(Encoding.UTF8.GetString(content));
                    var backend = payload["backend"] as JObject;
                    if (backend == null)
                    {
                        throw new InvalidOperationException(
                            $"SDK configuration file {path} does not contain backend settings.");
                    }

                    backend["base_api_url"] = bootstrap.Backend.BaseApiUrl;
                    backend["access_token"] = bootstrap.Backend.AccessToken;
                    File.WriteAllText(
                        Path.Combine(stagingDirectory, fileName),
                        payload.ToString(Formatting.Indented) + Environment.NewLine,
                        new UTF8Encoding(false));
                }
            }
        }

        private static void ValidateArchivePath(string? path)
        {
            if (string.IsNullOrWhiteSpace(path)
                || Path.IsPathRooted(path)
                || path!.Contains("..")
                || path.Contains('\\'))
            {
                throw new InvalidOperationException(
                    "SDK configuration package contains an invalid file path.");
            }

            if (!path.StartsWith("Config/", StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "SDK configuration files must be located under Config/.");
            }
        }

        private static string Sha256Hex(byte[] content)
        {
            using (var algorithm = SHA256.Create())
            {
                return BitConverter.ToString(algorithm.ComputeHash(content))
                    .Replace("-", string.Empty)
                    .ToLowerInvariant();
            }
        }

        private static void PublishCurrentPointer(
            string configDirectory,
            string revision)
        {
            var managedRoot = Path.Combine(configDirectory, ManagedDirectoryName);
            var currentPath = Path.Combine(managedRoot, CurrentPointerFileName);
            var temporaryPath = currentPath + $".{Guid.NewGuid():N}.tmp";
            File.WriteAllText(
                temporaryPath,
                JsonConvert.SerializeObject(
                    new { configuration_revision = revision },
                    Formatting.Indented) + Environment.NewLine,
                new UTF8Encoding(false));
            if (File.Exists(currentPath))
            {
                File.Replace(temporaryPath, currentPath, null);
            }
            else
            {
                File.Move(temporaryPath, currentPath);
            }
        }

        private static string? TryReadCurrentRevision(string configDirectory)
        {
            var currentPath = Path.Combine(
                configDirectory,
                ManagedDirectoryName,
                CurrentPointerFileName);
            if (!File.Exists(currentPath))
            {
                return null;
            }

            var payload = JObject.Parse(File.ReadAllText(currentPath, Encoding.UTF8));
            return RequireRevision(
                (string?)payload["configuration_revision"],
                "managed current revision");
        }

        private static string RequireCurrentManagedDirectory(string configDirectory)
        {
            var current = TryResolveCurrentManagedDirectory(configDirectory);
            if (current == null)
            {
                throw new InvalidOperationException(
                    "Backend returned 304 but the SDK has no valid managed snapshot.");
            }

            return current;
        }

        private static string? TryResolveCurrentManagedDirectory(string configDirectory)
        {
            var revision = TryReadCurrentRevision(configDirectory);
            if (string.IsNullOrWhiteSpace(revision))
            {
                return null;
            }

            var path = Path.Combine(configDirectory, ManagedDirectoryName, revision);
            if (!Directory.Exists(path)
                || Directory.GetFiles(path, "config*.json").Length == 0)
            {
                return null;
            }

            return path;
        }

        private static string RequireRevision(string? value, string fieldName)
        {
            var normalized = value?.Trim();
            if (normalized == null
                || normalized.Length != 64
                || normalized.Any(character => !Uri.IsHexDigit(character)))
            {
                throw new InvalidOperationException(
                    $"SDK configuration {fieldName} is not a SHA-256 revision.");
            }

            return normalized.ToLowerInvariant();
        }
    }

    internal sealed class SdkBootstrapConfig
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonProperty("backend")]
        public SdkBootstrapBackendConfig Backend { get; set; } = new SdkBootstrapBackendConfig();

        [JsonProperty("configuration_sync")]
        public SdkBootstrapSyncConfig ConfigurationSync { get; set; } = new SdkBootstrapSyncConfig();

        internal void Validate(string path)
        {
            if (!string.Equals(
                FormatId,
                "amvision.sdk-bootstrap.v1",
                StringComparison.Ordinal))
            {
                throw new InvalidOperationException($"{path}.format_id is not supported.");
            }

            Backend.Validate($"{path}.backend");
        }
    }

    internal sealed class SdkBootstrapBackendConfig
    {
        [JsonProperty("base_api_url")]
        public string BaseApiUrl { get; set; } = string.Empty;

        [JsonProperty("configuration_path")]
        public string ConfigurationPath { get; set; } = string.Empty;

        [JsonProperty("access_token")]
        public string AccessToken { get; set; } = string.Empty;

        [JsonProperty("http_timeout_seconds")]
        public int HttpTimeoutSeconds { get; set; } = 10;

        internal void Validate(string path)
        {
            BaseApiUrl = ConfigValidation.RequireText(BaseApiUrl, $"{path}.base_api_url");
            ConfigurationPath = ConfigValidation.RequireText(
                ConfigurationPath,
                $"{path}.configuration_path");
            AccessToken = ConfigValidation.RequireText(
                AccessToken,
                $"{path}.access_token");
            Uri baseUri;
            if (!Uri.TryCreate(BaseApiUrl, UriKind.Absolute, out baseUri)
                || (baseUri.Scheme != Uri.UriSchemeHttp
                    && baseUri.Scheme != Uri.UriSchemeHttps))
            {
                throw new InvalidOperationException(
                    $"{path}.base_api_url must be an absolute HTTP or HTTPS URL.");
            }

            if (!ConfigurationPath.StartsWith("/", StringComparison.Ordinal)
                || Uri.IsWellFormedUriString(ConfigurationPath, UriKind.Absolute))
            {
                throw new InvalidOperationException(
                    $"{path}.configuration_path must be a server-relative path.");
            }

            if (HttpTimeoutSeconds <= 0)
            {
                throw new InvalidOperationException(
                    $"{path}.http_timeout_seconds must be positive.");
            }
        }
    }

    internal sealed class SdkBootstrapSyncConfig
    {
        [JsonProperty("enabled")]
        public bool Enabled { get; set; }

        [JsonProperty("use_last_known_good")]
        public bool UseLastKnownGood { get; set; } = true;
    }
}
