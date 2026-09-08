using System.Reflection;
using System.Security.Cryptography;
using Newtonsoft.Json;
using Amvar.Launcher.Infrastructure.Serialization;

namespace Amvar.Launcher.Infrastructure.Metadata;

public sealed class LauncherReleaseManifest
{
    [JsonProperty("format_id")] public string FormatId { get; } = "amvar.launcher-release.v2";
    [JsonProperty("rid")] public string Rid { get; } = "win-x64";
    [JsonProperty("self_contained")] public bool SelfContained { get; } = true;
    [JsonProperty("webview_version")] public required string WebViewVersion { get; init; }
    [JsonProperty("files")] public required List<LauncherReleaseFile> Files { get; init; }
}
public sealed record class LauncherReleaseFile(
    [property: JsonProperty("path")] string Path,
    [property: JsonProperty("sha256")] string Sha256);

public static class ReleaseManifestWriter
{
    public static void Write(string root, Assembly assembly)
    {
        BuildInformationReader.Write(root, assembly);
        var installation = Directory.GetParent(Path.TrimEndingDirectorySeparator(root))!.FullName;
        var webview = Path.Combine(root, "tools", "webview2", "win-x64", "msedgewebview2.exe");
        if (!File.Exists(webview) || !File.Exists(Path.Combine(root, "coreclr.dll")))
            throw new IOException("发行包必须包含自带 .NET 和 Fixed Version WebView2。");
        var files = Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories)
            .Append(Path.Combine(installation, "amvar.launcher.exe"))
            .Select(path => (path, relative: Path.GetRelativePath(installation, path).Replace('\\', '/')))
            .Where(item => item.relative != "launcher/launcher-release.json" && !item.relative.StartsWith("launcher/config/") &&
                !item.relative.StartsWith("launcher/data/") && !item.relative.StartsWith("launcher/logs/"))
            .OrderBy(item => item.relative, StringComparer.Ordinal)
            .Select(item => { using var stream = File.OpenRead(item.path); return new LauncherReleaseFile(item.relative, Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant()); }).ToList();
        var manifest = new LauncherReleaseManifest
        {
            WebViewVersion = System.Diagnostics.FileVersionInfo.GetVersionInfo(webview).FileVersion ?? "unknown",
            Files = files
        };
        File.WriteAllText(Path.Combine(root, "launcher-release.json"), LauncherJson.Write(manifest));
    }
}
