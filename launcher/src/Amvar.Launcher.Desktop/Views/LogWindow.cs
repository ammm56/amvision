using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;

namespace Amvar.Launcher.Desktop.Views;

/// <summary>有界读取当前启动器日志，不载入网页或业务数据。</summary>
public sealed class LogWindow : Window
{
    private readonly TextBox output = new() { IsReadOnly = true, AcceptsReturn = true, TextWrapping = Avalonia.Media.TextWrapping.Wrap, FontSize = 12 };
    private readonly string directory;
    public LogWindow(string directory)
    {
        this.directory = directory;
        Title = "启动日志"; Width = 800; Height = 540; MinWidth = 540; MinHeight = 320;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var refresh = new Button { Content = "刷新" };
        refresh.Click += async (_, _) => await ReadAsync();
        var folder = new Button { Content = "打开日志目录" };
        folder.Click += (_, _) =>
        {
            try { Directory.CreateDirectory(directory); Process.Start(new ProcessStartInfo(directory) { UseShellExecute = true }); }
            catch (Exception ex) { output.Text = ex.Message; }
        };
        var layout = new Grid { RowDefinitions = new("Auto,12,*"), Margin = new Thickness(20) };
        layout.Children.Add(new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10, Children = { refresh, folder } });
        Grid.SetRow(output, 2); layout.Children.Add(output); Content = layout;
        Opened += async (_, _) => await ReadAsync();
    }
    private async Task ReadAsync()
    {
        try
        {
            var latest = Directory.Exists(directory) ? Directory.EnumerateFiles(directory, "*.log").OrderDescending().FirstOrDefault() : null;
            if (latest == null) { output.Text = "暂无启动日志。"; return; }
            await using var file = new FileStream(latest, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            if (file.Length > 64 * 1024) file.Seek(-64 * 1024, SeekOrigin.End);
            using var reader = new StreamReader(file);
            output.Text = await reader.ReadToEndAsync();
        }
        catch (Exception ex) { output.Text = "日志读取失败：" + ex.Message; }
    }
}
