---
name: hmos-env-doctor
description: "检查原生 iOS 迁移的鸿蒙目标环境：DevEco、SDK、Node、JDK、ohpm、hvigor、hdc 和签名；源理解不依赖本机 Xcode，按实际缺项修复。"
---


# 鸿蒙目标开发环境检查

读取 `.migbot/config.json` 与当前目标工程；只对任务相关环境做诊断。
先查显式配置与已知 DevEco 位置，不递归扫描所有磁盘或覆盖用户系统环境。

1. 配置：source_platform=ios、真实 source/target 路径且分离；目标 app/module/build-profile。
2. 工具：DevEco 自带 Node、JDK、ohpm、hvigor、SDK 是否存在，版本与目标工程是否相容。
3. 检查 JDK 的 java 可执行文件；构建进程需要时局部设置 JAVA_HOME/PATH，
   这是目标打包依赖，不代表 iOS 用该语言开发。
4. 检查 ohpm 锁定依赖、hvigorfile、local.properties/hwsdk.dir 与 build-profile 签名路径。
5. 使用 a2h_ios validate；需要 build 时调用 a2h-build/hmos-fix-build-errors 保存真实日志。
6. 目标设备用 hdc 的实际返回区分未装工具、无设备、多设备、连接失败；设备选择沿用用户输入。
7. iOS Xcode/设备/官方 skills/MCP 独立报告，不以本机没有 Mac 阻断静态源分析或目标构建。

常见根因：错误 Node/JDK、SDK 目录、依赖未安装、签名路径、设备授权、目标版本。
修复后重跑失败检查；没有工具/签名/设备如实标 unavailable，不造 PASS。
环境修复不删除用户代码或凭据，不改用户全局安全策略来获得一次构建成功。
