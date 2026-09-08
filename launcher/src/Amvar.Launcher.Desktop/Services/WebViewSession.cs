using System.Diagnostics;
using Avalonia.Controls;
using Avalonia.Platform;
using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Runtime;

namespace Amvar.Launcher.Desktop.Services;

/// <summary>负责网页生命周期与原生全屏快捷键；不执行服务脚本或网页传入的本机命令。</summary>
public sealed class WebViewSession : IDisposable
{
    private readonly ILauncherLog log;
    private CancellationTokenSource? navigation;
    private long generation;
    private bool disposed;
    private bool ready;
    private bool darkTheme;
    private IDisposable? fullscreenShortcut;
    public NativeWebView View { get; } = new();
    public event Action<bool, string?>? Completed;
    public event Action? Started;
    public event Action? FullscreenRequested;

    public WebViewSession(string userDataDirectory, string? browserDirectory, ILauncherLog logger)
    {
        log = logger;
        View.EnvironmentRequested += (_, args) =>
        {
            args.EnableDevTools = false;
            if (args is WindowsWebView2EnvironmentRequestedEventArgs windows)
            {
                windows.UserDataFolder = userDataDirectory;
                windows.BrowserExecutableFolder = browserDirectory;
                windows.ProfileName = "amvar";
                windows.Language = "zh-CN";
            }
        };
        View.NavigationStarted += OnStarting;
        View.NavigationCompleted += OnCompleted;
        View.AdapterCreated += (_, _) =>
        {
            if (OperatingSystem.IsWindows() && View.TryGetPlatformHandle() is IWindowsWebView2PlatformHandle handle)
            {
                fullscreenShortcut?.Dispose();
                fullscreenShortcut = new WindowsFullscreenShortcut(handle, () => { if (!disposed) FullscreenRequested?.Invoke(); });
            }
        };
        View.AdapterDestroyed += (_, _) => { fullscreenShortcut?.Dispose(); fullscreenShortcut = null; };
        View.NewWindowRequested += (_, args) =>
        {
            args.Handled = true;
            if (args.Request is null) return;
            if (IsLocal(args.Request)) View.Navigate(args.Request);
            else OpenExternal(args.Request);
        };
    }

    public static bool IsLocal(Uri? uri) => uri is { IsAbsoluteUri: true, Scheme: "http", Host: "127.0.0.1", Port: 5600 };

    private void OnStarting(object? sender, WebViewNavigationStartingEventArgs args)
    {
        if (args.Request is null) { args.Cancel = true; return; }
        if (args.Request.Scheme is "about" or "blob") return;
        if (!IsLocal(args.Request))
        {
            args.Cancel = true;
            OpenExternal(args.Request);
            return;
        }
        BeginNavigation();
        Started?.Invoke();
    }

    private async void OnCompleted(object? sender, WebViewNavigationCompletedEventArgs args)
    {
        if (disposed || !IsLocal(args.Request)) return;
        var current = generation;
        var token = navigation?.Token ?? CancellationToken.None;
        try
        {
            if (!args.IsSuccess) throw new InvalidOperationException("工作台连接失败，请确认视觉服务已启动。");
            var watch = Stopwatch.StartNew();
            while (watch.Elapsed < TimeSpan.FromSeconds(30))
            {
                token.ThrowIfCancellationRequested();
                var ready = await View.InvokeScript("location.origin === 'http://127.0.0.1:5600' && document.documentElement.getAttribute('data-amvision-ui-ready') === 'v1'").WaitAsync(TimeSpan.FromSeconds(5), token);
                if (current != generation || disposed) return;
                if (ready == "true")
                {
                    this.ready = true;
                    await ApplyThemeAsync(); navigation?.Cancel(); Completed?.Invoke(true, null); return;
                }
                await Task.Delay(100, token);
            }
            throw new TimeoutException("工作台首屏载入超时，请重新载入并检查前端资源。");
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
        catch (Exception ex)
        {
            log.Write("网页载入失败", ex);
            if (current == generation && !disposed) { navigation?.Cancel(); Completed?.Invoke(false, ex.Message); }
        }
    }

    private void OpenExternal(Uri uri)
    {
        if (uri.Scheme is not ("http" or "https")) return;
        try { Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true }); }
        catch (Exception ex) { log.Write("打开外部链接失败", ex); }
    }

    private void BeginNavigation()
    {
        ready = false;
        navigation?.Cancel(); navigation?.Dispose(); navigation = new();
        _ = WatchNavigationAsync(++generation, navigation.Token);
    }
    private async Task WatchNavigationAsync(long current, CancellationToken token)
    {
        try
        {
            await Task.Delay(TimeSpan.FromSeconds(45), token);
            if (!disposed && current == generation) Completed?.Invoke(false, "网页载入超时，请检查 WebView2 和视觉服务。");
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
    }
    public void NavigateHome() { BeginNavigation(); View.Navigate(ProjectInstallation.HomeUri); }
    public async Task SetThemeAsync(bool dark)
    {
        darkTheme = dark;
        if (ready && !disposed) await ApplyThemeAsync();
    }
    private async Task ApplyThemeAsync()
    {
        try
        {
            // 固定枚举与固定 origin，不接受配置中的任意脚本。
            var value = darkTheme ? "dark" : "light";
            await View.InvokeScript("if(location.origin==='http://127.0.0.1:5600'){window.dispatchEvent(new CustomEvent('amvision:launcher-theme-v1',{detail:{theme:'" + value + "'}}));}")
                .WaitAsync(TimeSpan.FromSeconds(5));
        }
        catch (Exception ex) { log.Write("同步工作台外观失败", ex); }
    }
    public void Dispose()
    {
        disposed = true;
        fullscreenShortcut?.Dispose(); fullscreenShortcut = null;
        navigation?.Cancel();
        navigation?.Dispose();
        View.NavigationStarted -= OnStarting;
        View.NavigationCompleted -= OnCompleted;
        View.Stop();
    }
}
