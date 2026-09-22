using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Interactivity;
using Avalonia.Platform;
using Avalonia.Controls.Presenters;
using Avalonia.Media;
using Avalonia.Styling;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Application;
using Amvar.Launcher.Core.Configuration;
using Amvar.Launcher.Infrastructure.Metadata;
using Amvar.Launcher.Desktop.Views;

namespace Amvar.Launcher.Desktop.Tests;

[Collection("Avalonia UI")]
public sealed class NativeViewTests
{
    [Fact]
    public async Task Settings_save_uses_typed_values_and_preserves_geometry()
    {
        using var session = HeadlessUnitTestSession.StartNew(typeof(TestApplication));
        await session.Dispatch(async () =>
        {
            var store = new MemorySettings();
            var service = new SettingsService(store);
            await service.LoadAsync();
            var window = new SettingsWindow(service, "config/launcher.json");
            window.Show();
            window.FindControl<CheckBox>("ManageService")!.IsChecked = false;
            window.FindControl<CheckBox>("StartFullscreen")!.IsChecked = true;
            window.FindControl<TextBox>("ProjectRoot")!.Text = "视觉 项目";
            window.FindControl<Button>("SaveButton")!.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Assert.True(window.Saved);
            Assert.False(store.Value.ManageService);
            Assert.True(store.Value.StartFullscreen);
            Assert.Equal("视觉 项目", store.Value.ProjectRoot);
            Assert.Equal(1400, store.Value.Window.Width);
            window.Close();
            return true;
        }, CancellationToken.None);
    }
    [Fact]
    public async Task Unknown_configuration_version_disables_save()
    {
        using var session = HeadlessUnitTestSession.StartNew(typeof(TestApplication));
        await session.Dispatch(async () =>
        {
            var service = new SettingsService(new MemorySettings { Kind = SettingsLoadKind.UnsupportedVersion });
            await service.LoadAsync();
            var window = new SettingsWindow(service, "config/launcher.json");
            window.Show();
            Assert.False(window.FindControl<Button>("SaveButton")!.IsEnabled);
            Assert.True(window.FindControl<TextBlock>("Problem")!.IsVisible);
            window.Close();
            return true;
        }, CancellationToken.None);
    }
    [Fact]
    public async Task About_and_main_xaml_load_with_embedded_offline_assets()
    {
        using var session = HeadlessUnitTestSession.StartNew(typeof(TestApplication));
        await session.Dispatch(() =>
        {
            var about = new AboutWindow(BuildInformationReader.Read(typeof(MainWindow).Assembly));
            about.Show();
            Assert.Equal("0.1.8", about.FindControl<SelectableTextBlock>("VersionText")!.Text);
            using var license = new StreamReader(AssetLoader.Open(new Uri("avares://amvar.launcher/Assets/LICENSE.txt")));
            Assert.Contains("PolyForm", license.ReadToEnd());
            using var icon = AssetLoader.Open(new Uri("avares://amvar.launcher/Assets/app.ico"));
            Assert.True(icon.Length > 100);
            var main = new MainWindow { DataContext = new Amvar.Launcher.Desktop.ViewModels.LauncherViewModel() };
            main.Show();
            Assert.NotNull(main.FindControl<Border>("LoadingSurface"));
            main.Close(); about.Close();
        }, CancellationToken.None);
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Settings_hover_and_focus_keep_one_input_outline_and_white_save_text(bool dark)
    {
        using var session = HeadlessUnitTestSession.StartNew(typeof(TestApplication));
        await session.Dispatch(async () =>
        {
            var service = new SettingsService(new MemorySettings());
            await service.LoadAsync();
            var window = new SettingsWindow(service, "config/launcher.json")
                { RequestedThemeVariant = dark ? ThemeVariant.Dark : ThemeVariant.Light };
            window.Show();
            window.UpdateLayout();
            var input = window.FindControl<NumericUpDown>("Timeout")!;
            var textbox = input.GetVisualDescendants().OfType<TextBox>().Single();
            var innerBorder = textbox.GetVisualDescendants().OfType<Border>()
                .Single(border => border.Name == "PART_BorderElement");
            void CheckOutline()
            {
                Assert.False(innerBorder.IsVisible);
                Assert.Equal(new Thickness(1), input.BorderThickness);
            }
            CheckOutline();
            window.MouseMove(textbox.TranslatePoint(new Point(10, 10), window)!.Value);
            Assert.True(textbox.IsPointerOver);
            CheckOutline();
            textbox.Focus();
            Assert.True(textbox.IsFocused);
            CheckOutline();

            var save = window.FindControl<Button>("SaveButton")!;
            var content = save.GetVisualDescendants().OfType<ContentPresenter>()
                .Single(presenter => presenter.Name == "PART_ContentPresenter");
            Assert.Equal(Colors.White, Assert.IsAssignableFrom<ISolidColorBrush>(content.Foreground).Color);
            window.MouseMove(save.TranslatePoint(new Point(10, 10), window)!.Value);
            Assert.True(save.IsPointerOver);
            Assert.Equal(Colors.White, Assert.IsAssignableFrom<ISolidColorBrush>(content.Foreground).Color);
            Assert.Equal(1, content.Opacity);
            window.Close();
            return true;
        }, CancellationToken.None);
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task About_links_and_popup_item_keep_their_text_color_on_hover(bool dark)
    {
        using var session = HeadlessUnitTestSession.StartNew(typeof(TestApplication));
        await session.Dispatch(() =>
        {
            var theme = dark ? ThemeVariant.Dark : ThemeVariant.Light;
            var about = new AboutWindow(BuildInformationReader.Read(typeof(MainWindow).Assembly))
                { RequestedThemeVariant = theme };
            about.Show();
            about.UpdateLayout();
            var links = about.GetVisualDescendants().OfType<Button>()
                .Where(button => button.Classes.Contains("link")).ToArray();
            Assert.Equal(3, links.Length);
            foreach (var link in links)
                CheckHover(about, link, Color.Parse(dark ? "#00D992" : "#087A56"));
            about.Close();

            var item = new Button { Content = "关于", Classes = { "popupItem" } };
            var popup = new Window { Content = item, RequestedThemeVariant = theme, Width = 220, Height = 100 };
            popup.Show();
            popup.UpdateLayout();
            CheckHover(popup, item, Color.Parse(dark ? "#F2F2F2" : "#344054"));
            popup.Close();
        }, CancellationToken.None);

        static void CheckHover(Window window, Button button, Color expected)
        {
            var presenter = button.GetVisualDescendants().OfType<ContentPresenter>()
                .Single(item => item.Name == "PART_ContentPresenter");
            var bounds = button.Bounds.Size;
            for (var iteration = 0; iteration < 3; iteration++)
            {
                window.MouseMove(new Point(-10, -10));
                Assert.False(button.IsPointerOver);
                Assert.Equal(expected, Assert.IsAssignableFrom<ISolidColorBrush>(presenter.Foreground).Color);
                window.MouseMove(button.TranslatePoint(new Point(10, 10), window)!.Value);
                Assert.True(button.IsPointerOver);
                Assert.Equal(expected, Assert.IsAssignableFrom<ISolidColorBrush>(presenter.Foreground).Color);
                Assert.Equal(bounds, button.Bounds.Size);
            }
        }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task About_buttons_do_not_flash_brighter_during_hover_transition(bool dark)
    {
        using var session = HeadlessUnitTestSession.StartNew(typeof(TestApplication));
        await session.Dispatch(async () =>
        {
            var theme = dark ? ThemeVariant.Dark : ThemeVariant.Light;
            var hover = Color.Parse(dark ? "#242825" : "#ECEFF2");
            var about = new AboutWindow(BuildInformationReader.Read(typeof(MainWindow).Assembly))
                { RequestedThemeVariant = theme };
            about.Show();
            about.UpdateLayout();
            foreach (var link in about.GetVisualDescendants().OfType<Button>().Where(b => b.Classes.Contains("link")))
                await CheckFrames(about, link, Color.Parse(dark ? "#101010" : "#F6F7F9"), hover);
            about.Close();

            var surface = Color.Parse(dark ? "#171918" : "#FFFFFF");
            var item = new Button { Content = "关于", Classes = { "popupItem" }, Margin = new Thickness(10) };
            var popup = new Window { Content = item, Background = new SolidColorBrush(surface),
                RequestedThemeVariant = theme, Width = 220, Height = 100 };
            popup.Show();
            popup.UpdateLayout();
            await CheckFrames(popup, item, surface, hover);
            popup.Close();
            return true;
        }, CancellationToken.None);

        static async Task CheckFrames(Window window, Button button, Color surface, Color hover)
        {
            var presenter = button.GetVisualDescendants().OfType<ContentPresenter>()
                .Single(p => p.Name == "PART_ContentPresenter");
            // 检查真实 BrushTransition 的中间帧，不能仅断言悬停前后的最终颜色。
            window.MouseMove(new Point(-10, -10));
            for (var direction = 0; direction < 2; direction++)
            {
                window.MouseMove(direction == 0
                    ? button.TranslatePoint(new Point(10, 10), window)!.Value : new Point(-10, -10));
                var intermediateFrames = 0;
                for (var frame = 0; frame < 15; frame++)
                {
                    await Task.Delay(16);
                    AvaloniaHeadlessPlatform.ForceRenderTimerTick();
                    Dispatcher.UIThread.RunJobs();
                    var brush = Assert.IsAssignableFrom<ISolidColorBrush>(presenter.Background);
                    var color = brush.Color;
                    var alpha = color.A / 255d * brush.Opacity;
                    var actual = new[] { color.R * alpha + surface.R * (1 - alpha),
                        color.G * alpha + surface.G * (1 - alpha), color.B * alpha + surface.B * (1 - alpha) };
                    var start = new[] { surface.R, surface.G, surface.B };
                    var end = new[] { hover.R, hover.G, hover.B };
                    for (var channel = 0; channel < 3; channel++)
                        Assert.InRange(actual[channel], Math.Min(start[channel], end[channel]) - 1d,
                            Math.Max(start[channel], end[channel]) + 1d);
                    if (Math.Abs(actual[0] - start[0]) > 1 && Math.Abs(actual[0] - end[0]) > 1)
                        intermediateFrames++;
                    Assert.Equal(direction == 0, button.IsPointerOver);
                }
                Assert.True(intermediateFrames > 0, "必须采样到实际动画中间帧，避免静态断言掩盖闪烁。");
            }
        }
    }

    public sealed class TestApplication
    {
        public static AppBuilder BuildAvaloniaApp() => AppBuilder.Configure<Amvar.Launcher.Desktop.App>().UseHeadless(new());
    }
    private sealed class MemorySettings : ISettingsStore
    {
        public LauncherSettings Value = new() { Window = new(1400, 900) };
        public SettingsLoadKind Kind = SettingsLoadKind.Valid;
        public Task<SettingsLoadResult> LoadAsync(CancellationToken token) => Task.FromResult(new SettingsLoadResult(Kind, Value, "配置版本不支持"));
        public Task SaveAsync(LauncherSettings settings, CancellationToken token) { Value = settings; return Task.CompletedTask; }
    }
}
