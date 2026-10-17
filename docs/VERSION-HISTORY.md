# GitHub 版本记录

本仓库从独立 **HMigBot CodeX 1.6.1** 的本地发行快照建立历史，再提交 **HMigBot iOS 0.5.0**。基线不是 HMigBot Plus，也不是伪造的上游 Git commit。

| 版本 | 内容 |
| --- | --- |
| `hmigbot-v1.6.1` | 原发行的 3,544 个文件，逐字节保留；仅排除缓存与文件系统元数据 |
| `v0.5.0` | iOS 原生源理解、原 a2h 流水线复用、自包含安装和验证 |

[版本差异](https://github.com/liuxingwen1016-sys/hmigbot-ios/compare/hmigbot-v1.6.1...v0.5.0) · [0.5.0 源码](https://github.com/liuxingwen1016-sys/hmigbot-ios/tree/v0.5.0)

0.5.0 以本地开发提交 `98329b4dead74e51f0b316cd65dda60b4edce23e` 为输入整理。该提交及此前试验历史仅在本地保留，不是远端历史的父提交。本次整理排除旧设计草稿、过时说明、生成示例、日志、运行报告和废弃目录生成器，同时修正文档引用与忽略规则；迁移实现与必需资源保留。

提交包含：技能/参考/模板、角色、源代码、提供器、安装/卸载/打包脚本、测试源码和必要夹具、当前使用文档、上游来源与文件摘要、`vendor/hmigbot` 完整复用资源。随包二进制属于运行依赖，保留在 Git 中。

不提交：工作区安装副本、用户应用、账号/证书、临时目录、缓存、构建结果、交付 ZIP、机器运行日志和旧版研究资料。原基线中的原作者资料保持原样，用于准确溯源；不把其中的历史说明当作 0.5.0 的操作入口。

后续开发从远端 `main` 开始，发布时建立版本标签。安装见 [INSTALL](INSTALL.md)，验证见 [VALIDATION](VALIDATION.md)，来源见 [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES.md)。

## 本地 0.6.0 开发

本轮在 feature/ios-harness-0.6.0 分支施工；新增选定 1.7.0 控制核心和 iOS v2 适配。发布与推送状态以实际 Git 记录为准，本说明不创建远端发布或标签。

## 本地 0.7.0 开发

在既有 0.6.0 工作树上接入固定版本 AvdLee SwiftUI/Concurrency、Axiom UIKit/内存资料，以及 stdio MCP 源查询证据适配器。保留原五阶段、稳定 ID、三份状态账本与目标实现/验证规程；新增资料审阅门禁及冻结输入，README 逐步说明产物和交接条件。施工和交付在本地完成，本轮没有创建 GitHub 发布或推送版本标签。
