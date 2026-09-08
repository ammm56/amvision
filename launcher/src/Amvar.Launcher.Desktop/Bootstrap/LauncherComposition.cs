using System.Reflection;
using Amvar.Launcher.Core.Application;
using Amvar.Launcher.Core.Configuration;
using Amvar.Launcher.Core.Diagnostics;
using Amvar.Launcher.Infrastructure.Configuration;
using Amvar.Launcher.Infrastructure.Diagnostics;
using Amvar.Launcher.Infrastructure.Http;
using Amvar.Launcher.Infrastructure.Metadata;
using Amvar.Launcher.Infrastructure.Processes;
using Amvar.Launcher.Infrastructure.Runtime;
using Amvar.Launcher.Desktop.Services;

namespace Amvar.Launcher.Desktop.Bootstrap;

/// <summary>唯一 Infrastructure 组合入口。</summary>
public sealed class LauncherComposition : IDisposable
{
    private readonly LauncherPaths paths = new(AppContext.BaseDirectory);
    private readonly HttpServiceProbe probe = new();
    private readonly FullStackController stack;
    private SingleInstanceLease? instance;
    public SettingsService Settings { get; }
    public FileLauncherLog Log { get; }
    public LauncherCoordinator Coordinator { get; }
    public BuildInformation Build { get; } = BuildInformationReader.Read(Assembly.GetExecutingAssembly());
    public string LogDirectory => paths.LogDirectory;
    public string SettingsFile => paths.SettingsFile;
    public LauncherComposition()
    {
        Log = new(paths.LogDirectory);
        Settings = new(new JsonSettingsStore(paths.SettingsFile));
        stack = new(Path.Combine(paths.DataDirectory, "requests"), Log);
        Coordinator = new(new BackendSessionController(probe, stack, TimeProvider.System), Log);
    }
    public async Task<bool> AcquireAsync(Action activate)
    {
        await Settings.LoadAsync();
        instance = await SingleInstanceLease.AcquireAsync(paths.DataDirectory,
            paths.ResolveInstallation(Settings.Current.ProjectRoot).RootDirectory);
        instance?.Listen(activate);
        return instance != null;
    }
    public Task InitializeAsync()
    {
        if (Settings.Loaded is { CanPersist: false } invalid)
        { Coordinator.InitializationFailed(invalid.Error ?? "配置文件无效。"); return Task.CompletedTask; }
        return Coordinator.InitializeAsync(Settings.Current, paths.ResolveInstallation(Settings.Current.ProjectRoot));
    }
    public WebViewSession CreateBrowser()
    {
        Directory.CreateDirectory(paths.WebViewDirectory);
        var fixedDirectory = File.Exists(Path.Combine(paths.FixedWebViewDirectory, "msedgewebview2.exe"))
            ? paths.FixedWebViewDirectory : null;
        return new(paths.WebViewDirectory, fixedDirectory, Log);
    }
    public static void WriteBuildInfo() => BuildInformationReader.Write(AppContext.BaseDirectory, Assembly.GetExecutingAssembly());
    public static void WriteReleaseManifest() => ReleaseManifestWriter.Write(AppContext.BaseDirectory, Assembly.GetExecutingAssembly());
    public void Dispose() { instance?.Dispose(); stack.Dispose(); probe.Dispose(); }
}
