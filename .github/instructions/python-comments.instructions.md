---
applyTo: "**/*.py"
description: "Use when creating or editing Python code in this repo. Require Chinese comments and docstrings for modules, classes, dataclasses, methods, parameters, fields, and public attributes. Keep English nouns unchanged."
---

# Python 中文注释规则

- 模块、类、dataclass、Protocol、函数、方法都必须写中文 docstring。
- dataclass 字段、模型字段和公共属性必须在类 docstring 里逐项说明；必要时补充简短行内注释。
- 方法和函数的 docstring 必须写参数和返回说明；没有返回值时可以省略返回段。
- 注释使用中文，DatasetVersion、ModelVersion、ModelBuild、RuntimeProfile、ObjectStore 这类名词保持英文不变。
- 注释只写职责、输入输出、边界和约束，不写空话，不重复代码字面意思。