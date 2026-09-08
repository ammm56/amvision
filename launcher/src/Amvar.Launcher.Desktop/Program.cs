using Avalonia;

namespace Amvar.Launcher.Desktop;

internal static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        if (args is ["--write-build-info"]) { Bootstrap.LauncherComposition.WriteBuildInfo(); return; }
        if (args is ["--write-release-manifest"]) { Bootstrap.LauncherComposition.WriteReleaseManifest(); return; }
        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
    }

    public static AppBuilder BuildAvaloniaApp() => AppBuilder.Configure<App>().UsePlatformDetect();
}
