---
name: arkts-app-identity
description: "根据 iOS 源应用身份和已批准目标标识实现并核验 HarmonyOS 名称、图标、启动页、链接与权限；不复制源签名配置。"
---


# 鸿蒙应用身份迁移

输入源 target 的 Info.plist、Asset Catalog、Scene/启动配置、URL schemes、
associated domains 与目标 bundle 决策；先读 ios-resources-convert 的身份资源映射。

1. 找到实际安装名称、不同语言名称、图标变体与启动表现，区分构建变量和展开值。
2. 检查目标 AppScope/app.json5、entry/module.json5、resources 的实际引用，
   识别模板应用名称、默认图标、错误 entry 页面与未使用资源。
3. 使用用户指定的目标 bundle/vendor/version；未给定而会影响外部注册时记录待决策。
   不能复制 iOS provisioning、entitlements 或签名账号作为目标配置。
4. 实现名称/图标/启动资源及入口，按目标 SDK 校验权限与 URL/deep link 接收。
5. 源 Universal Link、分享入口、推送注册有服务端依赖时列清目标注册和验证条件。
6. 运行目标配置与资源检查、实际编译；设备可用时安装冷启并核对名称/图标/入口。

输出源身份→目标配置→资源引用表和证据。静态配置正确、HAP 可编译、安装身份正确
是三种不同状态；缺设备不写 installed/verified。用户可见身份不应被模板值替代。
