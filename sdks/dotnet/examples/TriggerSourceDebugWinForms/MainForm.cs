using System.Text.Json;
using System.Windows.Forms;
using Amvision.TriggerSources;

namespace TriggerSourceDebugWinForms;

internal sealed class MainForm : Form
{
    private static readonly JsonSerializerOptions PrettyJsonOptions = new()
    {
        WriteIndented = true
    };

    private readonly TextBox endpointTextBox;
    private readonly TextBox triggerSourceIdTextBox;
    private readonly TextBox workflowRuntimeIdTextBox;
    private readonly TextBox defaultInputBindingTextBox;
    private readonly TextBox httpInputBindingTextBox;
    private readonly TextBox imagePathTextBox;
    private readonly TextBox mediaTypeTextBox;
    private readonly NumericUpDown timeoutSecondsInput;
    private readonly TextBox deploymentInstanceIdTextBox;
    private readonly TextBox eventIdTextBox;
    private readonly TextBox traceIdTextBox;
    private readonly TextBox baseApiUrlTextBox;
    private readonly TextBox accessTokenTextBox;
    private readonly TextBox projectIdTextBox;
    private readonly RichTextBox metadataJsonTextBox;
    private readonly RichTextBox payloadJsonTextBox;
    private readonly TextBox stateTextBox;
    private readonly TextBox workflowRunIdTextBox;
    private readonly TextBox resultEventIdTextBox;
    private readonly Button startRuntimeButton;
    private readonly Button fetchRuntimeHealthButton;
    private readonly Button stopRuntimeButton;
    private readonly Button fetchTriggerSourceHealthButton;
    private readonly Button enableTriggerSourceButton;
    private readonly Button disableTriggerSourceButton;
    private readonly Button invokeButton;
    private readonly Button invokeRuntimeButton;
    private readonly Button fetchRunButton;
    private readonly RichTextBox envelopePreviewTextBox;
    private readonly RichTextBox requestPreviewTextBox;
    private readonly RichTextBox triggerResultTextBox;
    private readonly RichTextBox invokeResponseTextBox;
    private readonly RichTextBox runtimeHealthTextBox;
    private readonly RichTextBox triggerSourceHealthTextBox;
    private readonly RichTextBox workflowRunTextBox;
    private readonly RichTextBox responseImageInfoTextBox;
    private readonly RichTextBox responseImageBase64TextBox;
    private readonly PictureBox responseImageBox;
    private readonly Button copyResponseImageBase64Button;
    private readonly Label statusLabel;
    private readonly OpenFileDialog imageFileDialog;

    /// <summary>
    /// 初始化 TriggerSource WinForms 调试界面。
    /// </summary>
    public MainForm()
    {
        Text = "Amvision TriggerSource / Runtime Debug WinForms";
        Width = 1360;
        Height = 980;
        MinimumSize = new Size(1180, 820);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular, GraphicsUnit.Point);

        imageFileDialog = new OpenFileDialog
        {
            Title = "选择调试图片",
            Filter = "Image Files|*.jpg;*.jpeg;*.png;*.bmp|All Files|*.*"
        };

        endpointTextBox = CreateTextBox("tcp://127.0.0.1:5555");
        triggerSourceIdTextBox = CreateTextBox("zeromq-trigger-source-06");
        workflowRuntimeIdTextBox = CreateTextBox(string.Empty);
        defaultInputBindingTextBox = CreateTextBox("request_image");
        httpInputBindingTextBox = CreateTextBox("request_image_base64");
        imagePathTextBox = CreateTextBox("data/files/validation-inputs/image-1.jpg");
        mediaTypeTextBox = CreateTextBox("image/jpeg");
        timeoutSecondsInput = new NumericUpDown
        {
            Minimum = 1,
            Maximum = 600,
            DecimalPlaces = 0,
            Value = 5,
            Dock = DockStyle.Fill
        };
        deploymentInstanceIdTextBox = CreateTextBox(string.Empty);
        eventIdTextBox = CreateTextBox(string.Empty);
        traceIdTextBox = CreateTextBox(string.Empty);
        baseApiUrlTextBox = CreateTextBox("http://127.0.0.1:8000");
        accessTokenTextBox = CreateTextBox("amvision-default-user-token");
        projectIdTextBox = CreateTextBox("project-1");

        metadataJsonTextBox = CreateJsonBox("{\n  \"source\": \"winforms-debugger\"\n}");
        payloadJsonTextBox = CreateJsonBox("{}");

        stateTextBox = CreateReadOnlyTextBox();
        workflowRunIdTextBox = CreateReadOnlyTextBox();
        resultEventIdTextBox = CreateReadOnlyTextBox();

