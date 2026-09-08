param([Parameter(Mandatory)][string]$PythonDirectory)
$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$temporaryRoot = [IO.Path]::GetFullPath((Join-Path $repository '.tmp/launcher'))
$fixture = Join-Path $temporaryRoot ('进程测试 & paths-' + [Guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $fixture 'launchers'), (Join-Path $fixture 'frontend'), (Join-Path $fixture 'manifests/release-profiles') | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $fixture 'python') -Target ([IO.Path]::GetFullPath($PythonDirectory)) | Out-Null
    foreach ($file in @('common.py', 'inspect_process.py')) { Copy-Item -LiteralPath (Join-Path $repository "runtimes/launchers/$file") -Destination (Join-Path $fixture "launchers/$file") }
    foreach ($file in @('start-amvision-full.bat', 'stop-amvision-full.bat', 'stop_amvision_full.py')) { Copy-Item -LiteralPath (Join-Path $repository "runtimes/launchers/full/$file") -Destination (Join-Path $fixture $file) }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'fixtures/full_stack.py') -Destination (Join-Path $fixture 'start_amvision_full.py')
    Set-Content -LiteralPath (Join-Path $fixture 'frontend/index.html') -Value '<html></html>'
    $env:AMVAR_LAUNCHER_TEST_ROOT = $fixture
    dotnet test (Join-Path $PSScriptRoot 'Amvar.Launcher.Infrastructure.Tests/Amvar.Launcher.Infrastructure.Tests.csproj') -c Release --filter 'FullyQualifiedName~FullStackProcessTests'
    if ($LASTEXITCODE -ne 0) { throw '真实进程集成测试失败。' }
} finally {
    Remove-Item Env:AMVAR_LAUNCHER_TEST_ROOT -ErrorAction SilentlyContinue
    # 先解除 junction，绝不能递归进入外部 Python 环境。
    $junction = Join-Path $fixture 'python'
    if (Test-Path -LiteralPath $junction) { [IO.Directory]::Delete($junction) }
    $resolvedFixture = [IO.Path]::GetFullPath($fixture)
    if (-not $resolvedFixture.StartsWith($temporaryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '测试目录越界。' }
    # 测试失败时保留现场；fixture 自身有 60 秒兜底退出，避免删除仍在使用的目录。
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $resolvedFixture)) { Remove-Item -LiteralPath $resolvedFixture -Recurse -Force }
}
