using System.Diagnostics;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Amvar.Launcher.Core.Diagnostics;

namespace Amvar.Launcher.Desktop.Views;

public partial class AboutWindow : Window
{
    private readonly BuildInformation information = null!;
    public AboutWindow() => InitializeComponent();
    public AboutWindow(BuildInformation information) : this()
    {
        this.information = information;
        VersionText.Text = information.Version;
        BuildText.Text = information.BuiltAt.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss zzz");
        CommitText.Text = information.Commit;
        LicenseText.Text = information.License;
        KeyDown += (_, args) => { if (args.Key == Avalonia.Input.Key.Escape) Close(); };
    }
    private void OpenRepository(object? sender, RoutedEventArgs args) => Open(information.Repository);
    private void OpenWebsite(object? sender, RoutedEventArgs args) => Open(information.Website);
    private void OpenLicense(object? sender, RoutedEventArgs args)
    {
        using var stream = Avalonia.Platform.AssetLoader.Open(new Uri("avares://amvar.launcher/Assets/LICENSE.txt"));
        using var reader = new StreamReader(stream);
        var dialog = new Window { Title = "许可证", Width = 720, Height = 540, WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Content = new TextBox { Text = reader.ReadToEnd(), IsReadOnly = true, AcceptsReturn = true, TextWrapping = Avalonia.Media.TextWrapping.Wrap, Margin = new Avalonia.Thickness(20) } };
        dialog.KeyDown += (_, key) => { if (key.Key == Avalonia.Input.Key.Escape) dialog.Close(); };
        dialog.Show(this);
    }
    private void Dismiss(object? sender, RoutedEventArgs args) => Close();
    private void Open(string url)
    {
        try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
        catch (Exception ex) { LicenseText.Text = "链接打开失败：" + ex.Message; }
    }
}
