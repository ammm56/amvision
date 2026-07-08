using Amvision.Workflows.Console.Tools;
using System;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console;

/// <summary>
/// 控制台程序入口，负责加载配置并执行代码中手动指定的调用方法。
/// </summary>
internal static class Program
{
    /// <summary>
    /// 默认 runtime 配置 key；现场使用时按 Config/config_*.json 修改。
    /// </summary>
    private const string RuntimeName = "yolo11m_barqrcode_runtime";

    /// <summary>
    /// 默认 TriggerSource 配置 key；现场使用时按 Config/config_*.json 修改。
    /// </summary>
    private const string TriggerSourceName = "yolo11m_barqrcode_zeromq";

    /// <summary>
    /// 默认模型 deployment 配置 key；现场使用时按 Config/config_*.json 修改。
    /// </summary>
    private const string ModelDeploymentName = "barcode_detector";

    /// <summary>
    /// WorkflowAppRuntime 或 ZeroMQ 图片文件路径；调用 ImageFromFile 方法时填写。
    /// </summary>
    private const string ImagePath = "Resources\\Img\\qrcode50.jpg";

    /// <summary>
    /// 现场相机或其他上游程序传入的 base64 图片；调用 ImageBase64 方法时填写。
    /// </summary>
    private static string ImageBase64 = "data:image/jpeg;base64,";

    /// <summary>
    /// 同步入口，桥接 async 主流程并统一输出错误。
    /// </summary>
    /// <returns>进程退出码。</returns>
    private static int Main()
    {
        try
        {
            ImageBase64 = ImageConversionTools.ImageFileToDataUrl(ImagePath);
            MainAsync(CancellationToken.None).GetAwaiter().GetResult();
            return 0;
        }
        catch (Exception exception)
        {
            System.Console.Error.WriteLine(exception);
            return 1;
        }
    }

    /// <summary>
    /// 主执行流程；启动时加载全部 config_*.json，并调用代码中明确指定的方法。
    /// </summary>
    /// <param name="cancellationToken">取消信号。</param>
    private static async Task MainAsync(CancellationToken cancellationToken)
    {
        using var runner = WorkflowOperationRunner.CreateDefault();

        var runtimeHealth = await runner.GetRuntimeHealthAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        // runtimeHealth 可直接绑定到 WinForms/WPF 页面，或继续参与现场业务判断。

        var runtime = await runner.GetRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        var runtimes = await runner.ListProjectRuntimesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var startedRuntime = await runner.StartRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var stoppedRuntime = await runner.StopRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var restartedRuntime = await runner.RestartRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        var runtimeInstances = await runner.ListRuntimeInstancesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);

        //var appResult = await runner.InvokeRuntimeAppResultAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var workflowRun = await runner.RunRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        var syncBase64Result = await runner.InvokeRuntimeAppResultWithImageBase64Async(RuntimeName, ImageBase64, mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);
        
        //var syncBytesResult = await runner.InvokeRuntimeAppResultWithImageBytesAsync(RuntimeName, new byte[] { }, mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);
        var syncFileResult = await runner.InvokeRuntimeAppResultWithImageFromFileAsync(RuntimeName, ImagePath, cancellationToken: cancellationToken).ConfigureAwait(false);
        //var asyncBase64Run = await runner.RunRuntimeWithImageBase64Async(RuntimeName, ImageBase64, mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);
        //var asyncBytesRun = await runner.RunRuntimeWithImageBytesAsync(RuntimeName, new byte[] { }, mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);
        //var asyncFileRun = await runner.RunRuntimeWithImageFromFileAsync(RuntimeName, ImagePath, cancellationToken: cancellationToken).ConfigureAwait(false);

        //var checkResult = await runner.CheckRuntimeFlowAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        var runtimeEvents = await runner.GetRuntimeEventsAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        var triggerSources = await runner.ListTriggerSourcesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        var triggerSource = await runner.GetTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
        //var enabledTriggerSource = await runner.EnableTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
        //var disabledTriggerSource = await runner.DisableTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
        var triggerHealth = await runner.GetTriggerSourceHealthAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
        //var eventResult = await runner.InvokeZeroMqEventAsync(TriggerSourceName, cancellationToken: cancellationToken).ConfigureAwait(false);
        //var configuredImageResult = await runner.InvokeZeroMqConfiguredImageAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
        var fileImageResult = await runner.InvokeZeroMqImageFromFileAsync(TriggerSourceName, ImagePath, cancellationToken: cancellationToken).ConfigureAwait(false);

        var base64ImageResult = await runner.InvokeZeroMqImageBase64Async(
            TriggerSourceName,
            ImageBase64,
            mediaType: "image/jpeg",
            cancellationToken: cancellationToken).ConfigureAwait(false);

        //var modelRuntimeStatus = await runner.GetModelDeploymentRuntimeStatusAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
        //var modelRuntimeHealth = await runner.GetModelDeploymentRuntimeHealthAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
        //var warmedModelRuntime = await runner.WarmupModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
        var modelSyncResult = await runner.InvokeModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ImagePath, cancellationToken: cancellationToken).ConfigureAwait(false);
        //var modelAsyncTask = await runner.RunModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ImagePath, cancellationToken: cancellationToken).ConfigureAwait(false);
    }
}
