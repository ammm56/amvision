# 设置设计交互样稿

28个场景共用一套Vue 3组件和主题变量，浏览器截图作为正式设计图。本样稿不连接业务API，不修改真实账号、权限、Token、启动设置或服务。

先按仓库开发文档安装`frontend/web-ui`依赖；本目录复用这些依赖。

```powershell
cd docs/design/frontend/prototypes/settings
npm run dev
```

打开`http://127.0.0.1:8769/?review=1&scene=services&theme=light`，右下角可切场景和主题。隐藏工具后点击左下角示例头像恢复。场景见`scenes.js`；`npm run build`验证构建。

提交和刷新仅改变示例，重载后恢复。密码和Token为演示内容，Token使用无效占位文本。语言下拉未接入完整英文翻译，品牌词缀静态展示。示例日期、版本、硬件数据和权限简表不能用作API契约。

截图视口1133×1142、1366×768；完整明细展开图1133×1400。输出时隐藏设计工具，浏览器JPEG截图仅无缩放转存PNG，不重绘或过滤。

[QA](design-qa.md) · [正式总览](../../generated/设置/设计总览.html) · [状态范围](../../settings-state-coverage.md)
