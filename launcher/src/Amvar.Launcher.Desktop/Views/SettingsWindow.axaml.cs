using Avalonia.Controls;
using Avalonia.Interactivity;
using Amvar.Launcher.Core.Application;
using Amvar.Launcher.Core.Configuration;

namespace Amvar.Launcher.Desktop.Views;

public partial class SettingsWindow : Window
{
    private readonly SettingsService service = null!;
    public SettingsWindow() => InitializeComponent();
    public bool Saved { get; private set; }
    private bool saving;
    public SettingsWindow(SettingsService service, string path) : this()
    {
        this.service = service;
        var settings = service.Current;
        ManageService.IsChecked = settings.ManageService;
        StartFullscreen.IsChecked = settings.StartFullscreen;
        ProjectRoot.Text = settings.ProjectRoot;
        Timeout.Value = (decimal)settings.StartupTimeout.TotalSeconds;
        ThemeChoice.SelectedIndex = (int)settings.Theme;
        ToolTip.SetTip(ProjectRoot, path);
        Closing += (_, args) => { if (saving) args.Cancel = true; };
        KeyDown += (_, args) => { if (args.Key == Avalonia.Input.Key.Escape && !saving) Close(); };
        if (service.Loaded is { CanPersist: false } invalid)
        { Problem.Text = invalid.Error; Problem.IsVisible = true; SaveButton.IsEnabled = invalid.Kind != SettingsLoadKind.UnsupportedVersion; }
    }
    private void Cancel(object? sender, RoutedEventArgs args) => Close();
    private async void Save(object? sender, RoutedEventArgs args)
    {
        SaveButton.IsEnabled = false;
        saving = true;
        try
        {
            if (Timeout.Value is not { } seconds) throw new ArgumentException("请输入启动等待时间。");
            var settings = service.Current with { ManageService = ManageService.IsChecked == true,
                StartFullscreen = StartFullscreen.IsChecked == true,
                ProjectRoot = ProjectRoot.Text?.Trim() ?? "", StartupTimeout = TimeSpan.FromSeconds((double)seconds), Theme = (ThemePreference)ThemeChoice.SelectedIndex };
            await service.SaveAsync(settings);
            MainWindow.ApplyTheme(settings.Theme);
            Saved = true;
            saving = false;
            Close();
        }
        catch (Exception ex) { Problem.Text = ex.Message; Problem.IsVisible = true; SaveButton.IsEnabled = true; }
        finally { saving = false; }
    }
}
