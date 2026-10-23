<#
仅清理已整理的项目设计目录。自动删除被审批阻止后，供本机手动执行。
先使用 -WhatIf 查看范围；不处理 bak1，不删除未知条目。
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'
$projectAssetsRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'generated/项目')).Path
$expectedRoot = 'W:\workspace\codex\python\amvision\docs\design\frontend\generated\项目'
if ($projectAssetsRoot -ne $expectedRoot) { throw '目标目录与已审查的项目设计目录不一致。' }

$manifestPath = Join-Path $projectAssetsRoot '生成清单.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.items.Count -eq 0 -or $manifest.items.Count -ne $manifest.images) { throw '保留图片清单数量不符。' }
$expectedFileCount = $manifest.items.Count + 2
$keepNames = @('设计总览.html', '生成清单.json')
foreach ($item in $manifest.items) {
    if ([IO.Path]::GetFileName($item.path) -ne $item.path -or [IO.Path]::GetExtension($item.path) -ne '.png') {
        throw '保留图片必须是根目录中的 PNG。'
    }
    $imagePath = Join-Path $projectAssetsRoot $item.path
    if ((Get-FileHash -LiteralPath $imagePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) {
        throw "保留图片内容与清单不一致：$($item.path)"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $projectAssetsRoot $item.prompt) -PathType Leaf)) {
        throw "缺少中文提示词：$($item.prompt)"
    }
    $keepNames += $item.path
}
if (@($keepNames | Select-Object -Unique).Count -ne $expectedFileCount) { throw '保留文件名存在重复。' }
foreach ($keepName in $keepNames) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectAssetsRoot $keepName) -PathType Leaf)) {
        throw "缺少保留文件：$keepName"
    }
}

# 中文提示词已集中到文档目录，删除副本前再次核对。
$promptRoot = Join-Path $PSScriptRoot 'prompts/项目完整设计请求'
if (@(Get-ChildItem -LiteralPath $promptRoot -File).Count -ne $manifest.items.Count) { throw '中文规格必须与保留图片一一对应。' }
$oldPromptRoot = Join-Path $projectAssetsRoot '完整设计/prompts'
if (Test-Path -LiteralPath $oldPromptRoot -PathType Container) {
    foreach ($sourcePrompt in Get-ChildItem -LiteralPath $oldPromptRoot -File) {
        if ((Get-FileHash -LiteralPath $sourcePrompt.FullName).Hash -ne
            (Get-FileHash -LiteralPath (Join-Path $promptRoot $sourcePrompt.Name)).Hash) {
            throw "中文请求副本不同：$($sourcePrompt.Name)"
        }
    }
}

$obsoleteEntries = @(
    '历史版本', '历史请求', '过程稿', '审查证据', '完整设计', 'prompts', 'references',
    'gallery.html', 'manifest.json', '项目概览.html', '项目概览清单.json',
    '项目操作.html', '项目操作清单.json', '项目审查清单.json'
)
$unknown = @(Get-ChildItem -LiteralPath $projectAssetsRoot -Force | Where-Object {
    $_.Name -notin $keepNames -and $_.Name -notin $obsoleteEntries
})
if ($unknown.Count) { throw "发现未审查的文件，停止清理：$($unknown.Name -join '、')" }
if (@(Get-ChildItem -LiteralPath $projectAssetsRoot -Recurse -Force | Where-Object {
    $_.Attributes -band [IO.FileAttributes]::ReparsePoint
}).Count) { throw '目录中存在链接，停止清理。' }

$obsoleteFiles = @()
$obsoleteDirectories = @()
foreach ($entry in $obsoleteEntries) {
    $entryPath = Join-Path $projectAssetsRoot $entry
    if (-not (Test-Path -LiteralPath $entryPath)) { continue }
    $entryItem = Get-Item -LiteralPath $entryPath
    if ($entryItem.PSIsContainer) {
        $children = @(Get-ChildItem -LiteralPath $entryItem.FullName -Recurse -Force)
        $obsoleteFiles += @($children | Where-Object { -not $_.PSIsContainer })
        $obsoleteDirectories += @($children | Where-Object { $_.PSIsContainer })
        $obsoleteDirectories += $entryItem
    } else { $obsoleteFiles += $entryItem }
}
foreach ($item in @($obsoleteFiles) + @($obsoleteDirectories)) {
    $absoluteTarget = (Resolve-Path -LiteralPath $item.FullName).Path
    if (-not $absoluteTarget.StartsWith($projectAssetsRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "删除目标超出项目设计目录：$absoluteTarget"
    }
}
foreach ($item in $obsoleteFiles) {
    if ($PSCmdlet.ShouldProcess($item.FullName, '删除历史或重复设计文件')) {
        Remove-Item -LiteralPath $item.FullName
    }
}
foreach ($item in $obsoleteDirectories | Sort-Object { $_.FullName.Length } -Descending) {
    if ($WhatIfPreference) { continue }
    if (@(Get-ChildItem -LiteralPath $item.FullName -Force).Count -ne 0) { continue }
    if ($PSCmdlet.ShouldProcess($item.FullName, '删除空目录')) { Remove-Item -LiteralPath $item.FullName }
}
if ($WhatIfPreference) { return }

$remaining = @(Get-ChildItem -LiteralPath $projectAssetsRoot -Force)
if ($remaining.Count -ne $expectedFileCount -or @($remaining | Where-Object { $_.PSIsContainer }).Count -ne 0) {
    throw '清理尚未完成；保留文件未删除，可检查后再次运行。'
}
$manifest.cleanup.state = 'completed'
$manifest.cleanup.reason = "本机执行已审查的清理脚本，确认根层 $expectedFileCount 个文件且无子目录。"
$manifest.cleanup.target_files = $expectedFileCount
$manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Output "清理完成：$($manifest.items.Count) 张图片、1 个总览、1 个清单；bak1 未修改。"
