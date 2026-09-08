using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;

namespace Amvar.Launcher.Desktop;

public partial class App : Avalonia.Application
{
    public override void Initialize() => AvaloniaXamlLoader.Load(this);
    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.ShutdownMode = ShutdownMode.OnExplicitShutdown;
            var composition = new Bootstrap.LauncherComposition();
            var window = new Views.MainWindow(composition, desktop);
            desktop.MainWindow = window;
            desktop.ShutdownRequested += (_, args) => { args.Cancel = true; window.RequestExit(); };
        }
        base.OnFrameworkInitializationCompleted();
    }
}
