# AMVision

AMVision 是本地优先的工业视觉服务平台，覆盖数据集导入导出、训练、评估、模型转换、Deployment 推理、Workflow 编排、Trigger 和外部系统集成。

## 文档入口

- [文档总览](docs/README.md)
- [开发指南](docs/development/README.md)
- [部署指南](docs/deployment/README.md)
- [架构总览](docs/architecture/README.md)
- [API 文档](docs/api/README.md)
- [模型与数据格式参考](docs/reference/README.md)
- [运维与排障](docs/operations/README.md)

源码开发和生产发行使用不同入口。开发态完整链路依次启动 inference daemon、backend-service、`python -m backend.workers.supervisor` 和 Vite；生产态进入组装后的发行目录运行 `start-amvision-full.bat`。两种环境都不能直接运行低层 Worker launcher。

## License

AMVision is source-available, not open source.

AMVision is licensed under the PolyForm Noncommercial License 1.0.0.

Free for personal learning, education, teaching, academic study, hobby projects, and non-commercial research.

Commercial use requires a valid commercial license from amvar. 

Website : https://www.amvar.io

## 许可证

AMVision 是源码可见软件，不是开源软件。

AMVision 使用 PolyForm Noncommercial License 1.0.0 授权。

个人学习、教育教学、学术学习、兴趣项目和非商业研究可以免费使用。

任何商业使用均需要获得 amvar 的有效商业授权。

官网：https://www.amvar.io
