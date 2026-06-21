# Python 代码检查

## 文档目的

本文档说明开发时最常用的 Python 代码检查命令，以及 Ruff 规则编号对应的直白含义。

这里不替代完整测试，也不要求每次结构重构都顺手清全仓库 lint。结构重构、功能修复和全仓库 lint 清理应分开提交。

## 明显问题检查

优先使用下面的脚本检查最容易影响运行的问题：

```powershell
conda activate amvision
.\scripts\check-python-obvious-errors.ps1
```

这个脚本实际执行：

```powershell
conda activate amvision
python -m ruff check backend tests custom_nodes --select F,E9
```

脚本会检查当前 shell 是否已经激活 `amvision` 环境。如果 Ruff 发现问题，脚本会返回非零退出码，方便本地脚本或后续 CI 直接判断失败。

## Ruff 规则编号含义

- `F`：Pyflakes 规则族，主要检查未用 import、未定义名称、未用变量等明显问题。
- `F401`：导入了模块、函数或类型，但当前文件没有使用。
- `F821`：使用了未定义的名称，常见原因是变量未声明、类型未导入或函数名写错。
- `F841`：局部变量赋值后没有使用。
- `E9`：严重语法类问题，例如 SyntaxError、IndentationError。

## 使用边界

- 结构重构时只修当前改动引入的问题，不顺手清理全仓库历史 lint。
- 全仓库 lint 清理应单独开一轮，只处理明确的未用 import、未定义名称、未用变量和语法错误。
- 不为了通过 lint 改变模型结构、训练逻辑、转换逻辑或公开 API 行为。
- 如果某个 import 是为了注册 ORM、触发插件加载或检查可选依赖，应加清楚注释或局部 `noqa`，不要误删。
