# 前端测试

新增前端单元测试统一放在仓库根 `tests/frontend/`，按功能分目录，文件命名为 `test_*.ts`。Workflow 文档和版本历史测试位于 `workflows/`。不在业务源码目录新增测试文件。

依赖仍由 `frontend/web-ui/package.json` 管理，不维护第二套 node_modules。Vitest 和 vue-tsc 同时覆盖本目录；既有 `frontend/web-ui/src/**/*.test.ts` 继续纳入测试，迁移时需保留覆盖范围。

```powershell
npm --prefix frontend/web-ui test -- tests/frontend/workflows
npm --prefix frontend/web-ui run typecheck
npm --prefix frontend/web-ui test
```

npm 脚本先进入仓库根目录再运行前端依赖中的 Vitest，使测试 root 和进程 cwd 一致，避免 Windows 下根目录外测试被错误解析。Vitest 的测试 alias 指向已有前端依赖，不改变生产构建的模块解析。
