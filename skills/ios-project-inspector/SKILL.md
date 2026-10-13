---
name: ios-project-inspector
description: "读取原生 iOS 工程边界、有效目标线索、语言、依赖和生命周期入口；分析 Xcode project/workspace、SwiftPM、构建条件及应用扩展，输出带证据的工程地图。"
---

## 0.7.0 外部专业资料与工具证据

先读 [外部 skill/MCP 接入规程](../ios-source-analysis/references/external-expertise.md)。facts 后运行 expertise-plan，按本轮主题清单读取实际上游资料，再用 expertise-review 提交源观察。需要符号证据时用 mcp-query；未连接工具保持 unknown/unavailable。结果继续进入现有 semantics/coverage/AC，不采用上游重构建议改写源行为。

## 0.6.0 可执行协议

本技能先加载 [Harness v2 协议](../ios-source-analysis/references/harness-v2.md)。事实、义务、计划和回执由随包脚本检查；本正文的分析责任继续适用，v2 协议决定机器产物和状态，旧版 source-check 不能代替新版门禁。

执行 `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope project`，读取生成的 `spec/ref/ios-project-signals.json`，再沿事实片段阅读实际调用链。不得手写或篡改机器信号。具体填录与失败恢复见 [专业规程](references/analysis-v2.md)。



# iOS 工程结构与构建边界

## 必要输入

读取源根、迁移范围和已有 `.migbot/config.json`。本技能不创建 Xcode 项目，
也不修改签名、账号或源仓配置。先读 `ios-source-analysis/references/native-facts.md`。
产物为 `spec/ref/ios-project.md`，由本技能独占；模块清单交 a2h-spec Phase 0。

## 1. 建立工程地图

- 枚举 `.xcworkspace/contents.xcworkspacedata`、`.xcodeproj/project.pbxproj`、
  shared schemes、`.xcconfig`、`Package.swift`、`Package.resolved`、Podfile/lock。
- 区分 workspace 引用的多个项目、项目内 targets、SwiftPM targets 和代码目录。
  `PBXFileReference` 只表示引用；结合 build phases、target dependencies 和
  synchronized groups 的例外才能推断构建成员。动态规则和未知对象类型记 unresolved。
- 每个 target 记录 product type、入口、deployment target、device family、
  conditional compilation、bundle 配置、资源成员和依赖方向。
- `.swift` 为 Swift；`.m` 为 Objective-C；`.mm` 为 Objective-C++；`.h` 按导入与
  符号解析判定。C/C++ 引擎与 JS/Web 内容单独记录，不能转成 Swift 的假事实。

## 2. 沿入口理解运行边界

SwiftUI App/Scene、UIApplicationDelegate/UISceneDelegate、main.m/自定义 main，
分别追到实际根界面及服务初始化。记录多 Scene、URL/Universal Link、通知、
后台唤醒与 extension 入口；某入口无 UI 不代表其功能不存在。

App Clip、Widget、Share、Notification Service、Intents 等扩展按独立 target 建图。
记录 App Group、共享容器、Keychain group、主应用通信协议与权限边界。
将平台专有入口交 `ios-api-inventory`，不能承诺所有扩展一对一映射。

## 3. 解析依赖与混合语义

区分源码包、预编译 `.xcframework/.framework`、动态加载、插件和资源 bundle。
记录版本锁定、调用点、公开协议、许可证位置及源码是否可见。
Swift/Objective-C bridging header、generated Swift header、module map、NS_SWIFT_NAME、
泛型擦除与 nullability 边界都影响下游类型理解。不能根据包名猜其运行行为。

SwiftSyntax provider 可给语法节点与位置；编译条件、宏展开和 overload resolution
未解析时不能标 resolved。SourceKit-LSP 或 Xcode 数据必须注明工具版本与目标配置。

## 4. 环境可用时提升证据

先确认用户授权范围与实际 Xcode。用只读项目查询核对 targets/schemes/build settings；
需要构建时执行已授权的配置并保存完整日志、命令、SDK、工具版本和退出码。
无 Mac 时保留静态工程地图，构建成员标 static-inferred，不阻断独立源阅读。
云端构建仅证明选定 scheme/configuration 的构建，不证明全部功能与设备行为。

## 5. 输出与检查

工程地图逐行包括 target ID、类型、入口文件:行、语言、UI 框架、构建配置证据、
依赖和未知项。代码量是分工参考，不能当覆盖率。
每条推断标出 observed/static-inferred/unresolved，并说明如何消除不确定性。
将运行入口交 UI/功能分析；将依赖和系统能力交 API inventory；重复事实引用同一 ID。

失败恢复：路径失效重新定位，解析器不支持则保留原文件与对象片段；
不要把解析失败改写成“没有模块/没有权限”。不通过猜测填满表格。
