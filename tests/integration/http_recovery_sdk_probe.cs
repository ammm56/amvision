// 使用现场 .NET Framework x64 SDK 核对同一真实图片的三条 Workflow 通道。
using System;
using System.IO;
using System.Linq;
using System.Threading;
using Amvar.Vision;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

internal static class HttpRecoverySdkProbe
{
    private static JObject Summary(object result)
    {
        var root = JToken.FromObject(result);
        var found = root.SelectTokens("$..*").OfType<JObject>()
            .FirstOrDefault(item => (string)item["format_id"] == "amvision.slot-classification-summary.v1");
        if (found == null) throw new InvalidOperationException("调用没有返回分类摘要：" + root.ToString(Formatting.None));
        return found;
    }

    private static int Main(string[] args)
    {
        try
        {
            const string runtime = "摆盘分拣3570治具空盘检测应用";
            const string zmq = "ZeroMQ 图片触发 摆盘分拣3570治具空盘检测应用 runtime";
            const string shared = "HTTP recovery validation shared";
            var image = File.ReadAllBytes(args[1]);
            var input = new { savepath = args[2], barqrcode = "http-recovery-sdk-probe" };
            using (var runner = AMVisionOperationRunner.CreateFromConfigDirectory(args[0]))
            {
                var request = runner.CreateWorkflowRequestBuilder(runtime)
                    .AddImageBase64("request_image_base64", image, "image/bmp")
                    .AddJson("request_json", input).WithTimeoutSeconds(60).BuildJson();
                var http = Summary(runner.CallAsync(api => api.InvokeRuntimeAppResultAsync(runtime, request, CancellationToken.None)).GetAwaiter().GetResult());
                var zmqInputs = runner.CreateWorkflowTriggerInputsBuilder(zmq).AddJson("request_json", input).Build();
                var zmqResult = Summary(runner.Call(api => api.InvokeZeroMqImageBytesWithInputs(zmq, image, zmqInputs, "image/bmp", CancellationToken.None)));
                var sharedInputs = runner.CreateWorkflowTriggerInputsBuilder(shared).AddJson("request_json", input).Build();
                var sharedResult = Summary(runner.Call(api => api.InvokeSharedMemoryImageBytesWithInputs(shared, image, "image/bmp", sharedInputs)));
                if (!JToken.DeepEquals(http, zmqResult) || !JToken.DeepEquals(http, sharedResult))
                    throw new InvalidOperationException("HTTP / ZeroMQ / 共享内存的分类摘要不一致");
                if ((int)http["count"] != 24 || (int)http["empty_count"] != 24 || (bool)http["passed"] != true)
                    throw new InvalidOperationException("真实空盘图片未得到预期的 24 个空槽结果");
                Console.WriteLine(JsonConvert.SerializeObject(new { result = "passed", channels = new[] { "HTTP", "ZeroMQ", "LocalSharedMemory" }, summary = http }));
            }
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
