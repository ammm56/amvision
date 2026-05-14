using System.Windows.Forms;

namespace TriggerSourceDebugWinForms;

internal static class Program
{
    /// <summary>
    /// WinForms 调试入口。
    /// </summary>
    [STAThread]
    private static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MainForm());
    }
}