using Avalonia.Controls;

namespace Amvar.Launcher.Desktop.Services;

/// <summary>窗口全屏状态，与启动偏好、服务生命周期分别管理。</summary>
public sealed class FullscreenController
{
    private WindowState restoreState = WindowState.Normal;
    public bool IsFullscreen { get; private set; }
    public WindowState Toggle(WindowState current)
    {
        if (IsFullscreen) { IsFullscreen = false; return restoreState; }
        restoreState = current == WindowState.Maximized ? WindowState.Maximized : WindowState.Normal;
        IsFullscreen = true;
        return WindowState.FullScreen;
    }
    public bool RestoreMaximized => restoreState == WindowState.Maximized;
}
