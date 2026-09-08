using Avalonia;
using Avalonia.Controls;
using System.Runtime.InteropServices;

namespace Amvar.Launcher.Desktop.Services;

/// <summary>保留自定义标题栏，并由 Windows 负责边缘光标、缩放和小圆角。</summary>
public sealed class WindowsWindowFrame : IDisposable
{
    public const double ResizeBorder = 5;
    private const uint ThickFrame = 0x00040000;
    private readonly Window window;
    private readonly Border surface;

    public WindowsWindowFrame(Window window, Border surface)
    {
        this.window = window;
        this.surface = surface;
        Win32Properties.AddWindowStylesCallback(window, ConfigureStyles);
        Win32Properties.AddWndProcHookCallback(window, HitTest);
        Win32Properties.SetWindowCornerPreference(window, Win32Properties.WindowCornerPreference.RoundSmall);
        window.PropertyChanged += OnPropertyChanged;
        window.Opened += OnOpened;
        UpdatePadding();
    }

    private void OnOpened(object? sender, EventArgs args)
    {
        if (!OperatingSystem.IsWindows() || window.TryGetPlatformHandle() is not { Handle: var handle }) return;
        // DWM 保留圆角和阴影，隐藏其默认浅色描边；旧系统不支持此属性时保持系统行为。
        uint borderColor = 0xfffffffe;
        _ = DwmSetWindowAttribute(handle, 34, ref borderColor, sizeof(uint));
    }

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr window, uint attribute, ref uint value, int size);

    private (uint, uint) ConfigureStyles(uint style, uint extendedStyle) =>
        (window.CanResize && window.WindowState != WindowState.FullScreen ? style | ThickFrame : style & ~ThickFrame, extendedStyle);

    private void OnPropertyChanged(object? sender, AvaloniaPropertyChangedEventArgs args)
    {
        if (args.Property == Window.WindowStateProperty || args.Property == Window.CanResizeProperty) UpdatePadding();
    }

    // 原生 WebView 不覆盖边缘，使系统始终能够收到非客户区命中测试。
    private void UpdatePadding() => surface.Padding = new Thickness(window.CanResize && window.WindowState == WindowState.Normal ? ResizeBorder : 0);

    private IntPtr HitTest(IntPtr handle, uint message, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (message != 0x0084 || !window.CanResize || window.WindowState != WindowState.Normal) return IntPtr.Zero;
        var packed = lParam.ToInt64();
        var point = window.PointToClient(new PixelPoint((short)(packed & 0xffff), (short)((packed >> 16) & 0xffff)));
        var result = ResizeHitTest(point, window.Bounds.Size);
        if (result == 0) return IntPtr.Zero;
        handled = true;
        return new IntPtr(result);
    }

    /// <summary>返回 Windows 标准 HT 边缘值；角点使用更大的沿边命中范围。</summary>
    public static int ResizeHitTest(Point point, Size size)
    {
        if (point.X < 0 || point.Y < 0 || point.X >= size.Width || point.Y >= size.Height) return 0;
        var left = point.X < ResizeBorder;
        var right = point.X >= size.Width - ResizeBorder;
        var top = point.Y < ResizeBorder;
        var bottom = point.Y >= size.Height - ResizeBorder;
        if (!(left || right || top || bottom)) return 0;
        var nearLeft = point.X < 16; var nearRight = point.X >= size.Width - 16;
        var nearTop = point.Y < 16; var nearBottom = point.Y >= size.Height - 16;
        if (nearLeft && nearTop) return 13;
        if (nearRight && nearTop) return 14;
        if (nearLeft && nearBottom) return 16;
        if (nearRight && nearBottom) return 17;
        return left ? 10 : right ? 11 : top ? 12 : 15;
    }

    public void Dispose()
    {
        window.PropertyChanged -= OnPropertyChanged;
        window.Opened -= OnOpened;
        Win32Properties.RemoveWndProcHookCallback(window, HitTest);
        Win32Properties.RemoveWindowStylesCallback(window, ConfigureStyles);
    }
}
