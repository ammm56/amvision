namespace Amvar.Launcher.Core.Configuration;

/// <summary>可持久化配置；运行中的会话使用初始化时的不可变副本。</summary>
public sealed record class LauncherSettings
{
    public bool ManageService { get; init; } = true;
    public bool StartFullscreen { get; init; }
    public string ProjectRoot { get; init; } = ".";
    public TimeSpan StartupTimeout { get; init; } = TimeSpan.FromSeconds(300);
    public ThemePreference Theme { get; init; } = ThemePreference.System;
    public WindowPreferences Window { get; init; } = new();

    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(ProjectRoot)) throw new ArgumentException("项目目录不能为空。");
        if (StartupTimeout < TimeSpan.FromSeconds(5) || StartupTimeout > TimeSpan.FromHours(24))
            throw new ArgumentException("启动等待时间必须为 5–86400 秒。");
        if (!Enum.IsDefined(Theme)) throw new ArgumentException("外观设置无效。");
        if (!double.IsFinite(Window.Width) || !double.IsFinite(Window.Height) ||
            Window.Width < 320 || Window.Height < 240 || Window.Width > 16384 || Window.Height > 16384)
            throw new ArgumentException("窗口尺寸无效。");
    }
}
public enum ThemePreference { System, Light, Dark }
public sealed record class WindowPreferences(double Width = 1280, double Height = 800, bool Maximized = false);
public enum SettingsLoadKind { Missing, Valid, Corrupt, UnsupportedVersion }
public sealed record class SettingsLoadResult(SettingsLoadKind Kind, LauncherSettings Settings, string? Error = null)
{
    public bool CanPersist => Kind is SettingsLoadKind.Missing or SettingsLoadKind.Valid;
}
