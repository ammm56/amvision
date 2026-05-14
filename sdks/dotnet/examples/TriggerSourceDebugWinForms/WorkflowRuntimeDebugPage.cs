using System.Text.Json;
using System.Windows.Forms;
using Amvision.TriggerSources;

namespace TriggerSourceDebugWinForms;

internal sealed class WorkflowRuntimeDebugPage : UserControl
{
    private static readonly JsonSerializerOptions PrettyJsonOptions = new()
    {
        WriteIndented = true
    };

    private readonly TextBox baseApiUrlTextBox;
    private readonly TextBox endpointTextBox;
    private readonly TextBox triggerSourceIdTextBox;
    private readonly TextBox defaultInputBindingTextBox;
    private readonly TextBox workflowRuntimeIdTextBox;
    private readonly TextBox inputBindingTextBox;
    private readonly TextBox imagePathTextBox;
    private readonly TextBox mediaTypeTextBox;
    private readonly NumericUpDown timeoutSecondsInput;
    private readonly TextBox principalIdTextBox;
    private readonly TextBox projectIdTextBox;
    private readonly TextBox scopesTextBox;
    private readonly TextBox eventIdTextBox;
    private readonly TextBox traceIdTextBox;
    private readonly RichTextBox metadataJsonTextBox;
    private readonly RichTextBox requestOverrideJsonTextBox;
    private readonly TextBox runStateTextBox;
    private readonly TextBox workflowRunIdTextBox;
    private readonly TextBox observedStateTextBox;
    private readonly Button startRuntimeButton;
    private readonly Button fetchHealthButton;
    private readonly Button fetchTriggerSourceHealthButton;
    private readonly Button enableTriggerSourceButton;
    private readonly Button disableTriggerSourceButton;
    private readonly Button invokeRuntimeButton;
    private readonly Button invokeTriggerSourceButton;
    private readonly Button fetchRunButton;
    private readonly Button stopRuntimeButton;
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
    /// 初始化 07 App Runtime HTTP 调试页。
    /// </summary>
    public WorkflowRuntimeDebugPage()
    {
        Dock = DockStyle.Fill;
        Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular, GraphicsUnit.Point);

        imageFileDialog = new OpenFileDialog
        {
            Title = "选择 07 调试图片",
            Filter = "Image Files|*.jpg;*.jpeg;*.png;*.bmp|All Files|*.*"
        };

        baseApiUrlTextBox = CreateTextBox("http://127.0.0.1:8000");
        endpointTextBox = CreateTextBox("tcp://127.0.0.1:5556");
        triggerSourceIdTextBox = CreateTextBox("zeromq-trigger-source-07");
        defaultInputBindingTextBox = CreateTextBox("request_image");
        workflowRuntimeIdTextBox = CreateTextBox(string.Empty);
        inputBindingTextBox = CreateTextBox("request_image_base64");
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
        principalIdTextBox = CreateTextBox("user-1");
        projectIdTextBox = CreateTextBox("project-1");
        scopesTextBox = CreateTextBox("workflows:read,workflows:write");
        eventIdTextBox = CreateTextBox(string.Empty);
        traceIdTextBox = CreateTextBox(string.Empty);
        metadataJsonTextBox = CreateJsonBox("{\n  \"scenario\": \"opencv-process-save-image-zeromq\",\n  \"trigger_source\": \"sync-api\",\n  \"source\": \"winforms-runtime-debugger\"\n}");
        requestOverrideJsonTextBox = CreateJsonBox(string.Empty);

        runStateTextBox = CreateReadOnlyTextBox();
        workflowRunIdTextBox = CreateReadOnlyTextBox();
        observedStateTextBox = CreateReadOnlyTextBox();

