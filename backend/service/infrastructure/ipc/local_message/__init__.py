"""统一的本机结构化 mmap RPC 与 EventRing 基础设施。

具体 adapter 从各自模块显式导入，避免 package import 隐式创建运行时依赖。
"""
