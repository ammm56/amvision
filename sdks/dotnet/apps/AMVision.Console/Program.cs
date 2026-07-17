using System;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision;

namespace AMVision.Console
{
    /// <summary>
    /// 控制台程序入口。默认演示 key name 调用；需要验证稳定 id 时切换下面两行注释。
    /// </summary>
    internal static class Program
    {
        private static int Main()
        {
            try
            {
                MainAsync(CancellationToken.None).GetAwaiter().GetResult();
                return 0;
            }
            catch (Exception exception)
            {
                System.Console.Error.WriteLine(exception);
                return 1;
            }
        }

        private static async Task MainAsync(CancellationToken cancellationToken)
        {
            using (var runner = AMVisionOperationRunner.CreateDefault())
            {
                // 默认入口：使用前端可读、可修改的 key name。
                await KeyNameSdkCalls.RunAsync(runner, cancellationToken).ConfigureAwait(false);

                // 稳定兜底：需要按后端资源 id 验证时，注释上一行并启用下一行。
                //await ResourceIdSdkCalls.RunAsync(runner, cancellationToken).ConfigureAwait(false);
            }

            if (!System.Console.IsInputRedirected)
            {
                System.Console.ReadKey(intercept: true);
            }
        }
    }
}
