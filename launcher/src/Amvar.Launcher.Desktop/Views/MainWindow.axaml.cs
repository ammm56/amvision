using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Input;
using Avalonia.Platform;
using Avalonia.Threading;
using Amvar.Launcher.Core.Configuration;
using Amvar.Launcher.Core.Lifecycle;
using Amvar.Launcher.Desktop.Bootstrap;
using Amvar.Launcher.Desktop.Services;
using Amvar.Launcher.Desktop.ViewModels;

namespace Amvar.Launcher.Desktop.Views;

/// <summary>窗口和托盘生命周期；服务状态只由 Coordinator 决定。</summary>
public partial class MainWindow : Window
{
    private readonly LauncherComposition composition = null!;
    private readonly IClassicDesktopStyleApplicationLifetime lifetime = null!;
    private readonly LauncherViewModel model = new();
    private WebViewSession? browser;
    private TrayIcon? tray;
    private NativeMenuItem? exitMenu;
    private readonly DispatcherTimer historyTimer = new() { Interval = TimeSpan.FromMilliseconds(400) };
    private WindowState lastNonMinimizedState;
    private readonly FullscreenController fullscreen = new();
    private bool fullscreenKeyDown;
    private long lastRevision = -1, navigationId;
    private bool mayClose, exiting, initialized;
    private Window? settingsWindow, aboutWindow;
    private double restoredWidth = 1280, restoredHeight = 800;
    public MainWindow()
    {
        InitializeComponent();
        AddHandler(KeyDownEvent, (_, args) =>
        {
            if (args.Key != Key.F11 || args.KeyModifiers != KeyModifiers.None) return;
            if (!fullscreenKeyDown) ToggleFullscreen();
            fullscreenKeyDown = true; args.Handled = true;
        }, Avalonia.Interactivity.RoutingStrategies.Tunnel);
        AddHandler(KeyUpEvent, (_, args) => { if (args.Key == Key.F11) fullscreenKeyDown = false; }, Avalonia.Interactivity.RoutingStrategies.Tunnel);
        Deactivated += (_, _) => fullscreenKeyDown = false;
        if (OperatingSystem.IsWindows())
        {
            var frame = new WindowsWindowFrame(this, WindowSurface);
            Closed += (_, _) => frame.Dispose();
        }
    }
    public MainWindow(LauncherComposition composition, IClassicDesktopStyleApplicationLifetime lifetime) : this()
    {
        this.composition = composition;
        this.lifetime = lifetime;
        DataContext = model;
        historyTimer.Tick += (_, _) =>
        {
            if (!IsVisible || browser == null) return;
            BackButton.IsEnabled = !exiting && browser.View.CanGoBack;
            ForwardButton.IsEnabled = !exiting && browser.View.CanGoForward;
        };
        composition.Coordinator.Changed += OnSnapshot;
        Closing += (_, args) => { if (!mayClose) { args.Cancel = true; HideToTray(); } };
        Opened += async (_, _) => await StartAsync();
        PropertyChanged += (_, args) =>
        {
            if (args.Property == ActualThemeVariantProperty) _ = SyncThemeAsync();
            if (args.Property == WindowStateProperty)
            {
                MaximizeGlyph.Data = Avalonia.Media.Geometry.Parse(WindowState == WindowState.Maximized
                    ? "M4 1H11V8 M1 4H8V11H1Z" : "M1 1H11V11H1Z");
                if (WindowState != WindowState.Minimized) lastNonMinimizedState = WindowState;
            }
            if (args.Property == BoundsProperty && WindowState == WindowState.Normal && !fullscreen.IsFullscreen) { restoredWidth = Width; restoredHeight = Height; }
        };
    }
    private async Task StartAsync()
    {
        if (initialized) return;
        initialized = true;
        try
        {
            if (!await composition.AcquireAsync(() => Dispatcher.UIThread.Post(ShowMain))) { Shutdown(); return; }
            var preferences = composition.Settings.Current;
            ApplyTheme(preferences.Theme);
            Width = Math.Clamp(preferences.Window.Width, MinWidth, Math.Max(MinWidth, Screens.Primary?.WorkingArea.Width / RenderScaling ?? 1920));
            Height = Math.Clamp(preferences.Window.Height, MinHeight, Math.Max(MinHeight, Screens.Primary?.WorkingArea.Height / RenderScaling ?? 1080));
            if (preferences.Window.Maximized) WindowState = WindowState.Maximized;
            if (preferences.StartFullscreen) ToggleFullscreen();
            CreateTray();
            await composition.InitializeAsync();
        }
        catch (Exception ex) { composition.Log.Write("初始化失败", ex); composition.Coordinator.InitializationFailed(ex.Message); }
    }
    private void CreateTray()
    {
        using var stream = AssetLoader.Open(new Uri("avares://amvar.launcher/Assets/app.ico"));
        Icon = new WindowIcon(stream);
        var show = new NativeMenuItem("显示窗口"); show.Click += (_, _) => ShowMain();
        var about = new NativeMenuItem("关于"); about.Click += (_, _) => ShowAbout();
        var exit = exitMenu = new NativeMenuItem("退出"); exit.Click += (_, _) => RequestExit();
        var menu = new NativeMenu(); menu.Items.Add(show); menu.Items.Add(about); menu.Items.Add(new NativeMenuItemSeparator()); menu.Items.Add(exit);
        tray = new() { Icon = Icon, ToolTipText = "amvar launcher", Menu = menu, IsVisible = true };
        tray.Clicked += (_, _) => ShowMain();
        if (Application.Current != null) TrayIcon.SetIcons(Application.Current, new TrayIcons { tray });
    }
    private void OnSnapshot(LauncherSnapshot snapshot) => Dispatcher.UIThread.Post(() =>
    {
        if (snapshot.Revision <= lastRevision || mayClose) return;
        lastRevision = snapshot.Revision;
        model.Apply(snapshot);
        if (snapshot.NavigationId > navigationId)
        {
            navigationId = snapshot.NavigationId;
            try
            {
                if (browser == null)
                {
                    browser = composition.CreateBrowser();
                    browser.FullscreenRequested += () => Dispatcher.UIThread.Post(ToggleFullscreen);
                    _ = SyncThemeAsync();
                    historyTimer.Start();
                    BrowserHost.Content = browser.View;
                    browser.Completed += (success, error) =>
                    {
                        BackButton.IsEnabled = browser.View.CanGoBack;
                        ForwardButton.IsEnabled = browser.View.CanGoForward;
                        composition.Coordinator.ReportNavigation(navigationId, success, error);
                    };
                    browser.View.PropertyChanged += (_, args) =>
                    {
                        if (args.Property.Name is "CanGoBack" or "CanGoForward")
                        { BackButton.IsEnabled = browser.View.CanGoBack; ForwardButton.IsEnabled = browser.View.CanGoForward; }
                    };
                }
                // 原生 HWND 无法由 XAML 覆盖；预载阶段保留 1px 宿主，首屏就绪后再展开。
                SetBrowserPresentation(false, true);
                browser.NavigateHome();
            }
            catch (Exception ex) { composition.Coordinator.ReportNavigation(navigationId, false, ex.Message); }
        }
        else SetBrowserPresentation(model.ShowBrowser, false);
    });
    private void SetBrowserPresentation(bool ready, bool preloading)
    {
        BrowserHost.Width = ready ? double.NaN : 1;
        BrowserHost.Height = ready ? double.NaN : 1;
        BrowserHost.HorizontalAlignment = ready ? Avalonia.Layout.HorizontalAlignment.Stretch : Avalonia.Layout.HorizontalAlignment.Right;
        BrowserHost.VerticalAlignment = ready ? Avalonia.Layout.VerticalAlignment.Stretch : Avalonia.Layout.VerticalAlignment.Bottom;
        BrowserHost.IsVisible = ready || preloading;
        LoadingSurface.IsVisible = !ready;
    }
    private async Task PersistWindowAsync()
    {
        try { await composition.Settings.SaveWindowAsync(new(restoredWidth, restoredHeight, fullscreen.IsFullscreen ? fullscreen.RestoreMaximized : WindowState == WindowState.Maximized)); }
        catch (Exception ex) { composition.Log.Write("窗口尺寸保存失败", ex); }
    }
    private async void HideToTray()
    {
        if (tray == null) { RequestExit(); return; }
        settingsWindow?.Hide(); aboutWindow?.Hide(); Hide();
        await PersistWindowAsync();
    }
    private void ShowMain() { Show(); if (WindowState == WindowState.Minimized) WindowState = lastNonMinimizedState; Activate(); }
    public async void RequestExit()
    {
        if (exiting || mayClose) return;
        exiting = true;
        if (exitMenu != null) exitMenu.IsEnabled = false;
        ShowMain();
        try
        {
            if (!await composition.Coordinator.RequestExitAsync()) return;
            await PersistWindowAsync();
            Shutdown();
        }
        catch (Exception ex) { composition.Log.Write("退出窗口失败", ex); }
        finally { exiting = false; if (!mayClose && exitMenu != null) exitMenu.IsEnabled = true; }
    }
    private void Shutdown()
    {
        mayClose = true;
        composition.Coordinator.Changed -= OnSnapshot;
        settingsWindow?.Close(); aboutWindow?.Close();
        browser?.Dispose(); BrowserHost.Content = null;
        tray?.Dispose(); composition.Dispose();
        historyTimer.Stop();
        lifetime.Shutdown();
    }
    public static void ApplyTheme(ThemePreference theme)
    {
        if (Application.Current != null) Application.Current.RequestedThemeVariant = theme switch
        { ThemePreference.Light => Avalonia.Styling.ThemeVariant.Light, ThemePreference.Dark => Avalonia.Styling.ThemeVariant.Dark, _ => Avalonia.Styling.ThemeVariant.Default };
    }
    private void DragTitle(object? sender, PointerPressedEventArgs args)
    {
        if (!args.GetCurrentPoint(this).Properties.IsLeftButtonPressed) return;
        if (args.ClickCount == 2) ToggleMaximize(); else BeginMoveDrag(args);
    }
    private void ToggleMaximize() => WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
    public void ToggleFullscreen()
    {
        if (exiting) return;
        WindowState = fullscreen.Toggle(WindowState);
        TitleBar.IsVisible = !fullscreen.IsFullscreen;
        ShellLayout.RowDefinitions[0].Height = new GridLength(fullscreen.IsFullscreen ? 0 : 36);
    }
    private void MinimizeWindow(object? sender, Avalonia.Interactivity.RoutedEventArgs args) => WindowState = WindowState.Minimized;
    private void MaximizeWindow(object? sender, Avalonia.Interactivity.RoutedEventArgs args) => ToggleMaximize();
    private void HideWindow(object? sender, Avalonia.Interactivity.RoutedEventArgs args) => Close();
    private Task SyncThemeAsync() => browser?.SetThemeAsync(ActualThemeVariant == Avalonia.Styling.ThemeVariant.Dark) ?? Task.CompletedTask;
    private void GoBack(object? sender, Avalonia.Interactivity.RoutedEventArgs args) { if (!exiting) browser?.View.GoBack(); }
    private void GoForward(object? sender, Avalonia.Interactivity.RoutedEventArgs args) { if (!exiting) browser?.View.GoForward(); }
    private async void RefreshPage(object? sender, Avalonia.Interactivity.RoutedEventArgs args)
    {
        if (exiting) return;
        if (composition.Coordinator.Snapshot.Backend == BackendPhase.Connected) browser?.View.Refresh();
        else await composition.Coordinator.RetryAsync();
    }
    private async void Retry(object? sender, Avalonia.Interactivity.RoutedEventArgs args)
    {
        if (composition.Coordinator.Snapshot.Application == ApplicationPhase.ExitBlocked) RequestExit();
        else await composition.Coordinator.RetryAsync();
    }
    private void OpenLogs(object? sender, Avalonia.Interactivity.RoutedEventArgs args) => new LogWindow(composition.LogDirectory).Show(this);
    private void ShowAbout()
    {
        if (aboutWindow != null) { aboutWindow.Show(); aboutWindow.Activate(); return; }
        aboutWindow = new AboutWindow(composition.Build);
        aboutWindow.Closed += (_, _) => aboutWindow = null;
        if (IsVisible) aboutWindow.Show(this); else aboutWindow.Show();
    }
    private void OpenAbout(object? sender, Avalonia.Interactivity.RoutedEventArgs args) { HelpButton.Flyout?.Hide(); ShowAbout(); }
    private void OpenSettings(object? sender, Avalonia.Interactivity.RoutedEventArgs args)
    {
        if (exiting) return;
        if (settingsWindow != null) { settingsWindow.Show(); settingsWindow.Activate(); return; }
        var dialog = new SettingsWindow(composition.Settings, composition.SettingsFile);
        settingsWindow = dialog;
        dialog.Closed += async (_, _) =>
        {
            settingsWindow = null;
            if (dialog.Saved && composition.Coordinator.Snapshot.Application == ApplicationPhase.InitializationFailed) await composition.InitializeAsync();
        };
        dialog.Show(this);
    }
}
