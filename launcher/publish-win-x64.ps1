param(
    [string]$WebView2Directory,
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $WebView2Directory) { $WebView2Directory = Join-Path $repository 'runtimes/third_party/webview2/win-x64' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot 'bin/publish/win-x64' }
$WebView2Directory = [IO.Path]::GetFullPath($WebView2Directory)
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
if (-not $OutputDirectory.StartsWith($PSScriptRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '开发发布输出必须位于 launcher 项目目录内。' }
if (-not (Test-Path -LiteralPath (Join-Path $WebView2Directory 'msedgewebview2.exe'))) { throw '缺少 Fixed Version WebView2，参数必须指向含 msedgewebview2.exe 的目录。' }
if (Test-Path -LiteralPath $OutputDirectory) { throw '输出目录已存在，请指定新的空目录，防止把旧文件混入发行包。' }
# staging 只在本脚本限定目录中生成，完成后清理。
$temporaryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'obj/publish'))
$staging = Join-Path $temporaryRoot ('publish-' + [Guid]::NewGuid().ToString('N'))
try {
    $payload = Join-Path $staging 'launcher'
    dotnet publish (Join-Path $PSScriptRoot 'src/Amvar.Launcher.Desktop/Amvar.Launcher.Desktop.csproj') -c Release -r win-x64 --self-contained true -p:LauncherLayout=true -o $payload
    if ($LASTEXITCODE -ne 0) { throw '启动器发布失败。' }
    $webviewTarget = Join-Path $payload 'tools/webview2/win-x64'
    New-Item -ItemType Directory -Force -Path $webviewTarget | Out-Null
    Get-ChildItem -LiteralPath $WebView2Directory -Force | Copy-Item -Destination $webviewTarget -Recurse
    Copy-Item -LiteralPath (Join-Path $repository 'LICENSE') -Destination (Join-Path $payload 'launcher-LICENSE.txt')
    # 由 C# 强类型模型和 Newtonsoft.Json 生成构建信息及带摘要的文件清单。
    $metadata = Start-Process -FilePath (Join-Path $staging 'amvar.launcher.exe') -ArgumentList '--write-release-manifest' -WindowStyle Hidden -PassThru -Wait
    if ($metadata.ExitCode -ne 0) { throw '发行清单生成失败。' }
    New-Item -ItemType Directory -Force -Path (Split-Path $OutputDirectory) | Out-Null
    Move-Item -LiteralPath $staging -Destination $OutputDirectory
    $settingsDirectory = Join-Path $OutputDirectory 'launcher/config'
    New-Item -ItemType Directory -Force -Path $settingsDirectory | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'config/launcher.example.json') -Destination (Join-Path $settingsDirectory 'launcher.json')
    Write-Output "启动器发行目录：$OutputDirectory"
} finally {
    $resolvedStaging = [IO.Path]::GetFullPath($staging)
    if (-not $resolvedStaging.StartsWith($temporaryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '临时目录越界。' }
    if (Test-Path -LiteralPath $resolvedStaging) { Remove-Item -LiteralPath $resolvedStaging -Recurse -Force }
}
