using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision;
using Newtonsoft.Json;

namespace Amvar.Vision.ConsoleApp
{
    /// <summary>
    /// Amvar Vision .NET SDK 调试控制台。
    /// </summary>
    internal static class Program
    {
        /// <summary>
        /// 程序入口。控制台只解析命令行参数，实际 HTTP、ZeroMQ、配置加载和业务调用都交给 SDK。
        /// </summary>
        /// <param name="args">命令行参数。</param>
        /// <returns>进程退出码；0 表示成功。</returns>
        private static async Task<int> Main(string[] args)
        {
            try
            {
                var options = ConsoleOptions.Parse(args);
                if (options.Command == "help")
                {
                    PrintUsage();
                    return 0;
                }

                var exitCode = await ExecuteCommandAsync(options, CancellationToken.None).ConfigureAwait(false);
                return exitCode;
            }
            catch (AMVisionApiException exception)
            {
                WriteApiException(exception);
                return 2;
            }
            catch (AMVisionTransportException exception)
            {
                WriteKnownException("HTTP transport failed", exception);
                return 3;
            }
            catch (AMVisionTriggerException exception)
            {
                WriteTriggerException(exception);
                return 4;
            }
            catch (ArgumentException exception)
            {
                WriteKnownException("Invalid argument", exception);
                return 5;
            }
            catch (InvalidOperationException exception)
            {
                WriteKnownException("Invalid operation", exception);
                return 6;
            }
            catch (Exception exception)
            {
                System.Console.Error.WriteLine("Unhandled exception:");
                System.Console.Error.WriteLine(exception);
                return 1;
            }
        }

        /// <summary>
        /// 执行已经解析完成的控制台命令。
        /// </summary>
        /// <param name="options">控制台命令参数。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>进程退出码。</returns>
        private static async Task<int> ExecuteCommandAsync(
            ConsoleOptions options,
            CancellationToken cancellationToken)
        {
            using (var client = CreateClient(options.ConfigDirectory))
            {
                if (options.Command == "health")
                {
                    var response = await client.GetSystemConfigResponseAsync(cancellationToken).ConfigureAwait(false);
                    PrintHealthSummary(response);
                    return 0;
                }

                if (options.Command == "runtime-invoke")
                {
                    var runtimeName = options.RequireArgument(0, "runtime-key");
                    var response = await client.InvokeConfiguredWorkflowRuntimeAsync(
                        runtimeName,
                        cancellationToken).ConfigureAwait(false);
                    PrintJson(response);
                    return 0;
                }

                if (options.Command == "runtime-invoke-image")
                {
                    var runtimeName = options.RequireArgument(0, "runtime-key");
                    var imagePath = options.RequireArgument(1, "image-path");
                    var response = await client.InvokeConfiguredWorkflowRuntimeWithImageFileAsync(
                        runtimeName,
                        imagePath,
                        cancellationToken: cancellationToken).ConfigureAwait(false);
                    PrintJson(response);
                    return 0;
                }

                if (options.Command == "model-invoke")
                {
                    var deploymentName = options.RequireArgument(0, "deployment-key");
                    var response = await client.InvokeConfiguredModelDeploymentAsync(
                        deploymentName,
                        cancellationToken).ConfigureAwait(false);
                    PrintJson(response);
                    return 0;
                }

                if (options.Command == "model-invoke-image")
                {
                    var deploymentName = options.RequireArgument(0, "deployment-key");
                    var imagePath = options.RequireArgument(1, "image-path");
                    var response = await client.InvokeConfiguredModelDeploymentWithImageFileAsync(
                        deploymentName,
                        imagePath,
                        cancellationToken: cancellationToken).ConfigureAwait(false);
                    PrintJson(response);
                    return 0;
                }

                if (options.Command == "model-run")
                {
                    var deploymentName = options.RequireArgument(0, "deployment-key");
                    var response = await client.RunConfiguredModelDeploymentAsync(
                        deploymentName,
                        cancellationToken).ConfigureAwait(false);
                    PrintJson(response);
                    return 0;
                }

                if (options.Command == "model-run-image")
                {
                    var deploymentName = options.RequireArgument(0, "deployment-key");
                    var imagePath = options.RequireArgument(1, "image-path");
                    var response = await client.RunConfiguredModelDeploymentWithImageFileAsync(
                        deploymentName,
                        imagePath,
                        cancellationToken: cancellationToken).ConfigureAwait(false);
                    PrintJson(response);
                    return 0;
                }

                if (options.Command == "trigger-image")
                {
                    var triggerSourceName = options.RequireArgument(0, "trigger-key");
                    var response = await client.InvokeConfiguredZeroMqImageAsync(
                        triggerSourceName,
                        cancellationToken).ConfigureAwait(false);
                    PrintJson(response);
                    return 0;
                }

                if (options.Command == "trigger-image-file")
                {
                    var triggerSourceName = options.RequireArgument(0, "trigger-key");
                    var imagePath = options.RequireArgument(1, "image-path");
                    var response = await client.InvokeConfiguredZeroMqImageFileAsync(
                        triggerSourceName,
                        imagePath,
                        cancellationToken: cancellationToken).ConfigureAwait(false);
                    PrintJson(response);
                    return 0;
                }

                if (options.Command == "trigger-bgr24")
                {
                    var triggerSourceName = options.RequireArgument(0, "trigger-key");
                    var response = await client.InvokeConfiguredZeroMqBgr24ImageAsync(
                        triggerSourceName,
                        cancellationToken).ConfigureAwait(false);
                    PrintJson(response);
                    return 0;
                }

                if (options.Command == "trigger-bgr24-file")
                {
                    var triggerSourceName = options.RequireArgument(0, "trigger-key");
                    var imagePath = options.RequireArgument(1, "image-path");
                    var response = await client.InvokeConfiguredZeroMqBgr24ImageFileAsync(
                        triggerSourceName,
                        imagePath,
                        cancellationToken).ConfigureAwait(false);
                    PrintJson(response);
                    return 0;
                }
            }

            throw new ArgumentException($"Unknown command: {options.Command}. Use help to view available commands.");
        }

