using Amvar.Launcher.Core.Configuration;
using Newtonsoft.Json;

namespace Amvar.Launcher.Infrastructure.Contracts;

public sealed class SettingsHeader
{
    [JsonProperty("schema_version", Required = Required.Always)] public int SchemaVersion { get; set; }
}
public sealed class LauncherSettingsDocumentV1
{
    [JsonProperty("schema_version", Required = Required.Always)] public int SchemaVersion { get; set; } = 1;
    [JsonProperty("manage_service", Required = Required.DisallowNull)] public bool ManageService { get; set; } = true;
    [JsonProperty("start_fullscreen", Required = Required.DisallowNull)] public bool StartFullscreen { get; set; }
    [JsonProperty("project_root", Required = Required.DisallowNull)] public string ProjectRoot { get; set; } = ".";
    [JsonProperty("startup_timeout_seconds", Required = Required.DisallowNull)] public int StartupTimeoutSeconds { get; set; } = 300;
    [JsonProperty("theme", Required = Required.DisallowNull)] public ThemePreference Theme { get; set; }
    [JsonProperty("window", Required = Required.DisallowNull)] public WindowPreferencesDocumentV1 Window { get; set; } = new();
    public LauncherSettings ToSettings() => new() { ManageService = ManageService, StartFullscreen = StartFullscreen, ProjectRoot = ProjectRoot,
        StartupTimeout = TimeSpan.FromSeconds(StartupTimeoutSeconds), Theme = Theme,
        Window = new(Window.Width, Window.Height, Window.Maximized) };
    public static LauncherSettingsDocumentV1 From(LauncherSettings value) => new()
    {
        ManageService = value.ManageService, StartFullscreen = value.StartFullscreen, ProjectRoot = value.ProjectRoot,
        StartupTimeoutSeconds = checked((int)value.StartupTimeout.TotalSeconds), Theme = value.Theme,
        Window = new() { Width = value.Window.Width, Height = value.Window.Height, Maximized = value.Window.Maximized }
    };
}
public sealed class WindowPreferencesDocumentV1
{
    [JsonProperty("width", Required = Required.DisallowNull)] public double Width { get; set; } = 1280;
    [JsonProperty("height", Required = Required.DisallowNull)] public double Height { get; set; } = 800;
    [JsonProperty("maximized", Required = Required.DisallowNull)] public bool Maximized { get; set; }
}
