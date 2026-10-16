---
name: ios-api-inventory
description: "提取原生 iOS 服务 API、系统框架、权限、entitlements、隐私与三方 SDK 接缝；保存调用和数据契约证据，并向 HMigBot 目标领域技能提供可核验输入。"
---

## 执行前加载

按 [Harness v2](../ios-source-analysis/references/harness-v2.md) 确定机器产物/状态写者；按 [外部资料规程](../ios-source-analysis/references/external-expertise.md) 执行expertise-plan/review，未连接工具保持unknown/unavailable。

执行 `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope api`，读取真实 `spec/ref/ios-api-signals.json` 后继续读调用链。加载 [接缝分析与跨作者交接](references/analysis-v2.md)；不得手改机器信号，也不采用上游重构建议改写源行为。

# iOS API、平台能力与依赖接缝

## 输入输出

读取工程地图、Swift/Objective-C 调用点、Info.plist、entitlements、PrivacyInfo.xcprivacy、
依赖锁定文件、公开接口及源测试。输出 `spec/baseline/api-inventory/` 下 JSON/Markdown。
网络 inventory 保留 HMigBot `services[].endpoints[].static.http_method/path/protocol`
和 `services[].auth_type` 契约，另加 `source_platform: ios`、源锚点和平台能力表。

## 1. 外部服务契约

从 URLSession、URLRequest、自定义 client、Alamofire、GraphQL、WebSocket、SSE、
WKWebView bridge 等实际调用追 method/path、base URL 选择、header、编码、
签名、token 刷新、超时、重试、分页、缓存和错误信封。依赖名只用于候选定位。
源码未确定的 URL 片段/响应类型明确标 dynamic/unknown，不拼造完整端点。
公共鉴权与公共参数放 common.md；功能 spec 引用所属端点 ID。

## 2. 系统能力矩阵

为每个使用点记录框架、方法、触发、返回数据/句柄域、回调线程、权限前后状态、
应用与扩展可用性、设备/版本限制、后台约束和失败表现。
覆盖实际出现的相机/媒体/相册/位置/蓝牙/NFC/通知/后台/联系人/日历/文件/分享、
StoreKit/Sign in with Apple/HealthKit/CloudKit/WidgetKit/App Intents 等能力。
列表是检查线索；未出现的能力写不适用，不能给任意应用捏造接口。

## 3. 配置与隐私

交叉核对调用点、usage descriptions、entitlements、URL schemes、associated domains、
ATS、App Groups、Keychain groups、背景 modes 与 privacy manifest。
用途字符串只证明声明，不能证明用户实际授权；权限拒绝和撤销路径继续读实现。
不抄源签名/账号配置到目标；目标 bundle、证书、支付/推送注册各自核验。

## 4. 三方与本地桥接

每个依赖记录版本、源码可见性、调用点、数据协议、资源、初始化/释放和平台限制。
优先查厂商官方鸿蒙支持与对应版本，再查公开实现；保留来源日期及实际测试状态。
NAPI 方案必须定义类型、缓冲区、所有权与线程边界；禁止把 .xcframework 改扩展名当目标库。

## 5. 目标映射与决策

映射不是 API 名字替换。区分行为等价但实现不同的 HARD 与行为变化的 HARD-DIV。
HARD-DIV 必须有决策 ID、源行为、替代数据流、被替代 AC 与新差异 AC，
按本轮授权确认产品选择；未知工具能力不能伪造为可用。
目标实现按实际领域使用 arkts-system-capabilities、arkts-data-layer、arkts-login、
arkts-payment、arkts-media-playback、arkts-webview 等包内技能。

## 6. 输出验收

每条记录可回到源文件:行；公共字段与 feature 引用一致；动态部分保留表达式和依赖。
无法读到的 SDK 内部行为记 opaque，并指定需要的公开契约或运行证据。
没有设备或服务账号的测试保留 not_run，不用静态调用存在声称设备功能通过。