        startRuntimeButton = new Button
        {
            Text = "启动 Runtime",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        startRuntimeButton.Click += async (_, _) => await StartRuntimeAsync();

        fetchHealthButton = new Button
        {
            Text = "读取 Runtime Health",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        fetchHealthButton.Click += async (_, _) => await FetchRuntimeHealthAsync();

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

        invokeRuntimeButton = new Button
        {
            Text = "调用 App Runtime",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        invokeRuntimeButton.Click += async (_, _) => await InvokeWorkflowRuntimeAsync();

        invokeTriggerSourceButton = new Button
        {
            Text = "调用 TriggerSource",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        invokeTriggerSourceButton.Click += async (_, _) => await InvokeTriggerSourceAsync();

        fetchRunButton = new Button
        {
            Text = "读取 WorkflowRun",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        fetchRunButton.Click += async (_, _) => await FetchWorkflowRunAsync();

        stopRuntimeButton = new Button
        {
            Text = "停止 Runtime",
            AutoSize = true,
            Padding = new Padding(10, 6, 10, 6)
        };
        stopRuntimeButton.Click += async (_, _) => await StopRuntimeAsync();

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
        ClearResponseImagePreview("当前 07 响应还没有可直接预览的 inline-base64 图片。storage-ref 输出会在这里显示摘要。\n如需排查失败输入，可先看 Invoke Response 和 Runtime Health 页签。");

        statusLabel = new Label
        {
            AutoSize = true,
            Text = "07 App Runtime 调试页准备就绪。",
            ForeColor = Color.DarkSlateGray,
            Padding = new Padding(0, 6, 0, 0)
        };

        Controls.Add(BuildRootLayout());
    }

    /// <summary>
    /// 构造页面根布局。
    /// </summary>
    /// <returns>根容器。</returns>
    private Control BuildRootLayout()
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
    /// 构造 07 调试参数区域。
    /// </summary>
    /// <returns>参数分组控件。</returns>
    private Control BuildSettingsGroup()
    {
        var group = new GroupBox
        {
            Dock = DockStyle.Top,
            Text = "07 Workflow App 调试参数",
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
        AddField(layout, 1, "Base API URL", baseApiUrlTextBox, "Workflow Runtime Id", workflowRuntimeIdTextBox);
        AddField(layout, 2, "Trigger Input", defaultInputBindingTextBox, "HTTP Input", inputBindingTextBox);
        AddField(layout, 3, "Media Type", mediaTypeTextBox, "Timeout(s)", timeoutSecondsInput);
        AddField(layout, 4, "Principal Id", principalIdTextBox, "Project Id", projectIdTextBox);
        AddField(layout, 5, "Scopes", scopesTextBox, "Event Id", eventIdTextBox);
        AddSingleFieldRow(layout, 6, "Trace Id", traceIdTextBox);
        AddImagePathRow(layout, 7);
        AddJsonRow(layout, 8, "Execution Metadata JSON", metadataJsonTextBox);
        AddJsonRow(layout, 9, "Request Override JSON", requestOverrideJsonTextBox);
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
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90F));
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 25F));
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110F));
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 40F));
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110F));
        summaryLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 35F));
        summaryLayout.Controls.Add(CreateLabel("Run State"), 0, 0);
        summaryLayout.Controls.Add(runStateTextBox, 1, 0);
        summaryLayout.Controls.Add(CreateLabel("WorkflowRun"), 2, 0);
        summaryLayout.Controls.Add(workflowRunIdTextBox, 3, 0);
        summaryLayout.Controls.Add(CreateLabel("Runtime State"), 4, 0);
        summaryLayout.Controls.Add(observedStateTextBox, 5, 0);

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
    /// 构造响应图片页。
    /// </summary>
    /// <returns>图片页内容。</returns>
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
    /// 构造响应图片子分页。
    /// </summary>
    /// <returns>图片分页。</returns>
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
    /// 构造响应图片辅助操作区。
    /// </summary>
    /// <returns>辅助操作控件。</returns>
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
            Text = "07 返回 storage-ref 时这里会显示 object_key 摘要；inline-base64 图片会直接预览并可复制原始 image_base64。"
        });
        return panel;
    }

    /// <summary>
    /// 调用 07 App Runtime invoke。
    /// </summary>
    private async Task InvokeWorkflowRuntimeAsync()
    {
        SetBusy(true, "正在调用 07 App Runtime...");
        workflowRunTextBox.Clear();
        runtimeHealthTextBox.Clear();
        try
        {
            using var client = CreateWorkflowClient();

            string requestJson;
            string requestSummary;
            AmvisionWorkflowApiResponse response;
            var requestOverrideText = requestOverrideJsonTextBox.Text.Trim();
            if (!string.IsNullOrWhiteSpace(requestOverrideText))
            {
                var request = WorkflowRuntimeInvokeRequest.Parse(requestOverrideText);
                requestJson = request.ToJson();
                requestSummary = "Request Override JSON";
                response = await client.InvokeWorkflowAppRuntimeAsync(RequireWorkflowRuntimeId(), request);
            }
            else
            {
                var request = BuildImageInvokeRequest(out requestSummary);
                requestJson = request.ToWorkflowRuntimeInvokeRequest().ToJson();
                response = await client.InvokeWorkflowAppRuntimeWithImageBase64Async(RequireWorkflowRuntimeId(), request);
            }

            requestPreviewTextBox.Text = requestJson;
            invokeResponseTextBox.Text = FormatJsonIfPossible(response.Content);
            ApplyInvokeResponse(response, requestSummary);
        }
        catch (Exception exception)
        {
            ApplyException(exception, invokeResponseTextBox, "07 App Runtime 调用失败。", setRunStateFailed: true);
            ClearResponseImagePreview("调用失败，当前没有可显示的响应图片。");
        }
        finally
        {
            SetBusy(false);
        }
    }

    /// <summary>
    /// 读取 07 Runtime health。
    /// </summary>
    private async Task FetchRuntimeHealthAsync()
    {
        await ExecuteWorkflowClientActionAsync(
            outputBox: runtimeHealthTextBox,
            updateObservedState: true,
            progressMessage: "正在读取 07 Runtime Health...",
            successMessage: "07 Runtime Health 读取成功。",
            action: client => client.GetWorkflowAppRuntimeHealthAsync(RequireWorkflowRuntimeId())
        );
    }

    /// <summary>
    /// 启动 07 Runtime。
    /// </summary>
    private async Task StartRuntimeAsync()
    {
        await ExecuteWorkflowClientActionAsync(
            outputBox: runtimeHealthTextBox,
            updateObservedState: true,
            progressMessage: "正在启动 07 Runtime...",
            successMessage: "07 Runtime 启动完成。",
            action: client => client.StartWorkflowAppRuntimeAsync(RequireWorkflowRuntimeId())
        );
    }

    /// <summary>
    /// 停止 07 Runtime。
    /// </summary>
    private async Task StopRuntimeAsync()
    {
        await ExecuteWorkflowClientActionAsync(
            outputBox: runtimeHealthTextBox,
            updateObservedState: true,
            progressMessage: "正在停止 07 Runtime...",
            successMessage: "07 Runtime 停止完成。",
            action: client => client.StopWorkflowAppRuntimeAsync(RequireWorkflowRuntimeId())
        );
    }

    /// <summary>
    /// 读取 07 TriggerSource health。
    /// </summary>
    private async Task FetchTriggerSourceHealthAsync()
    {
        await ExecuteWorkflowClientActionAsync(
            outputBox: triggerSourceHealthTextBox,
            updateObservedState: false,
            progressMessage: "正在读取 07 TriggerSource Health...",
            successMessage: "07 TriggerSource Health 读取成功。",
            action: client => client.GetTriggerSourceHealthAsync(RequireTriggerSourceId())
        );
    }

    /// <summary>
    /// 启用 07 TriggerSource。
    /// </summary>
    private async Task EnableTriggerSourceAsync()
    {
        await ExecuteWorkflowClientActionAsync(
            outputBox: triggerSourceHealthTextBox,
            updateObservedState: false,
            progressMessage: "正在启用 07 TriggerSource...",
            successMessage: "07 TriggerSource 已启用。",
            action: client => client.EnableTriggerSourceAsync(RequireTriggerSourceId())
        );
    }

    /// <summary>
    /// 停用 07 TriggerSource。
    /// </summary>
    private async Task DisableTriggerSourceAsync()
    {
        await ExecuteWorkflowClientActionAsync(
            outputBox: triggerSourceHealthTextBox,
            updateObservedState: false,
            progressMessage: "正在停用 07 TriggerSource...",
            successMessage: "07 TriggerSource 已停用。",
            action: client => client.DisableTriggerSourceAsync(RequireTriggerSourceId())
        );
    }

    /// <summary>
    /// 通过 ZeroMQ 调用 07 TriggerSource。
    /// </summary>
    private async Task InvokeTriggerSourceAsync()
    {
        SetBusy(true, "正在调用 07 TriggerSource...");
        workflowRunTextBox.Clear();
        try
        {
            var request = BuildTriggerRequest(out var resolvedImagePath);
            using var client = new AmvisionTriggerClient(new AmvisionTriggerClientOptions
            {
                Endpoint = endpointTextBox.Text.Trim(),
                TriggerSourceId = RequireTriggerSourceId(),
                DefaultInputBinding = defaultInputBindingTextBox.Text.Trim(),
                Timeout = TimeSpan.FromSeconds(decimal.ToDouble(timeoutSecondsInput.Value))
            });

            var envelope = client.BuildEnvelope(request);
            envelopePreviewTextBox.Text = SerializePretty(envelope);

            var result = await Task.Run(() => client.InvokeImage(request));
            ApplyTriggerResult(result);
            statusLabel.Text = $"07 TriggerSource 调用完成：{Path.GetFileName(resolvedImagePath)} -> {result.State}";
            statusLabel.ForeColor = Color.DarkGreen;
        }
        catch (Exception exception)
        {
            ApplyTriggerException(exception);
        }
        finally
        {
            SetBusy(false);
        }
    }

    /// <summary>
    /// 读取当前 workflow_run_id 对应的 WorkflowRun。
    /// </summary>
    private async Task FetchWorkflowRunAsync()
    {
        var workflowRunId = workflowRunIdTextBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(workflowRunId))
        {
            statusLabel.Text = "当前没有可读取的 workflow_run_id。";
            statusLabel.ForeColor = Color.Maroon;
            return;
        }

        SetBusy(true, "正在读取 07 WorkflowRun...");
        try
        {
            using var client = CreateWorkflowClient();
            var response = await client.GetWorkflowRunAsync(workflowRunId);
            var content = response.Content;
            workflowRunTextBox.Text = FormatJsonIfPossible(content);
            TryApplyResponseImagePreviewFromWorkflowRunLikeContent(content, "WorkflowRun.outputs");
            statusLabel.Text = response.IsSuccessStatusCode
                ? "07 WorkflowRun 读取成功。"
                : BuildApiFailureMessage("07 WorkflowRun 读取失败", response);
            statusLabel.ForeColor = response.IsSuccessStatusCode ? Color.DarkGreen : Color.Maroon;
        }
        catch (Exception exception)
        {
            ApplyException(exception, workflowRunTextBox, "07 WorkflowRun 读取失败。", setRunStateFailed: false);
        }
        finally
        {
            SetBusy(false);
        }
    }

    /// <summary>
    /// 执行 Workflow SDK 控制面请求。
    /// </summary>
    /// <param name="outputBox">目标输出框。</param>
    /// <param name="updateObservedState">是否尝试刷新 observed_state。</param>
    /// <param name="progressMessage">进行中提示。</param>
    /// <param name="successMessage">成功提示。</param>
    /// <param name="action">SDK 动作。</param>
    private async Task ExecuteWorkflowClientActionAsync(
        RichTextBox outputBox,
        bool updateObservedState,
        string progressMessage,
        string successMessage,
        Func<AmvisionWorkflowClient, Task<AmvisionWorkflowApiResponse>> action)
    {
        SetBusy(true, progressMessage);
        try
        {
            using var client = CreateWorkflowClient();
            var response = await action(client);
            var content = response.Content;
            outputBox.Text = FormatJsonIfPossible(content);
            if (updateObservedState && TryReadRuntimeObservedState(content, out var observedState))
            {
                observedStateTextBox.Text = observedState;
            }

            statusLabel.Text = response.IsSuccessStatusCode
                ? successMessage
                : BuildApiFailureMessage(successMessage.Replace("成功。", "失败"), response);
            statusLabel.ForeColor = response.IsSuccessStatusCode ? Color.DarkGreen : Color.Maroon;
        }
        catch (Exception exception)
        {
            ApplyException(exception, outputBox, "07 控制面请求失败。", setRunStateFailed: false);
        }
        finally
        {
            SetBusy(false);
        }
    }

    /// <summary>
    /// 构造 ZeroMQ TriggerSource 调用请求。
    /// </summary>
    /// <param name="resolvedImagePath">最终使用的图片路径。</param>
    /// <returns>TriggerSource 图片请求。</returns>
    private ImageTriggerRequest BuildTriggerRequest(out string resolvedImagePath)
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

        request.Metadata.TryAdd("source", "winforms-runtime-debugger");
        return request;
    }

    /// <summary>
    /// 根据当前图片输入生成 image-base64 invoke 请求。
    /// </summary>
    /// <param name="requestSummary">请求摘要，用于状态栏显示。</param>
    /// <returns>SDK image invoke 请求对象。</returns>
    private WorkflowRuntimeImageInvokeRequest BuildImageInvokeRequest(out string requestSummary)
    {
        var bindingId = inputBindingTextBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(bindingId))
        {
            throw new InvalidOperationException("Input Binding 不能为空。\n");
        }

        var resolvedImagePath = ResolveImagePath(imagePathTextBox.Text.Trim());
        var mediaType = ResolveMediaType(resolvedImagePath, mediaTypeTextBox.Text.Trim());
        var request = new WorkflowRuntimeImageInvokeRequest
        {
            ImageBytes = File.ReadAllBytes(resolvedImagePath),
            InputBinding = bindingId,
            MediaType = mediaType,
            TimeoutSeconds = decimal.ToInt32(timeoutSecondsInput.Value)
        };

        foreach (var pair in ParseJsonObject(metadataJsonTextBox.Text))
        {
            request.ExecutionMetadata[pair.Key] = pair.Value;
        }

        requestSummary = Path.GetFileName(resolvedImagePath);
        return request;
    }

    /// <summary>
    /// 把 invoke 响应写回界面。
    /// </summary>
    /// <param name="response">SDK HTTP 响应。</param>
    /// <param name="requestSummary">请求摘要。</param>
    private void ApplyInvokeResponse(AmvisionWorkflowApiResponse response, string requestSummary)
    {
        if (!response.IsSuccessStatusCode)
        {
            runStateTextBox.Text = "http-error";
            workflowRunIdTextBox.Text = string.Empty;
            ClearResponseImagePreview("Invoke 返回了 HTTP 错误，当前没有可显示的响应图片。\n可继续读取 Runtime Health 查看 runtime 是否仍保持 running。\n如果需要手工构造异常输入，可在上方 Request Override JSON 中直接编辑请求体。");
            statusLabel.Text = BuildApiFailureMessage("07 App Runtime 调用失败", response);
            statusLabel.ForeColor = Color.Maroon;
            return;
        }

        var content = response.Content;
        using var document = JsonDocument.Parse(content);
        var root = document.RootElement;
        runStateTextBox.Text = TryReadStringProperty(root, "state");
        workflowRunIdTextBox.Text = TryReadStringProperty(root, "workflow_run_id");
        TryApplyResponseImagePreviewFromWorkflowRunLikeContent(content, "Invoke Response.outputs");
        statusLabel.Text = $"07 App Runtime 调用完成：{requestSummary} -> {runStateTextBox.Text}";
        statusLabel.ForeColor = string.Equals(runStateTextBox.Text, "failed", StringComparison.OrdinalIgnoreCase)
            ? Color.DarkGoldenrod
            : Color.DarkGreen;
    }

    /// <summary>
    /// 把 TriggerSource 返回结果写回界面。
    /// </summary>
    /// <param name="result">SDK TriggerResult。</param>
    private void ApplyTriggerResult(TriggerResult result)
    {
        runStateTextBox.Text = result.State;
        workflowRunIdTextBox.Text = result.WorkflowRunId ?? string.Empty;
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
    /// 把 TriggerSource 调用异常写回界面。
    /// </summary>
    /// <param name="exception">异常对象。</param>
    private void ApplyTriggerException(Exception exception)
    {
        runStateTextBox.Text = "failed";
        workflowRunIdTextBox.Text = string.Empty;
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

        ClearResponseImagePreview("07 TriggerSource 调用失败，当前没有可显示的响应图片。");
        statusLabel.Text = "07 TriggerSource 调用失败。";
        statusLabel.ForeColor = Color.Maroon;
    }

    /// <summary>
    /// 尝试使用 TriggerResult 中的图片结果更新预览。
    /// </summary>
    /// <param name="result">SDK TriggerResult。</param>
    private void TryApplyResponseImagePreviewFromTriggerResult(TriggerResult result)
    {
        if (!TryExtractImageFromTriggerResult(result, out var imagePayload))
        {
            ClearResponseImagePreview("Trigger Result 当前没有 image 或 annotated_image。\n如果需要排查节点输出，可再读取 WorkflowRun。");
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
                BuildImageSummaryText(imagePayload, infoText),
                string.IsNullOrWhiteSpace(base64Text)
                    ? "当前响应包含图片字段，但未返回可直接显示的 image_base64。"
                    : "已提取原始 image_base64，但本地图片解码失败；可直接复制下方 Raw Base64 继续排查。"
            }
        );
    }

    /// <summary>
    /// 从 WorkflowRun 结构响应中提取图片并更新预览。
    /// </summary>
    /// <param name="content">响应 JSON 文本。</param>
    /// <param name="sourceLabel">信息面板中的来源标签。</param>
    private void TryApplyResponseImagePreviewFromWorkflowRunLikeContent(string content, string sourceLabel)
    {
        if (string.IsNullOrWhiteSpace(content))
        {
            return;
        }

        try
        {
            using var document = JsonDocument.Parse(content);
            if (!TryExtractImageFromWorkflowRunLikePayload(document.RootElement, out var imagePayload))
            {
                ClearResponseImagePreview($"{sourceLabel} 当前没有 image 或 annotated_image 输出。\n如果本次返回的是参数错误，可直接看 Invoke Response 中的 error_details。\n如果返回 storage-ref，这里会展示 object_key 摘要而不会直接拉取文件。\n");
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
                        $"来源：{sourceLabel}",
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
                    $"来源：{sourceLabel}",
                    BuildImageSummaryText(imagePayload, infoText),
                    string.IsNullOrWhiteSpace(base64Text)
                        ? "当前图片输出不是 inline-base64，通常表示 07 返回的是 storage-ref 或只返回了图片摘要。"
                        : "已提取原始 image_base64，但本地图片解码失败；可复制下方 Raw Base64 继续排查。"
                }
            );
        }
        catch (JsonException)
        {
        }
    }

    /// <summary>
    /// 清空响应图片预览。
    /// </summary>
    /// <param name="message">提示信息。</param>
    private void ClearResponseImagePreview(string message)
    {
        ReplaceResponsePreviewImage(null);
        responseImageInfoTextBox.Text = message;
        SetResponseImageBase64(null);
    }

    /// <summary>
    /// 更新 Raw Base64 文本框与复制按钮状态。
    /// </summary>
    /// <param name="base64Text">原始 base64 文本。</param>
    private void SetResponseImageBase64(string? base64Text)
    {
        responseImageBase64TextBox.Text = base64Text ?? string.Empty;
        copyResponseImageBase64Button.Enabled = !string.IsNullOrWhiteSpace(base64Text);
    }

    /// <summary>
    /// 复制当前 Raw Base64。
    /// </summary>
    private void CopyResponseImageBase64()
    {
        var base64Text = responseImageBase64TextBox.Text;
        if (string.IsNullOrWhiteSpace(base64Text))
        {
            statusLabel.Text = "当前没有可复制的 image_base64。";
            statusLabel.ForeColor = Color.Maroon;
            return;
        }

        Clipboard.SetText(base64Text);
        statusLabel.Text = "已复制 07 响应中的原始 image_base64。";
        statusLabel.ForeColor = Color.DarkGreen;
    }

    /// <summary>
    /// 替换当前图片预览。
    /// </summary>
    /// <param name="image">新的图片对象。</param>
    private void ReplaceResponsePreviewImage(Image? image)
    {
        var previousImage = responseImageBox.Image;
        responseImageBox.Image = image;
        previousImage?.Dispose();
    }

    /// <summary>
    /// 把异常写入指定输出框。
    /// </summary>
    /// <param name="exception">异常对象。</param>
    /// <param name="outputBox">目标输出框。</param>
    /// <param name="statusMessage">状态栏消息。</param>
    /// <param name="setRunStateFailed">是否将 runState 置为 failed。</param>
    private void ApplyException(
        Exception exception,
        RichTextBox outputBox,
        string statusMessage,
        bool setRunStateFailed)
    {
        if (setRunStateFailed)
        {
            runStateTextBox.Text = "failed";
            workflowRunIdTextBox.Text = string.Empty;
        }

        outputBox.Text = exception.ToString();
        statusLabel.Text = statusMessage;
        statusLabel.ForeColor = Color.Maroon;
    }

    /// <summary>
    /// 从 TriggerResult 中提取图片 payload。
    /// </summary>
    /// <param name="result">SDK TriggerResult。</param>
    /// <param name="imagePayload">提取到的图片 payload。</param>
    /// <returns>是否成功提取。</returns>
    private static bool TryExtractImageFromTriggerResult(TriggerResult result, out JsonElement imagePayload)
    {
        if (result.ResponsePayload.TryGetValue("result", out var resultElement)
            && TryExtractImageFromResponse(resultElement, out imagePayload))
        {
            return true;
        }

        if (result.ResponsePayload.TryGetValue("outputs", out var outputsElement)
            && outputsElement.ValueKind == JsonValueKind.Object
            && outputsElement.TryGetProperty("http_response", out var responseElement)
            && TryExtractImageFromResponse(responseElement, out imagePayload))
        {
            return true;
        }

        imagePayload = default;
        return false;
    }

    /// <summary>
    /// 设置页面忙闲状态。
    /// </summary>
    /// <param name="busy">是否忙碌。</param>
    /// <param name="message">状态栏消息。</param>
    private void SetBusy(bool busy, string? message = null)
    {
        UseWaitCursor = busy;
        startRuntimeButton.Enabled = !busy;
        fetchHealthButton.Enabled = !busy;
        fetchTriggerSourceHealthButton.Enabled = !busy;
        enableTriggerSourceButton.Enabled = !busy;
        disableTriggerSourceButton.Enabled = !busy;
        invokeRuntimeButton.Enabled = !busy;
        invokeTriggerSourceButton.Enabled = !busy;
        fetchRunButton.Enabled = !busy;
        stopRuntimeButton.Enabled = !busy;
        copyResponseImageBase64Button.Enabled = !busy && !string.IsNullOrWhiteSpace(responseImageBase64TextBox.Text);
        if (!string.IsNullOrWhiteSpace(message))
        {
            statusLabel.Text = message;
            statusLabel.ForeColor = Color.DarkSlateGray;
        }
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
    /// <param name="layout">目标布局。</param>
    /// <param name="rowIndex">目标行号。</param>
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
    /// <param name="layout">目标布局。</param>
    /// <param name="rowIndex">目标行号。</param>
    /// <param name="label">字段标签。</param>
    /// <param name="control">字段控件。</param>
    private static void AddJsonRow(TableLayoutPanel layout, int rowIndex, string label, Control control)
    {
        layout.Controls.Add(CreateLabel(label), 0, rowIndex);
        layout.Controls.Add(control, 1, rowIndex);
        layout.SetColumnSpan(control, 3);
    }

    /// <summary>
    /// 添加单字段整行输入。
    /// </summary>
    /// <param name="layout">目标布局。</param>
    /// <param name="rowIndex">目标行号。</param>
    /// <param name="label">字段标签。</param>
    /// <param name="control">字段控件。</param>
    private static void AddSingleFieldRow(TableLayoutPanel layout, int rowIndex, string label, Control control)
    {
        layout.Controls.Add(CreateLabel(label), 0, rowIndex);
        layout.Controls.Add(control, 1, rowIndex);
        layout.SetColumnSpan(control, 3);
    }

    /// <summary>
    /// 添加帮助说明行。
    /// </summary>
    /// <param name="layout">目标布局。</param>
    /// <param name="rowIndex">目标行号。</param>
    private static void AddHelperRow(TableLayoutPanel layout, int rowIndex)
    {
        var helperLabel = new Label
        {
            AutoSize = true,
            Padding = new Padding(0, 6, 0, 0),
            Text = "Request Override JSON 非空时会直接按原文发送，可用于复现缺字段、坏 base64 或坏图片 bytes 等 07 参数错误。"
        };
        layout.Controls.Add(helperLabel, 1, rowIndex);
        layout.SetColumnSpan(helperLabel, 3);
    }

    /// <summary>
    /// 添加操作按钮行。
    /// </summary>
    /// <param name="layout">目标布局。</param>
    /// <param name="rowIndex">目标行号。</param>
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
        actionsPanel.Controls.Add(fetchHealthButton);
        actionsPanel.Controls.Add(stopRuntimeButton);
        actionsPanel.Controls.Add(invokeRuntimeButton);
        actionsPanel.Controls.Add(fetchTriggerSourceHealthButton);
        actionsPanel.Controls.Add(enableTriggerSourceButton);
        actionsPanel.Controls.Add(disableTriggerSourceButton);
        actionsPanel.Controls.Add(invokeTriggerSourceButton);
        actionsPanel.Controls.Add(fetchRunButton);

        var helperLabel = new Label
        {
            AutoSize = true,
            Padding = new Padding(16, 10, 0, 0),
            Text = "07 页保留和 06 相同的控制按钮：runtime start/stop/health、HTTP invoke、trigger source enable/disable/health、ZeroMQ invoke 和 WorkflowRun 读取。"
        };
        actionsPanel.Controls.Add(helperLabel);

        layout.Controls.Add(actionsPanel, 1, rowIndex);
        layout.SetColumnSpan(actionsPanel, 3);
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
            PrincipalId = principalIdTextBox.Text.Trim(),
            ProjectIds = projectIdTextBox.Text.Trim(),
            Scopes = scopesTextBox.Text.Trim(),
            Timeout = TimeSpan.FromSeconds(decimal.ToDouble(timeoutSecondsInput.Value))
        });
    }

    /// <summary>
    /// 读取并校验 workflow_runtime_id。
    /// </summary>
    /// <returns>规范化后的 runtime id。</returns>
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
    /// 读取并校验 trigger_source_id。
    /// </summary>
    /// <returns>规范化后的 trigger source id。</returns>
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
    /// 从 runtime 响应中读取 observed_state。
    /// </summary>
    /// <param name="content">响应文本。</param>
    /// <param name="observedState">读取到的 observed_state。</param>
    /// <returns>是否成功读取。</returns>
    private static bool TryReadRuntimeObservedState(string content, out string observedState)
    {
        observedState = string.Empty;
        if (string.IsNullOrWhiteSpace(content))
        {
            return false;
        }

        try
        {
            using var document = JsonDocument.Parse(content);
            observedState = TryReadStringProperty(document.RootElement, "observed_state");
            return !string.IsNullOrWhiteSpace(observedState);
        }
        catch (JsonException)
        {
            return false;
        }
    }

    /// <summary>
    /// 从 WorkflowRun 风格 JSON 中提取图片 payload。
    /// </summary>
    /// <param name="root">JSON 根元素。</param>
    /// <param name="imagePayload">提取到的图片 payload。</param>
    /// <returns>是否成功提取。</returns>
    private static bool TryExtractImageFromWorkflowRunLikePayload(JsonElement root, out JsonElement imagePayload)
    {
        if (root.ValueKind == JsonValueKind.Object
            && root.TryGetProperty("outputs", out var outputsElement)
            && outputsElement.ValueKind == JsonValueKind.Object
            && outputsElement.TryGetProperty("http_response", out var responseElement)
            && TryExtractImageFromResponse(responseElement, out imagePayload))
        {
            return true;
        }

        imagePayload = default;
        return false;
    }

    /// <summary>
    /// 从标准 response 对象中提取 image 或 annotated_image。
    /// </summary>
    /// <param name="responseRoot">response JSON。</param>
    /// <param name="imagePayload">提取到的图片 payload。</param>
    /// <returns>是否成功提取。</returns>
    private static bool TryExtractImageFromResponse(JsonElement responseRoot, out JsonElement imagePayload)
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

        if (responseRoot.TryGetProperty("image", out imagePayload))
        {
            imagePayload = UnwrapImagePayload(imagePayload);
            return true;
        }

        imagePayload = default;
        return false;
    }

    /// <summary>
    /// 兼容 image-preview body 包裹结构。
    /// </summary>
    /// <param name="candidate">候选元素。</param>
    /// <returns>真正的图片 payload。</returns>
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
    /// 尝试把 inline-base64 图片解码为可显示对象。
    /// </summary>
    /// <param name="imagePayload">图片 payload。</param>
    /// <param name="image">解码后的图片对象。</param>
    /// <param name="infoText">图片摘要信息。</param>
    /// <param name="base64Text">提取到的原始 base64 文本。</param>
    /// <returns>是否成功解码。</returns>
    private static bool TryDecodeInlineBase64Image(
        JsonElement imagePayload,
        out Image? image,
        out string infoText,
        out string? base64Text)
    {
        image = null;
        base64Text = null;
        infoText = BuildImageSummaryText(imagePayload, string.Empty);
        if (imagePayload.ValueKind != JsonValueKind.Object)
        {
            return false;
        }

        var transportKind = TryReadStringProperty(imagePayload, "transport_kind");
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
    /// 构造图片 payload 摘要文本。
    /// </summary>
    /// <param name="imagePayload">图片 payload。</param>
    /// <param name="fallback">追加的补充文本。</param>
    /// <returns>摘要文本。</returns>
    private static string BuildImageSummaryText(JsonElement imagePayload, string fallback)
    {
        var lines = new List<string>
        {
            $"transport_kind: {TryReadStringProperty(imagePayload, "transport_kind")}",
            $"media_type: {TryReadStringProperty(imagePayload, "media_type")}",
        };
        var width = TryReadIntProperty(imagePayload, "width");
        var height = TryReadIntProperty(imagePayload, "height");
        lines.Add(width is null || height is null ? "size: unknown" : $"size: {width} x {height}");
        var objectKey = TryReadStringProperty(imagePayload, "object_key");
        if (!string.IsNullOrWhiteSpace(objectKey))
        {
            lines.Add($"object_key: {objectKey}");
        }

        if (!string.IsNullOrWhiteSpace(fallback))
        {
            lines.Add(fallback);
        }

        return string.Join(Environment.NewLine, lines);
    }

    /// <summary>
    /// 读取 JSON 字符串字段。
    /// </summary>
    /// <param name="root">JSON 根对象。</param>
    /// <param name="propertyName">字段名。</param>
    /// <returns>字段字符串值。</returns>
    private static string TryReadStringProperty(JsonElement root, string propertyName)
    {
        return root.TryGetProperty(propertyName, out var property)
            && property.ValueKind == JsonValueKind.String
            ? property.GetString() ?? string.Empty
            : string.Empty;
    }

    /// <summary>
    /// 读取 JSON 整数字段。
    /// </summary>
    /// <param name="root">JSON 根对象。</param>
    /// <param name="propertyName">字段名。</param>
    /// <returns>字段整数值。</returns>
    private static int? TryReadIntProperty(JsonElement root, string propertyName)
    {
        return root.TryGetProperty(propertyName, out var property)
            && property.ValueKind == JsonValueKind.Number
            && property.TryGetInt32(out var value)
            ? value
            : null;
    }

    /// <summary>
    /// 校验并格式化 JSON object 文本。
    /// </summary>
    /// <param name="text">原始 JSON 文本。</param>
    /// <returns>格式化后的 JSON 文本。</returns>
    private static string NormalizeJsonObjectText(string text)
    {
        using var document = JsonDocument.Parse(text);
        if (document.RootElement.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidOperationException("JSON 输入必须是 object。\n");
        }

        return JsonSerializer.Serialize(document.RootElement, PrettyJsonOptions);
    }

    /// <summary>
    /// 解析 JSON object 文本为字典。
    /// </summary>
    /// <param name="text">JSON 文本。</param>
    /// <returns>对象字典。</returns>
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
    /// 尝试格式化文本中的 JSON。
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
    /// 把对象序列化为格式化 JSON。
    /// </summary>
    /// <param name="value">待序列化对象。</param>
    /// <returns>格式化后的 JSON 文本。</returns>
    private static string SerializePretty(object value)
    {
        return JsonSerializer.Serialize(value, PrettyJsonOptions);
    }

    /// <summary>
    /// 解析图片路径，支持仓库样例图片快捷名。
    /// </summary>
    /// <param name="imagePath">用户输入路径。</param>
    /// <returns>可读取路径。</returns>
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

        throw new FileNotFoundException($"找不到图片文件：{imagePath}。当前工作目录：{Environment.CurrentDirectory}。");
    }

    /// <summary>
    /// 解析 media type，空值时按扩展名推断。
    /// </summary>
    /// <param name="imagePath">图片路径。</param>
    /// <param name="mediaType">用户输入 media type。</param>
    /// <returns>最终 media type。</returns>
    private static string ResolveMediaType(string imagePath, string mediaType)
    {
        return string.IsNullOrWhiteSpace(mediaType) ? GuessMediaType(imagePath) : mediaType;
    }

    /// <summary>
    /// 根据扩展名猜测 media type。
    /// </summary>
    /// <param name="path">文件路径。</param>
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

    /// <summary>
    /// 创建标准文本框。
    /// </summary>
    /// <param name="text">默认文本。</param>
    /// <returns>标准文本框。</returns>
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
    /// <returns>只读文本框。</returns>
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
    /// <param name="text">默认文本。</param>
    /// <returns>JSON 输入框。</returns>
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
    /// <returns>输出框。</returns>
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
    /// <param name="text">标签文本。</param>
    /// <returns>标签控件。</returns>
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
    /// 创建 Tab 页面。
    /// </summary>
    /// <param name="title">标题。</param>
    /// <param name="content">页面内容。</param>
    /// <returns>Tab 页面。</returns>
    private static TabPage CreateTabPage(string title, Control content)
    {
        var page = new TabPage(title);
        page.Controls.Add(content);
        return page;
    }
}