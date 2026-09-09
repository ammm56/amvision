using System;
using System.IO;
using System.Threading;
using Amvar.Vision;
using Newtonsoft.Json;

namespace Amvar.Vision.ContractTests
{
    /// <summary>通过正式 SDK 验证默认 Token 的真实同步、异步 Workflow 调用。</summary>
    internal static class UserAccessSdkProbe
    {
        internal static int Run(string[] args)
        {
            if (args.Length != 5) return 64;
            try
            {
                using (var client = new AMVisionClient(new AMVisionClientOptions
                {
                    BaseApiUrl = args[1],
                    AccessToken = Environment.GetEnvironmentVariable("AMVISION_ACCEPTANCE_TOKEN") ?? "amvision-default-user-token"
                }))
                {
                    var request = new WorkflowRuntimeInvokeRequest();
                    request.InputBindings["request_image_base64"] = new
                    {
                        image_base64 = Convert.ToBase64String(File.ReadAllBytes(args[3])),
                        media_type = "image/jpeg"
                    };
                    var multipart = new WorkflowRuntimeMultipartInvokeRequest();
                    multipart.Files.Add(WorkflowRuntimeMultipartFile.FromFile("request_image_ref", args[3], "image/jpeg"));
                    var useUpload = Environment.GetEnvironmentVariable("AMVISION_ACCEPTANCE_INPUT_MODE") == "upload";
                    var sync = useUpload
                        ? client.InvokeWorkflowAppRuntimeUploadResponseAsync(args[2], multipart).GetAwaiter().GetResult()
                        : client.InvokeWorkflowAppRuntimeResponseAsync(args[2], request).GetAwaiter().GetResult();
                    if (sync.State != "succeeded") throw new InvalidOperationException("同步调用失败: " + JsonConvert.SerializeObject(sync.Error));
                    var asyncRun = useUpload
                        ? client.CreateWorkflowRunUploadResponseAsync(args[2], multipart).GetAwaiter().GetResult()
                        : client.CreateWorkflowRunResponseAsync(args[2], request).GetAwaiter().GetResult();
                    var deadline = DateTime.UtcNow.AddSeconds(120);
                    while (asyncRun.State == "queued" || asyncRun.State == "running")
                    {
                        if (DateTime.UtcNow >= deadline) throw new TimeoutException("异步调用超时");
                        Thread.Sleep(100);
                        asyncRun = client.GetWorkflowRunResponseAsync(asyncRun.WorkflowRunId).GetAwaiter().GetResult();
                    }
                    if (asyncRun.State != "succeeded") throw new InvalidOperationException("异步调用失败: " + asyncRun.State);
                    File.WriteAllText(args[4], JsonConvert.SerializeObject(new {
                        succeeded = true,
                        sync = new { sync.WorkflowRunId, sync.State, sync.Outputs },
                        asyncRun = new { asyncRun.WorkflowRunId, asyncRun.State, asyncRun.Outputs }
                    }));
                    return 0;
                }
            }
            catch (Exception error)
            {
                File.WriteAllText(args[4], JsonConvert.SerializeObject(new { succeeded = false, error = error.ToString() }));
                return 1;
            }
        }
    }
}