        /// <summary>
        /// 按命令行参数创建 SDK client。
        /// </summary>
        /// <param name="configDirectory">可选 Config 目录。</param>
        /// <returns>已经加载配置的 SDK client。</returns>
        private static AMVisionClient CreateClient(string? configDirectory)
        {
            if (configDirectory == null)
            {
                var client = AMVisionClient.CreateFromConfig();
                return client;
            }

            var trimmedConfigDirectory = configDirectory.Trim();
            if (trimmedConfigDirectory.Length == 0)
            {
                var client = AMVisionClient.CreateFromConfig();
                return client;
            }

            var configuredClient = AMVisionClient.CreateFromConfigDirectory(trimmedConfigDirectory);
            return configuredClient;
        }

        /// <summary>
        /// 输出 JSON 响应，便于现场复制和排查。
        /// </summary>
        /// <param name="value">待输出对象。</param>
        private static void PrintJson(object value)
        {
            var json = JsonConvert.SerializeObject(value, Formatting.Indented);
            System.Console.WriteLine(json);
        }

        /// <summary>
        /// 输出后端连接检查摘要，避免 health 命令打印过大的系统配置。
        /// </summary>
        /// <param name="response">系统配置响应。</param>
        private static void PrintHealthSummary(SystemConfigResponse response)
        {
            if (response == null)
            {
                throw new ArgumentNullException(nameof(response));
            }

            var localBufferBroker = response.LocalBufferBroker;
            var summary = new Dictionary<string, object?>
            {
                ["state"] = "ok",
                ["format_id"] = response.FormatId,
                ["local_buffer_broker_enabled"] = localBufferBroker?.Enabled,
                ["local_buffer_broker_default_pool"] = localBufferBroker?.DefaultPoolName
            };

            PrintJson(summary);
        }

        /// <summary>
        /// 输出 HTTP API 异常详情。
        /// </summary>
        /// <param name="exception">SDK HTTP API 异常。</param>
        private static void WriteApiException(AMVisionApiException exception)
        {
            System.Console.Error.WriteLine("HTTP API call failed:");
            System.Console.Error.WriteLine(exception.Message);
            System.Console.Error.WriteLine($"StatusCode: {(int)exception.StatusCode}");

            if (!string.IsNullOrWhiteSpace(exception.ErrorCode))
            {
                System.Console.Error.WriteLine($"ErrorCode: {exception.ErrorCode}");
            }

            if (exception.Details.Count > 0)
            {
                System.Console.Error.WriteLine("Details:");
                System.Console.Error.WriteLine(JsonConvert.SerializeObject(exception.Details, Formatting.Indented));
            }

            if (!string.IsNullOrWhiteSpace(exception.ResponseBody))
            {
                System.Console.Error.WriteLine("ResponseBody:");
                System.Console.Error.WriteLine(exception.ResponseBody);
            }
        }

        /// <summary>
        /// 输出 ZeroMQ TriggerSource 异常详情。
        /// </summary>
        /// <param name="exception">SDK TriggerSource 异常。</param>
        private static void WriteTriggerException(AMVisionTriggerException exception)
        {
            System.Console.Error.WriteLine("ZeroMQ TriggerSource call failed:");
            System.Console.Error.WriteLine(exception.Message);
            System.Console.Error.WriteLine($"ErrorCode: {exception.ErrorCode}");

            if (exception.Details.Count > 0)
            {
                System.Console.Error.WriteLine("Details:");
                System.Console.Error.WriteLine(JsonConvert.SerializeObject(exception.Details, Formatting.Indented));
            }
        }

        /// <summary>
        /// 输出已知异常。
        /// </summary>
        /// <param name="title">错误标题。</param>
        /// <param name="exception">异常对象。</param>
        private static void WriteKnownException(string title, Exception exception)
        {
            System.Console.Error.WriteLine($"{title}:");
            System.Console.Error.WriteLine(exception.Message);

            if (exception.InnerException != null)
            {
                System.Console.Error.WriteLine("InnerException:");
                System.Console.Error.WriteLine(exception.InnerException.Message);
            }
        }