        startRuntimeButton = new Button
        {
            Text = "启动 Runtime",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        startRuntimeButton.Click += async (_, _) => await StartWorkflowAppRuntimeAsync();

        fetchRuntimeHealthButton = new Button
        {
            Text = "读取 Runtime Health",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        fetchRuntimeHealthButton.Click += async (_, _) => await FetchWorkflowAppRuntimeHealthAsync();

        stopRuntimeButton = new Button
        {
            Text = "停止 Runtime",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        stopRuntimeButton.Click += async (_, _) => await StopWorkflowAppRuntimeAsync();

        fetchTriggerSourceHealthButton = new Button
        {
            Text = "读取 TriggerSource Health",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        fetchTriggerSourceHealthButton.Click += async (_, _) => await FetchTriggerSourceHealthAsync();

        enableTriggerSourceButton = new Button
        {
            Text = "启用 TriggerSource",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        enableTriggerSourceButton.Click += async (_, _) => await EnableTriggerSourceAsync();

        disableTriggerSourceButton = new Button
        {
            Text = "停用 TriggerSource",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        disableTriggerSourceButton.Click += async (_, _) => await DisableTriggerSourceAsync();

        invokeButton = new Button
        {
            Text = "调用 TriggerSource",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        invokeButton.Click += async (_, _) => await InvokeTriggerSourceAsync();

        invokeRuntimeButton = new Button
        {
            Text = "调用 App Runtime",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        invokeRuntimeButton.Click += async (_, _) => await InvokeWorkflowRuntimeAsync();

        fetchRunButton = new Button
        {
            Text = "读取 WorkflowRun",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        fetchRunButton.Click += async (_, _) => await FetchWorkflowRunAsync();

        envelopePreviewTextBox = CreateOutputBox();
        requestPreviewTextBox = CreateOutputBox();
        triggerResultTextBox = CreateOutputBox();
        invokeResponseTextBox = CreateOutputBox();
        runtimeHealthTextBox = CreateOutputBox();
        triggerSourceHealthTextBox = CreateOutputBox();
        workflowRunTextBox = CreateOutputBox();
        responseImageInfoTextBox = CreateOutputBox();
        responseImageInfoTextBox.Height = 96;
        responseImageBase64TextBox = CreateOutputBox();
        responseImageBox = new PictureBox
        {
            Dock = DockStyle.Fill,
            SizeMode = PictureBoxSizeMode.Zoom,
            BackColor = Color.WhiteSmoke,
            BorderStyle = BorderStyle.FixedSingle
        };
        copyResponseImageBase64Button = new Button
        {
            Text = "复制 Raw Base64",
            AutoSize = true,
            Padding = new Padding(10, 4, 10, 4),
            Enabled = false
        };
        copyResponseImageBase64Button.Click += (_, _) => CopyResponseImageBase64();
        ClearResponseImagePreview("当前响应未包含可直接预览的 inline-base64 图片。");

        statusLabel = new Label
        {
            AutoSize = true,
            Text = "准备就绪。",
            ForeColor = Color.DarkSlateGray,
            Padding = new Padding(0, 6, 0, 0)
        };

        Controls.Add(BuildRootLayout());
    }

    /// <summary>
    /// 组合页面根布局。
    /// </summary>
    /// <returns>根容器。</returns>
    private Control BuildRootLayout()
    {
        var tabControl = new TabControl
        {
            Dock = DockStyle.Fill
        };
        tabControl.TabPages.Add(CreateTabPage("06 Workflow App", BuildTriggerSourcePage()));
        tabControl.TabPages.Add(CreateTabPage("07 Workflow App", new WorkflowRuntimeDebugPage()));
        return tabControl;
    }

    /// <summary>
    /// 构造 06 TriggerSource 调试页内容。
    /// </summary>
    /// <returns>06 调试页根容器。</returns>
    private Control BuildTriggerSourcePage()
    {
        var rootLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            ColumnCount = 1,
            RowCount = 2,
            Padding = new Padding(10)
        };
        rootLayout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        rootLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));

        rootLayout.Controls.Add(BuildSettingsGroup(), 0, 0);
        rootLayout.Controls.Add(BuildResultTabs(), 0, 1);
        return rootLayout;
    }

    /// <summary>
    /// 构造参数与动作区域。
    /// </summary>
    /// <returns>参数分组控件。</returns>
    private Control BuildSettingsGroup()
    {
        var group = new GroupBox
        {
            Dock = DockStyle.Top,
            Text = "06 Workflow App 调试参数",
            Padding = new Padding(12),
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink
        };

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            ColumnCount = 4,
            RowCount = 11,
            Margin = new Padding(0)
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120F));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50F));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120F));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50F));
        for (var rowIndex = 0; rowIndex < layout.RowCount; rowIndex += 1)
        {
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        }

        AddField(layout, 0, "Endpoint", endpointTextBox, "TriggerSource Id", triggerSourceIdTextBox);
        AddField(layout, 1, "Workflow Runtime Id", workflowRuntimeIdTextBox, "Trigger Input", defaultInputBindingTextBox);
        AddField(layout, 2, "HTTP Input", httpInputBindingTextBox, "Media Type", mediaTypeTextBox);
        AddField(layout, 3, "Timeout(s)", timeoutSecondsInput, "Deployment Id", deploymentInstanceIdTextBox);
        AddField(layout, 4, "Base API URL", baseApiUrlTextBox, "Access Token", accessTokenTextBox);
        AddSingleFieldRow(layout, 5, "Project Id", projectIdTextBox);
        AddField(layout, 6, "Event Id", eventIdTextBox, "Trace Id", traceIdTextBox);
        AddImagePathRow(layout, 7);
        AddJsonRow(layout, 8, "Metadata JSON", metadataJsonTextBox);
        AddJsonRow(layout, 9, "Payload JSON", payloadJsonTextBox);
        AddActionRow(layout, 10);

        group.Controls.Add(layout);
        return group;
    }

    /// <summary>
    /// 构造结果显示 Tab。
    /// </summary>
    /// <returns>结果区域。</returns>
    private Control BuildResultTabs()
    {
        var container = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(0, 10, 0, 0)
        };
        container.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        container.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        container.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));

        var summaryLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            ColumnCount = 6
        };
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 80F));
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 20F));
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110F));
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 40F));
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 80F));
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 40F));
        summaryLayout.Controls.Add(CreateLabel("State"), 0, 0);
        summaryLayout.Controls.Add(stateTextBox, 1, 0);
        summaryLayout.Controls.Add(CreateLabel("WorkflowRun"), 2, 0);
        summaryLayout.Controls.Add(workflowRunIdTextBox, 3, 0);
        summaryLayout.Controls.Add(CreateLabel("Event Id"), 4, 0);
        summaryLayout.Controls.Add(resultEventIdTextBox, 5, 0);

        var tabControl = new TabControl
        {
            Dock = DockStyle.Fill
        };
        tabControl.TabPages.Add(CreateTabPage("Request Envelope", envelopePreviewTextBox));
        tabControl.TabPages.Add(CreateTabPage("Request JSON", requestPreviewTextBox));
        tabControl.TabPages.Add(CreateTabPage("Trigger Result", triggerResultTextBox));
        tabControl.TabPages.Add(CreateTabPage("Invoke Response", invokeResponseTextBox));
        tabControl.TabPages.Add(CreateTabPage("Runtime Health", runtimeHealthTextBox));
        tabControl.TabPages.Add(CreateTabPage("TriggerSource Health", triggerSourceHealthTextBox));
        tabControl.TabPages.Add(CreateTabPage("Workflow Run", workflowRunTextBox));
        tabControl.TabPages.Add(CreateTabPage("Response Image", BuildResponseImageTab()));

        container.Controls.Add(summaryLayout, 0, 0);
        container.Controls.Add(statusLabel, 0, 1);
        container.Controls.Add(tabControl, 0, 2);
        return container;
    }

    /// <summary>
    /// 构造响应图片预览页面。
    /// </summary>
    /// <returns>图片预览页面内容。</returns>
    private Control BuildResponseImageTab()
    {
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(6)
        };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 110F));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
        layout.Controls.Add(responseImageInfoTextBox, 0, 0);
        layout.Controls.Add(BuildResponseImageActionBar(), 0, 1);
        layout.Controls.Add(BuildResponseImageContentTabs(), 0, 2);
        return layout;
    }

    /// <summary>
    /// 构造响应图片内容分页。
    /// </summary>
    /// <returns>图片预览与 Raw Base64 分页。</returns>
    private Control BuildResponseImageContentTabs()
    {
        var tabControl = new TabControl
        {
            Dock = DockStyle.Fill
        };
        tabControl.TabPages.Add(CreateTabPage("Preview", responseImageBox));
        tabControl.TabPages.Add(CreateTabPage("Raw Base64", responseImageBase64TextBox));
        return tabControl;
    }

    /// <summary>
    /// 构造响应图片辅助操作区域。
    /// </summary>
    /// <returns>辅助操作区域。</returns>
    private Control BuildResponseImageActionBar()
    {
        var panel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            WrapContents = false,
            FlowDirection = FlowDirection.LeftToRight,
            Margin = new Padding(0)
        };
        panel.Controls.Add(copyResponseImageBase64Button);
        panel.Controls.Add(new Label
        {
            AutoSize = true,
            Padding = new Padding(8, 8, 0, 0),
            Text = "下方是原始 image_base64 字符串，可直接复制；Trigger Result JSON 页签中的 \\u002B 属于 JSON 转义。"
        });
        return panel;
    }

    /// <summary>
    /// 执行真实 TriggerSource 调用。
    /// </summary>
    private async Task InvokeTriggerSourceAsync()
    {
        SetBusy(true, "正在调用 TriggerSource...");
        workflowRunTextBox.Clear();
        try
        {
            var request = BuildRequest(out var resolvedImagePath);
            using var client = new AmvisionTriggerClient(new AmvisionTriggerClientOptions
            {
                Endpoint = endpointTextBox.Text.Trim(),
                TriggerSourceId = triggerSourceIdTextBox.Text.Trim(),
                DefaultInputBinding = defaultInputBindingTextBox.Text.Trim(),
                Timeout = TimeSpan.FromSeconds(decimal.ToDouble(timeoutSecondsInput.Value))
            });

            var envelope = client.BuildEnvelope(request);
            envelopePreviewTextBox.Text = SerializePretty(envelope);

            var result = await Task.Run(() => client.InvokeImage(request));
            ApplyTriggerResult(result);
            statusLabel.Text = $"调用完成：{Path.GetFileName(resolvedImagePath)} -> {result.State}";
            statusLabel.ForeColor = Color.DarkGreen;
        }
        catch (Exception exception)
        {
            ApplyException(exception);
        }
        finally
        {
            SetBusy(false);
        }
    }

    /// <summary>
    /// 通过 HTTP 调用 06 WorkflowAppRuntime。
    /// </summary>
    private async Task InvokeWorkflowRuntimeAsync()
    {
        SetBusy(true, "正在调用 App Runtime...");
        workflowRunTextBox.Clear();
        try
        {
            using var client = CreateWorkflowClient();
            var request = BuildRuntimeInvokeRequest(out var requestSummary);
            var requestJson = request.ToJson();
            requestPreviewTextBox.Text = FormatJsonIfPossible(requestJson);

            var response = await client.InvokeWorkflowAppRuntimeAsync(RequireWorkflowRuntimeId(), request);
            invokeResponseTextBox.Text = FormatJsonIfPossible(response.Content);
            ApplyRuntimeInvokeResponse(response, requestSummary);
        }
        catch (Exception exception)
        {
            stateTextBox.Text = "failed";
            workflowRunIdTextBox.Text = string.Empty;
            resultEventIdTextBox.Text = string.Empty;
            invokeResponseTextBox.Text = exception.ToString();
            ClearResponseImagePreview("App Runtime 调用失败，当前没有可显示的响应图片。");
            statusLabel.Text = "App Runtime 调用失败。";
            statusLabel.ForeColor = Color.Maroon;
        }
        finally
        {
            SetBusy(false);
        }
    }

    /// <summary>
    /// 通过 REST 查询 WorkflowRun 详情。
    /// </summary>
    private async Task FetchWorkflowRunAsync()
    {
        var workflowRunId = workflowRunIdTextBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(workflowRunId))
        {
            statusLabel.Text = "没有可查询的 workflow_run_id。";
            statusLabel.ForeColor = Color.Maroon;
            return;
        }

        SetBusy(true, "正在读取 WorkflowRun...");
        try
        {
            using var client = CreateWorkflowClient();
            var response = await client.GetWorkflowRunAsync(workflowRunId);
            var content = response.Content;
            workflowRunTextBox.Text = FormatJsonIfPossible(content);
            TryApplyResponseImagePreviewFromWorkflowRun(content);
            statusLabel.Text = response.IsSuccessStatusCode
                ? "WorkflowRun 读取成功。"
                : BuildApiFailureMessage("WorkflowRun 读取失败", response);
            statusLabel.ForeColor = response.IsSuccessStatusCode ? Color.DarkGreen : Color.Maroon;
        }
        catch (Exception exception)
        {
            workflowRunTextBox.Text = exception.ToString();
            statusLabel.Text = "WorkflowRun 读取失败。";
            statusLabel.ForeColor = Color.Maroon;
        }
        finally
        {
            SetBusy(false);
        }
    }

    /// <summary>
    /// 构造真实调用请求并返回解析后的图片路径。
    /// </summary>
    /// <param name="resolvedImagePath">最终使用的图片路径。</param>
    /// <returns>图片调用请求。</returns>
    private ImageTriggerRequest BuildRequest(out string resolvedImagePath)
    {
        resolvedImagePath = ResolveImagePath(imagePathTextBox.Text.Trim());
        var mediaType = ResolveMediaType(resolvedImagePath, mediaTypeTextBox.Text.Trim());
        var request = new ImageTriggerRequest
        {
            ImageBytes = File.ReadAllBytes(resolvedImagePath),
            MediaType = mediaType
        };

        var eventId = eventIdTextBox.Text.Trim();
        if (!string.IsNullOrWhiteSpace(eventId))
        {
            request.EventId = eventId;
        }

        var traceId = traceIdTextBox.Text.Trim();
        if (!string.IsNullOrWhiteSpace(traceId))
        {
            request.TraceId = traceId;
        }

        foreach (var pair in ParseJsonObject(metadataJsonTextBox.Text))
        {
            request.Metadata[pair.Key] = pair.Value;
        }

        request.Metadata.TryAdd("source", "winforms-debugger");

        foreach (var pair in ParseJsonObject(payloadJsonTextBox.Text))
        {
            request.Payload[pair.Key] = pair.Value;
        }

        var deploymentInstanceId = deploymentInstanceIdTextBox.Text.Trim();
        if (!string.IsNullOrWhiteSpace(deploymentInstanceId))
        {
            request.Payload["deployment_request"] = new Dictionary<string, object?>
            {
                ["value"] = new Dictionary<string, object?>
                {
                    ["deployment_instance_id"] = deploymentInstanceId
                }
            };
        }

        return request;
    }

    /// <summary>
    /// 构造 06 WorkflowAppRuntime HTTP invoke 请求。
    /// </summary>
    /// <param name="requestSummary">请求摘要。</param>
    /// <returns>SDK invoke 请求对象。</returns>
    private WorkflowRuntimeInvokeRequest BuildRuntimeInvokeRequest(out string requestSummary)
    {
        var httpInputBinding = httpInputBindingTextBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(httpInputBinding))
        {
            throw new InvalidOperationException("HTTP Input 不能为空。\n");
        }

        var resolvedImagePath = ResolveImagePath(imagePathTextBox.Text.Trim());
        var mediaType = ResolveMediaType(resolvedImagePath, mediaTypeTextBox.Text.Trim());
        var request = new WorkflowRuntimeInvokeRequest
        {
            TimeoutSeconds = decimal.ToInt32(timeoutSecondsInput.Value)
        };
        request.InputBindings[httpInputBinding] = new Dictionary<string, object?>
        {
            ["image_base64"] = Convert.ToBase64String(File.ReadAllBytes(resolvedImagePath)),
            ["media_type"] = mediaType
        };

        foreach (var pair in ParseJsonObject(metadataJsonTextBox.Text))
        {
            request.ExecutionMetadata[pair.Key] = pair.Value;
        }

        var deploymentInstanceId = deploymentInstanceIdTextBox.Text.Trim();
        if (!string.IsNullOrWhiteSpace(deploymentInstanceId))
        {
            request.InputBindings["deployment_request"] = new Dictionary<string, object?>
            {
                ["value"] = new Dictionary<string, object?>
                {
                    ["deployment_instance_id"] = deploymentInstanceId
                }
            };
        }

        requestSummary = Path.GetFileName(resolvedImagePath);
        return request;
    }

    /// <summary>
    /// 把成功结果写入界面。
    /// </summary>
    /// <param name="result">SDK 返回的 TriggerResult。</param>
    private void ApplyTriggerResult(TriggerResult result)
    {
        stateTextBox.Text = result.State;
        workflowRunIdTextBox.Text = result.WorkflowRunId ?? string.Empty;
        resultEventIdTextBox.Text = result.EventId;
        triggerResultTextBox.Text = SerializePretty(new
        {
            format_id = result.FormatId,
            trigger_source_id = result.TriggerSourceId,
            event_id = result.EventId,
            state = result.State,
            workflow_run_id = result.WorkflowRunId,
            response_payload = result.ResponsePayload,
            error_message = result.ErrorMessage,
            metadata = result.Metadata
        });
        TryApplyResponseImagePreviewFromTriggerResult(result);
    }

    /// <summary>
    /// 把 HTTP runtime invoke 响应写回界面。
    /// </summary>
    /// <param name="response">SDK HTTP 响应。</param>
    /// <param name="requestSummary">请求摘要。</param>
    private void ApplyRuntimeInvokeResponse(AmvisionWorkflowApiResponse response, string requestSummary)
    {
        if (!response.IsSuccessStatusCode)
        {
            stateTextBox.Text = "http-error";
            workflowRunIdTextBox.Text = string.Empty;
            resultEventIdTextBox.Text = string.Empty;
            ClearResponseImagePreview("Invoke 返回了 HTTP 错误，当前没有可显示的响应图片。\n可继续读取 Runtime Health 查看 runtime 是否仍保持 running。");
            statusLabel.Text = BuildApiFailureMessage("App Runtime 调用失败", response);
            statusLabel.ForeColor = Color.Maroon;
            return;
        }

        using var document = JsonDocument.Parse(response.Content);
        var root = document.RootElement;
        stateTextBox.Text = TryReadStringProperty(root, "state");
        workflowRunIdTextBox.Text = TryReadStringProperty(root, "workflow_run_id");
        resultEventIdTextBox.Text = string.Empty;
        ClearResponseImagePreview("当前响应未包含可直接预览的 inline-base64 图片。");
        TryApplyResponseImagePreviewFromWorkflowRun(response.Content);
        statusLabel.Text = $"App Runtime 调用完成：{requestSummary} -> {stateTextBox.Text}";
        statusLabel.ForeColor = string.Equals(stateTextBox.Text, "failed", StringComparison.OrdinalIgnoreCase)
            ? Color.DarkGoldenrod
            : Color.DarkGreen;
    }

    /// <summary>
    /// 把异常写入界面。
    /// </summary>
    /// <param name="exception">调用异常。</param>
    private void ApplyException(Exception exception)
    {
        stateTextBox.Text = "failed";
        workflowRunIdTextBox.Text = string.Empty;
        resultEventIdTextBox.Text = string.Empty;
        if (exception is AmvisionTriggerException triggerException)
        {
            triggerResultTextBox.Text = SerializePretty(new
            {
                error_code = triggerException.ErrorCode,
                error_message = triggerException.Message,
                details = triggerException.Details
            });
        }
        else
        {
            triggerResultTextBox.Text = exception.ToString();
        }

        ClearResponseImagePreview("调用失败，当前没有可显示的响应图片。");

        statusLabel.Text = "调用失败，请检查 TriggerSource 响应和参数。";
        statusLabel.ForeColor = Color.Maroon;
    }

    /// <summary>
    /// 启动当前 workflow runtime。
    /// </summary>
    private Task StartWorkflowAppRuntimeAsync()
    {
        return ExecuteWorkflowClientActionAsync(
            outputBox: runtimeHealthTextBox,
            busyMessage: "正在启动 WorkflowAppRuntime...",
            successMessage: "WorkflowAppRuntime 已启动。",
            action: client => client.StartWorkflowAppRuntimeAsync(RequireWorkflowRuntimeId())
        );
    }

    /// <summary>
    /// 停止当前 workflow runtime。
    /// </summary>
    private Task StopWorkflowAppRuntimeAsync()
    {
        return ExecuteWorkflowClientActionAsync(
            outputBox: runtimeHealthTextBox,
            busyMessage: "正在停止 WorkflowAppRuntime...",
            successMessage: "WorkflowAppRuntime 已停止。",
            action: client => client.StopWorkflowAppRuntimeAsync(RequireWorkflowRuntimeId())
        );
    }

    /// <summary>
    /// 读取当前 workflow runtime health。
    /// </summary>
    private Task FetchWorkflowAppRuntimeHealthAsync()
    {
        return ExecuteWorkflowClientActionAsync(
            outputBox: runtimeHealthTextBox,
            busyMessage: "正在读取 WorkflowAppRuntime Health...",
            successMessage: "WorkflowAppRuntime Health 读取成功。",
            action: client => client.GetWorkflowAppRuntimeHealthAsync(RequireWorkflowRuntimeId())
        );
    }

    /// <summary>
    /// 读取当前 trigger source health。
    /// </summary>
    private Task FetchTriggerSourceHealthAsync()
    {
        return ExecuteWorkflowClientActionAsync(
            outputBox: triggerSourceHealthTextBox,
            busyMessage: "正在读取 TriggerSource Health...",
            successMessage: "TriggerSource Health 读取成功。",
            action: client => client.GetTriggerSourceHealthAsync(RequireTriggerSourceId())
        );
    }

    /// <summary>
    /// 启用当前 trigger source。
    /// </summary>
    private Task EnableTriggerSourceAsync()
    {
        return ExecuteWorkflowClientActionAsync(
            outputBox: triggerSourceHealthTextBox,
            busyMessage: "正在启用 TriggerSource...",
            successMessage: "TriggerSource 已启用。",
            action: client => client.EnableTriggerSourceAsync(RequireTriggerSourceId())
        );
    }

    /// <summary>
    /// 停用当前 trigger source。
    /// </summary>
    private Task DisableTriggerSourceAsync()
    {
        return ExecuteWorkflowClientActionAsync(
            outputBox: triggerSourceHealthTextBox,
            busyMessage: "正在停用 TriggerSource...",
            successMessage: "TriggerSource 已停用。",
            action: client => client.DisableTriggerSourceAsync(RequireTriggerSourceId())
        );
    }

    /// <summary>
    /// 执行 Workflow SDK 控制面动作。
    /// </summary>
    /// <param name="outputBox">结果输出框。</param>
    /// <param name="busyMessage">进行中提示。</param>
    /// <param name="successMessage">成功提示。</param>
    /// <param name="action">SDK 动作。</param>
    private async Task ExecuteWorkflowClientActionAsync(
        RichTextBox outputBox,
        string busyMessage,
        string successMessage,
        Func<AmvisionWorkflowClient, Task<AmvisionWorkflowApiResponse>> action)
    {
        SetBusy(true, busyMessage);
        try
        {
            using var client = CreateWorkflowClient();
            var response = await action(client);
            outputBox.Text = FormatJsonIfPossible(response.Content);
            statusLabel.Text = response.IsSuccessStatusCode
                ? successMessage
                : BuildApiFailureMessage(successMessage.Replace("成功。", "失败"), response);
            statusLabel.ForeColor = response.IsSuccessStatusCode ? Color.DarkGreen : Color.Maroon;
        }
        catch (Exception exception)
        {
            outputBox.Text = exception.ToString();
            statusLabel.Text = busyMessage.Replace("正在", string.Empty).TrimEnd('.').TrimEnd('。') + "失败。";
            statusLabel.ForeColor = Color.Maroon;
        }
        finally
        {
            SetBusy(false);
        }
    }

    /// <summary>
    /// 清空当前图片预览。
    /// </summary>
    /// <param name="message">提示信息。</param>
    private void ClearResponseImagePreview(string message)
    {
        ReplaceResponsePreviewImage(null);
        responseImageInfoTextBox.Text = message;
        SetResponseImageBase64(null);
    }

    /// <summary>
    /// 使用 TriggerResult 中的 annotated_image 更新预览。
    /// </summary>
    /// <param name="result">SDK 返回的 TriggerResult。</param>
    private void TryApplyResponseImagePreviewFromTriggerResult(TriggerResult result)
    {
        if (TryExtractAnnotatedImageFromTriggerResult(result, out var imagePayload))
        {
            if (TryDecodeInlineBase64Image(imagePayload, out var image, out var infoText, out var base64Text))
            {
                ReplaceResponsePreviewImage(image);
                SetResponseImageBase64(base64Text);
                responseImageInfoTextBox.Text = string.Join(
                    Environment.NewLine,
                    new[]
                    {
                        "来源：Trigger Result.response_payload",
                        infoText,
                        "下方 Raw Base64 为可直接复制的原始字符串。"
                    }
                );
                return;
            }

            ReplaceResponsePreviewImage(null);
            SetResponseImageBase64(base64Text);
            responseImageInfoTextBox.Text = string.Join(
                Environment.NewLine,
                new[]
                {
                    "来源：Trigger Result.response_payload",
                    infoText,
                    string.IsNullOrWhiteSpace(base64Text)
                        ? "当前响应包含图片字段，但未返回可直接显示的 image_base64。"
                        : "已提取原始 image_base64，但本地图片解码失败；可直接复制下方 Raw Base64 继续排查。"
                }
            );
            return;
        }

        ClearResponseImagePreview("Trigger Result 当前没有 annotated_image。\n如果需要排查节点输出，可再读取 WorkflowRun。");
    }

    /// <summary>
    /// 尝试使用 WorkflowRun JSON 中的 annotated_image 更新预览。
    /// </summary>
    /// <param name="workflowRunContent">WorkflowRun 响应 JSON 文本。</param>
    private void TryApplyResponseImagePreviewFromWorkflowRun(string workflowRunContent)
    {
        if (string.IsNullOrWhiteSpace(workflowRunContent))
        {
            return;
        }

        try
        {
            using var document = JsonDocument.Parse(workflowRunContent);
            if (!TryExtractAnnotatedImageFromWorkflowRun(document.RootElement, out var imagePayload))
            {
                return;
            }

            if (TryDecodeInlineBase64Image(imagePayload, out var image, out var infoText, out var base64Text))
            {
                ReplaceResponsePreviewImage(image);
                SetResponseImageBase64(base64Text);
                responseImageInfoTextBox.Text = string.Join(
                    Environment.NewLine,
                    new[]
                    {
                        "来源：WorkflowRun.outputs",
                        infoText,
                        "下方 Raw Base64 为可直接复制的原始字符串。"
                    }
                );
            }
        }
        catch (JsonException)
        {
        }
    }

    /// <summary>
    /// 从 TriggerResult 中提取 annotated_image payload。
    /// </summary>
    /// <param name="result">SDK 返回结果。</param>
    /// <param name="imagePayload">提取到的图片 payload。</param>
    /// <returns>是否成功提取。</returns>
    private static bool TryExtractAnnotatedImageFromTriggerResult(
        TriggerResult result,
        out JsonElement imagePayload)
    {
        if (result.ResponsePayload.TryGetValue("result", out var resultElement)
            && TryExtractAnnotatedImageFromResponse(resultElement, out imagePayload))
        {
            return true;
        }

        if (result.ResponsePayload.TryGetValue("outputs", out var outputsElement)
            && outputsElement.ValueKind == JsonValueKind.Object
            && outputsElement.TryGetProperty("http_response", out var responseElement)
            && TryExtractAnnotatedImageFromResponse(responseElement, out imagePayload))
        {
            return true;
        }

        imagePayload = default;
        return false;
    }

    /// <summary>
    /// 从 WorkflowRun JSON 中提取 annotated_image payload。
    /// </summary>
    /// <param name="workflowRunRoot">WorkflowRun JSON 根元素。</param>
    /// <param name="imagePayload">提取到的图片 payload。</param>
    /// <returns>是否成功提取。</returns>
    private static bool TryExtractAnnotatedImageFromWorkflowRun(
        JsonElement workflowRunRoot,
        out JsonElement imagePayload)
    {
        if (workflowRunRoot.ValueKind == JsonValueKind.Object
            && workflowRunRoot.TryGetProperty("outputs", out var outputsElement)
            && outputsElement.ValueKind == JsonValueKind.Object
            && outputsElement.TryGetProperty("http_response", out var responseElement)
            && TryExtractAnnotatedImageFromResponse(responseElement, out imagePayload))
        {
            return true;
        }

        imagePayload = default;
        return false;
    }

    /// <summary>
    /// 从标准 response 对象中提取 annotated_image 或 image payload。
    /// </summary>
    /// <param name="responseRoot">标准 response 对象。</param>
    /// <param name="imagePayload">提取到的图片 payload。</param>
    /// <returns>是否成功提取。</returns>
    private static bool TryExtractAnnotatedImageFromResponse(
        JsonElement responseRoot,
        out JsonElement imagePayload)
    {
        if (responseRoot.ValueKind != JsonValueKind.Object)
        {
            imagePayload = default;
            return false;
        }

        if (responseRoot.TryGetProperty("body", out var bodyElement)
            && bodyElement.ValueKind == JsonValueKind.Object)
        {
            if (bodyElement.TryGetProperty("data", out var dataElement)
                && dataElement.ValueKind == JsonValueKind.Object
                && dataElement.TryGetProperty("annotated_image", out imagePayload))
            {
                imagePayload = UnwrapImagePayload(imagePayload);
                return true;
            }

            if (bodyElement.TryGetProperty("image", out imagePayload))
            {
                imagePayload = UnwrapImagePayload(imagePayload);
                return true;
            }
        }

        if (responseRoot.TryGetProperty("data", out var fallbackDataElement)
            && fallbackDataElement.ValueKind == JsonValueKind.Object
            && fallbackDataElement.TryGetProperty("annotated_image", out imagePayload))
        {
            imagePayload = UnwrapImagePayload(imagePayload);
            return true;
        }

        if (responseRoot.TryGetProperty("image", out imagePayload))
        {
            imagePayload = UnwrapImagePayload(imagePayload);
            return true;
        }

        imagePayload = default;
        return false;
    }

    /// <summary>
    /// 兼容 image-preview body，统一返回真正的图片 payload。
    /// </summary>
    /// <param name="candidate">候选元素。</param>
    /// <returns>解包后的图片 payload。</returns>
    private static JsonElement UnwrapImagePayload(JsonElement candidate)
    {
        if (candidate.ValueKind == JsonValueKind.Object
            && !candidate.TryGetProperty("transport_kind", out _)
            && candidate.TryGetProperty("image", out var nestedImage)
            && nestedImage.ValueKind == JsonValueKind.Object)
        {
            return nestedImage;
        }

        return candidate;
    }

    /// <summary>
    /// 尝试把 inline-base64 图片 payload 解码成可显示图片。
    /// </summary>
    /// <param name="imagePayload">图片 payload。</param>
    /// <param name="image">解码后的图片。</param>
    /// <param name="infoText">图片信息摘要。</param>
    /// <param name="base64Text">提取到的原始 base64 字符串。</param>
    /// <returns>是否成功解码。</returns>
    private static bool TryDecodeInlineBase64Image(
        JsonElement imagePayload,
        out Image? image,
        out string infoText,
        out string? base64Text)
    {
        image = null;
        infoText = string.Empty;
        base64Text = null;
        if (imagePayload.ValueKind != JsonValueKind.Object)
        {
            return false;
        }

        var transportKind = TryReadStringProperty(imagePayload, "transport_kind");
        var mediaType = TryReadStringProperty(imagePayload, "media_type");
        var width = TryReadIntProperty(imagePayload, "width");
        var height = TryReadIntProperty(imagePayload, "height");
        infoText = string.Join(
            Environment.NewLine,
            new[]
            {
                $"transport_kind: {transportKind}",
                $"media_type: {mediaType}",
                width is null || height is null ? "size: unknown" : $"size: {width} x {height}"
            }
        );
        if (!string.Equals(transportKind, "inline-base64", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (!imagePayload.TryGetProperty("image_base64", out var base64Element)
            || base64Element.ValueKind != JsonValueKind.String)
        {
            return false;
        }

        base64Text = base64Element.GetString();
        if (string.IsNullOrWhiteSpace(base64Text))
        {
            return false;
        }

        infoText = string.Join(
            Environment.NewLine,
            new[]
            {
                infoText,
                $"base64_length: {base64Text.Length}"
            }
        );

        try
        {
            var imageBytes = Convert.FromBase64String(base64Text);
            using var memoryStream = new MemoryStream(imageBytes);
            using var decodedImage = Image.FromStream(memoryStream);
            image = new Bitmap(decodedImage);
            infoText = string.Join(
                Environment.NewLine,
                new[]
                {
                    infoText,
                    $"bytes: {imageBytes.Length}"
                }
            );
            return true;
        }
        catch (FormatException)
        {
            return false;
        }
        catch (ArgumentException)
        {
            return false;
        }
    }

    /// <summary>
    /// 更新原始 base64 文本框与复制按钮状态。
    /// </summary>
    /// <param name="base64Text">原始 base64 字符串。</param>
    private void SetResponseImageBase64(string? base64Text)
    {
        responseImageBase64TextBox.Text = base64Text ?? string.Empty;
        copyResponseImageBase64Button.Enabled = !string.IsNullOrWhiteSpace(base64Text);
    }

    /// <summary>
    /// 复制当前原始 base64 字符串。
    /// </summary>
    private void CopyResponseImageBase64()
    {
        var base64Text = responseImageBase64TextBox.Text;
        if (string.IsNullOrWhiteSpace(base64Text))
        {
            statusLabel.Text = "当前没有可复制的原始 image_base64。";
            statusLabel.ForeColor = Color.Maroon;
            return;
        }

        Clipboard.SetText(base64Text);
        statusLabel.Text = "已复制原始 image_base64。";
        statusLabel.ForeColor = Color.DarkGreen;
    }

    /// <summary>
    /// 替换当前预览图片并释放旧资源。
    /// </summary>
    /// <param name="image">新的预览图片。</param>
    private void ReplaceResponsePreviewImage(Image? image)
    {
        var previousImage = responseImageBox.Image;
        responseImageBox.Image = image;
        previousImage?.Dispose();
    }

    /// <summary>
    /// 读取 JSON 对象中的字符串字段。
    /// </summary>
    /// <param name="root">JSON 对象。</param>
    /// <param name="propertyName">字段名。</param>
    /// <returns>字段字符串值；不存在时返回空字符串。</returns>
    private static string TryReadStringProperty(JsonElement root, string propertyName)
    {
        return root.TryGetProperty(propertyName, out var property)
            && property.ValueKind == JsonValueKind.String
            ? property.GetString() ?? string.Empty
            : string.Empty;
    }

    /// <summary>
    /// 读取 JSON 对象中的整数字段。
    /// </summary>
    /// <param name="root">JSON 对象。</param>
    /// <param name="propertyName">字段名。</param>
    /// <returns>字段整数值；不存在时返回空。</returns>
    private static int? TryReadIntProperty(JsonElement root, string propertyName)
    {
        return root.TryGetProperty(propertyName, out var property)
            && property.ValueKind == JsonValueKind.Number
            && property.TryGetInt32(out var value)
            ? value
            : null;
    }

    /// <summary>
    /// 设置页面忙闲状态。
    /// </summary>
    /// <param name="busy">是否忙碌。</param>
    /// <param name="message">忙碌提示。</param>
    private void SetBusy(bool busy, string? message = null)
    {
        UseWaitCursor = busy;
        startRuntimeButton.Enabled = !busy;
        fetchRuntimeHealthButton.Enabled = !busy;
        stopRuntimeButton.Enabled = !busy;
        fetchTriggerSourceHealthButton.Enabled = !busy;
        enableTriggerSourceButton.Enabled = !busy;
        disableTriggerSourceButton.Enabled = !busy;
        invokeButton.Enabled = !busy;
        invokeRuntimeButton.Enabled = !busy;
        fetchRunButton.Enabled = !busy;
        if (!string.IsNullOrWhiteSpace(message))
        {
            statusLabel.Text = message;
            statusLabel.ForeColor = Color.DarkSlateGray;
        }
    }

    /// <summary>
    /// 创建标准文本框。
    /// </summary>
    private static TextBox CreateTextBox(string text)
    {
        return new TextBox
        {
            Dock = DockStyle.Fill,
            Text = text
        };
    }

    /// <summary>
    /// 创建只读文本框。
    /// </summary>
    private static TextBox CreateReadOnlyTextBox()
    {
        return new TextBox
        {
            Dock = DockStyle.Fill,
            ReadOnly = true,
            BackColor = Color.White
        };
    }

    /// <summary>
    /// 创建 JSON 输入框。
    /// </summary>
    private static RichTextBox CreateJsonBox(string text)
    {
        return new RichTextBox
        {
            Dock = DockStyle.Fill,
            Height = 90,
            Font = new Font("Consolas", 9F, FontStyle.Regular, GraphicsUnit.Point),
            WordWrap = false,
            Text = text
        };
    }

    /// <summary>
    /// 创建结果输出框。
    /// </summary>
    private static RichTextBox CreateOutputBox()
    {
        return new RichTextBox
        {
            Dock = DockStyle.Fill,
            ReadOnly = true,
            Font = new Font("Consolas", 9F, FontStyle.Regular, GraphicsUnit.Point),
            WordWrap = false,
            BackColor = Color.White
        };
    }

    /// <summary>
    /// 创建表单标签。
    /// </summary>
    private static Label CreateLabel(string text)
    {
        return new Label
        {
            Text = text,
            AutoSize = true,
            Anchor = AnchorStyles.Left,
            Padding = new Padding(0, 6, 0, 0)
        };
    }

    /// <summary>
    /// 添加一行双列字段。
    /// </summary>
    private static void AddField(
        TableLayoutPanel layout,
        int rowIndex,
        string leftLabel,
        Control leftControl,
        string rightLabel,
        Control rightControl)
    {
        layout.Controls.Add(CreateLabel(leftLabel), 0, rowIndex);
        layout.Controls.Add(leftControl, 1, rowIndex);
        layout.Controls.Add(CreateLabel(rightLabel), 2, rowIndex);
        layout.Controls.Add(rightControl, 3, rowIndex);
    }

    /// <summary>
    /// 添加图片路径和浏览按钮。
    /// </summary>
    private void AddImagePathRow(TableLayoutPanel layout, int rowIndex)
    {
        var pathPanel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            Margin = new Padding(0)
        };
        pathPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        pathPanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));

        var browseButton = new Button
        {
            Text = "选择图片",
            AutoSize = true,
            Margin = new Padding(8, 0, 0, 0)
        };
        browseButton.Click += (_, _) =>
        {
            if (imageFileDialog.ShowDialog(this) == DialogResult.OK)
            {
                imagePathTextBox.Text = imageFileDialog.FileName;
                if (string.IsNullOrWhiteSpace(mediaTypeTextBox.Text))
                {
                    mediaTypeTextBox.Text = GuessMediaType(imageFileDialog.FileName);
                }
            }
        };

        pathPanel.Controls.Add(imagePathTextBox, 0, 0);
        pathPanel.Controls.Add(browseButton, 1, 0);

        layout.Controls.Add(CreateLabel("Image Path"), 0, rowIndex);
        layout.Controls.Add(pathPanel, 1, rowIndex);
        layout.SetColumnSpan(pathPanel, 3);
    }

    /// <summary>
    /// 添加 JSON 多行输入。
    /// </summary>
    private static void AddJsonRow(TableLayoutPanel layout, int rowIndex, string label, Control control)
    {
        layout.Controls.Add(CreateLabel(label), 0, rowIndex);
        layout.Controls.Add(control, 1, rowIndex);
        layout.SetColumnSpan(control, 3);
    }

    /// <summary>
    /// 添加单字段整行输入。
    /// </summary>
    private static void AddSingleFieldRow(TableLayoutPanel layout, int rowIndex, string label, Control control)
    {
        layout.Controls.Add(CreateLabel(label), 0, rowIndex);
        layout.Controls.Add(control, 1, rowIndex);
        layout.SetColumnSpan(control, 3);
    }

    /// <summary>
    /// 添加操作按钮和提示。
    /// </summary>
    private void AddActionRow(TableLayoutPanel layout, int rowIndex)
    {
        var actionsPanel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            WrapContents = true,
            FlowDirection = FlowDirection.LeftToRight,
            Margin = new Padding(0)
        };
        actionsPanel.Controls.Add(startRuntimeButton);
        actionsPanel.Controls.Add(fetchRuntimeHealthButton);
        actionsPanel.Controls.Add(stopRuntimeButton);
        actionsPanel.Controls.Add(fetchTriggerSourceHealthButton);
        actionsPanel.Controls.Add(enableTriggerSourceButton);
        actionsPanel.Controls.Add(disableTriggerSourceButton);
        actionsPanel.Controls.Add(invokeButton);
        actionsPanel.Controls.Add(invokeRuntimeButton);
        actionsPanel.Controls.Add(fetchRunButton);

        var helperLabel = new Label
        {
            AutoSize = true,
            Padding = new Padding(16, 10, 0, 0),
            Text = "06 页保留和 07 相同的控制按钮：runtime start/stop/health、HTTP invoke、trigger source enable/disable/health、ZeroMQ invoke 和 WorkflowRun 读取。"
        };
        actionsPanel.Controls.Add(helperLabel);

        layout.Controls.Add(actionsPanel, 1, rowIndex);
        layout.SetColumnSpan(actionsPanel, 3);
    }

    /// <summary>
    /// 创建 Tab 页面。
    /// </summary>
    private static TabPage CreateTabPage(string title, Control content)
    {
        var page = new TabPage(title);
        page.Controls.Add(content);
        return page;
    }

    /// <summary>
    /// 解析 JSON object 文本为字典。
    /// </summary>
    /// <param name="text">JSON 文本。</param>
    /// <returns>解析后的对象字典。</returns>
    private static Dictionary<string, object?> ParseJsonObject(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return new Dictionary<string, object?>();
        }

        using var document = JsonDocument.Parse(text);
        if (document.RootElement.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidOperationException("JSON 输入必须是 object。\n");
        }

        var values = new Dictionary<string, object?>();
        foreach (var property in document.RootElement.EnumerateObject())
        {
            values[property.Name] = property.Value.Clone();
        }

        return values;
    }

    /// <summary>
    /// 尝试把对象格式化为易读 JSON。
    /// </summary>
    /// <param name="value">待序列化对象。</param>
    /// <returns>格式化文本。</returns>
    private static string SerializePretty(object value)
    {
        return JsonSerializer.Serialize(value, PrettyJsonOptions);
    }

    /// <summary>
    /// 尝试格式化字符串中的 JSON 内容。
    /// </summary>
    /// <param name="text">待格式化文本。</param>
    /// <returns>格式化后的文本。</returns>
    private static string FormatJsonIfPossible(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return string.Empty;
        }

        try
        {
            using var document = JsonDocument.Parse(text);
            return JsonSerializer.Serialize(document.RootElement, PrettyJsonOptions);
        }
        catch (JsonException)
        {
            return text;
        }
    }

    /// <summary>
    /// 解析图片路径，支持仓库内样例文件快捷路径。
    /// </summary>
    /// <param name="imagePath">用户输入路径。</param>
    /// <returns>可读取的绝对或相对路径。</returns>
    private static string ResolveImagePath(string imagePath)
    {
        if (File.Exists(imagePath))
        {
            return imagePath;
        }

        var fileName = Path.GetFileName(imagePath);
        if (!string.IsNullOrWhiteSpace(fileName) && string.IsNullOrWhiteSpace(Path.GetDirectoryName(imagePath)))
        {
            var workspaceSamplePath = Path.Combine(
                Environment.CurrentDirectory,
                "data",
                "files",
                "validation-inputs",
                fileName
            );
            if (File.Exists(workspaceSamplePath))
            {
                return workspaceSamplePath;
            }
        }

        throw new FileNotFoundException(
            $"找不到图片文件：{imagePath}。当前工作目录：{Environment.CurrentDirectory}。"
        );
    }

    /// <summary>
    /// 解析 media type，空值时按扩展名猜测。
    /// </summary>
    /// <param name="imagePath">图片路径。</param>
    /// <param name="mediaType">用户输入 media type。</param>
    /// <returns>最终 media type。</returns>
    private static string ResolveMediaType(string imagePath, string mediaType)
    {
        return string.IsNullOrWhiteSpace(mediaType) ? GuessMediaType(imagePath) : mediaType;
    }

    /// <summary>
    /// 创建当前页面使用的 Workflow 控制面 SDK client。
    /// </summary>
    /// <returns>SDK client。</returns>
    private AmvisionWorkflowClient CreateWorkflowClient()
    {
        return new AmvisionWorkflowClient(new AmvisionWorkflowClientOptions
        {
            BaseApiUrl = baseApiUrlTextBox.Text.Trim(),
            AccessToken = accessTokenTextBox.Text.Trim(),
            Timeout = TimeSpan.FromSeconds(decimal.ToDouble(timeoutSecondsInput.Value))
        });
    }

    /// <summary>
    /// 获取必填 workflow runtime id。
    /// </summary>
    /// <returns>workflow runtime id。</returns>
    private string RequireWorkflowRuntimeId()
    {
        var workflowRuntimeId = workflowRuntimeIdTextBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(workflowRuntimeId))
        {
            throw new InvalidOperationException("Workflow Runtime Id 不能为空。\n");
        }

        return workflowRuntimeId;
    }

    /// <summary>
    /// 获取必填 trigger source id。
    /// </summary>
    /// <returns>trigger source id。</returns>
    private string RequireTriggerSourceId()
    {
        var triggerSourceId = triggerSourceIdTextBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(triggerSourceId))
        {
            throw new InvalidOperationException("TriggerSource Id 不能为空。\n");
        }

        return triggerSourceId;
    }

    /// <summary>
    /// 构造统一的 SDK HTTP 失败提示。
    /// </summary>
    /// <param name="prefix">提示前缀。</param>
    /// <param name="response">HTTP 响应。</param>
    /// <returns>状态栏提示。</returns>
    private static string BuildApiFailureMessage(string prefix, AmvisionWorkflowApiResponse response)
    {
        var errorText = response.ErrorCode ?? string.Empty;
        if (!string.IsNullOrWhiteSpace(response.ErrorMessage))
        {
            errorText = string.IsNullOrWhiteSpace(errorText)
                ? response.ErrorMessage
                : $"{errorText} {response.ErrorMessage}";
        }

        return string.IsNullOrWhiteSpace(errorText)
            ? $"{prefix}：HTTP {(int)response.StatusCode}"
            : $"{prefix}：HTTP {(int)response.StatusCode} {errorText}";
    }

    /// <summary>
    /// 根据文件扩展名推断 media type。
    /// </summary>
    /// <param name="path">图片路径。</param>
    /// <returns>media type。</returns>
    private static string GuessMediaType(string path)
    {
        return Path.GetExtension(path).ToLowerInvariant() switch
        {
            ".jpg" or ".jpeg" => "image/jpeg",
            ".png" => "image/png",
            ".bmp" => "image/bmp",
            _ => "image/octet-stream"
        };
    }
}