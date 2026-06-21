<#
检查 Python 代码里最容易影响运行的明显问题。

这个脚本只是给 Ruff 规则编号加一个更直白的入口：
- F：未用 import、未定义名称、未用变量等 Pyflakes 问题
- E9：语法错误、缩进错误等会直接阻止 Python 运行的问题

默认只检查本项目源码和测试目录，不扫描 projectsrc、data、release/full。
#>

$ErrorActionPreference = "Stop"

if ($env:CONDA_DEFAULT_ENV -ne "amvision") {
    Write-Error "请先执行 conda activate amvision，再运行本脚本。"
    exit 1
}

$Paths = @("backend", "tests", "custom_nodes")

python -m ruff check @Paths --select F,E9
exit $LASTEXITCODE