        /// <summary>
        /// 输出控制台使用说明。
        /// </summary>
        private static void PrintUsage()
        {
            System.Console.WriteLine("Amvar Vision .NET SDK Console");
            System.Console.WriteLine();
            System.Console.WriteLine("Config loading: the SDK automatically loads Config/config*.json. Commands only need config key names and required arguments.");
            System.Console.WriteLine();
            System.Console.WriteLine("Global options:");
            System.Console.WriteLine("  --config-dir <path>                 Use the specified Config directory; omitted means SDK default discovery.");
            System.Console.WriteLine();
            System.Console.WriteLine("Commands:");
            System.Console.WriteLine("  help                                Show help.");
            System.Console.WriteLine("  health                              Call the backend-service system config API.");
            System.Console.WriteLine("  runtime-invoke <runtime-key>         Invoke Workflow App Runtime with configured default input.");
            System.Console.WriteLine("  runtime-invoke-image <runtime-key> <image-path>");
            System.Console.WriteLine("                                      Invoke Workflow App Runtime with an image file.");
            System.Console.WriteLine("  model-invoke <deployment-key>        Invoke model deployment with configured default input.");
            System.Console.WriteLine("  model-invoke-image <deployment-key> <image-path>");
            System.Console.WriteLine("                                      Invoke model deployment with an image file.");
            System.Console.WriteLine("  model-run <deployment-key>           Create an async model inference task with configured default input.");
            System.Console.WriteLine("  model-run-image <deployment-key> <image-path>");
            System.Console.WriteLine("                                      Create an async model inference task with an image file.");
            System.Console.WriteLine("  trigger-image <trigger-key>          Trigger ZeroMQ image bytes with configured default image.");
            System.Console.WriteLine("  trigger-image-file <trigger-key> <image-path>");
            System.Console.WriteLine("                                      Trigger ZeroMQ image bytes with an image file.");
            System.Console.WriteLine("  trigger-bgr24 <trigger-key>          Trigger ZeroMQ BGR24 with configured default image.");
            System.Console.WriteLine("  trigger-bgr24-file <trigger-key> <image-path>");
            System.Console.WriteLine("                                      Trigger ZeroMQ BGR24 with an image file.");
            System.Console.WriteLine();
            System.Console.WriteLine("Examples:");
            System.Console.WriteLine("  Amvar.Vision.Console.exe health");
            System.Console.WriteLine("  Amvar.Vision.Console.exe runtime-invoke tray-empty-runtime");
            System.Console.WriteLine("  Amvar.Vision.Console.exe model-invoke-image slot-classifier .\\images\\slot.jpg");
            System.Console.WriteLine("  Amvar.Vision.Console.exe trigger-bgr24-file zeromq-tray-empty .\\images\\tray.jpg");
        }

        /// <summary>
        /// 控制台命令参数。
        /// </summary>
        private sealed class ConsoleOptions
        {
            /// <summary>
            /// 命令名称。
            /// </summary>
            public string Command { get; private set; } = "help";

            /// <summary>
            /// 命令参数。
            /// </summary>
            public IReadOnlyList<string> Arguments { get; private set; } = Array.Empty<string>();

            /// <summary>
            /// 可选 Config 目录。
            /// </summary>
            public string? ConfigDirectory { get; private set; }

            /// <summary>
            /// 解析命令行参数。
            /// </summary>
            /// <param name="args">原始命令行参数。</param>
            /// <returns>解析完成的控制台参数。</returns>
            public static ConsoleOptions Parse(string[] args)
            {
                var values = new List<string>();
                string? configDirectory = null;

                for (var index = 0; index < args.Length; index++)
                {
                    var value = args[index];
                    if (string.Equals(value, "--config-dir", StringComparison.OrdinalIgnoreCase))
                    {
                        if (index + 1 >= args.Length)
                        {
                            throw new ArgumentException("--config-dir requires a directory path.");
                        }

                        configDirectory = args[index + 1];
                        index++;
                        continue;
                    }

                    values.Add(value);
                }

                var options = new ConsoleOptions
                {
                    ConfigDirectory = configDirectory
                };

                if (values.Count == 0)
                {
                    options.Command = "help";
                    options.Arguments = Array.Empty<string>();
                    return options;
                }

                options.Command = values[0].Trim().ToLowerInvariant();
                values.RemoveAt(0);
                options.Arguments = values.ToArray();
                return options;
            }

            /// <summary>
            /// 读取必填命令参数。
            /// </summary>
            /// <param name="index">参数索引。</param>
            /// <param name="name">参数名称，用于错误提示。</param>
            /// <returns>非空参数文本。</returns>
            public string RequireArgument(int index, string name)
            {
                if (index >= Arguments.Count || string.IsNullOrWhiteSpace(Arguments[index]))
                {
                    throw new ArgumentException($"Command {Command} requires argument: {name}.");
                }

                return Arguments[index];
            }
        }
    }
}
