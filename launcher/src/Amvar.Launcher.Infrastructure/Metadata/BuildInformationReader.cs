using System.Reflection;
using Amvar.Launcher.Core.Diagnostics;
using Amvar.Launcher.Infrastructure.Serialization;

namespace Amvar.Launcher.Infrastructure.Metadata;

public static class BuildInformationReader
{
    public static BuildInformation Read(Assembly assembly)
    {
        var timestamp = assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .FirstOrDefault(a => a.Key == "BuildTimestamp")?.Value;
        var version = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "0.1.0";
        var parts = version.Split('+', 2);
        return new("amvar launcher", parts[0], DateTimeOffset.TryParse(timestamp, out var date) ? date : DateTimeOffset.MinValue,
            parts.Length > 1 ? parts[1] : "unknown", "PolyForm Noncommercial 1.0.0",
            "https://github.com/ammm56/amvision", "https://amvar.io");
    }

    public static void Write(string directory, Assembly assembly) =>
        File.WriteAllText(Path.Combine(directory, "launcher-build-info.json"), LauncherJson.Write(Read(assembly)));
}
