# 0.7.0 实施与验证边界

新增真实上游资料快照、expertise-plan/review、源门禁与冻结计划接线、stdio 源查询 MCP
证据采集与引用校验。完整阶段、细分步骤、skill/MCP、产物和交接写在 [README](../README.md)。
本机仅用隔离协议服务验证 stdio 交互/失败；尚未实测真实 Serena/SourceKit/Xcode。
工具验证以本版 release-checks/package-check 报告为准，不扩张为完整 App 迁移验收。

新增可执行 iOS Harness 与原 1.7.0 四拍控制核心；实施细节、测试层级和未完成的应用验收见 [0.6.0 实现报告](HARNESS-0.6.md)。实际结果以本轮新报告为准，以下是继承的工具层能力与应用验收限制。


已实现启用层的 iOS 源语义改造、四领域源分析、通用锚点、原生事实检查和目标复用入口。
发行包含 96 技能、29 角色及独立归档内 3,516 原资源。原 a2h 五阶段、spec 目录、计划/brief/AC/findings 保留。

## 验证依据

以交付目录的 release-checks.json、native-pipeline/report.json、package-check.json 和安装报告为准。
单元测试含真实原图片检测、源 oracle 路径、原生维度遗漏/未知/越界/语言错标、安装所有权和现有机械工具回归。
原流水线兼容测试覆盖真实原消费者以及漏 AC、源变更、孤立 ViewModel 等失败和修复路径。
完整 ZIP 冒烟在中文/空格路径解压、安装，隐藏解压源后从安装副本升级和卸载。

## 未完成的应用验收

尚未指定完整用户源 App，本版没有完成其源编译、iPhone 安装运行或双端视觉/行为验收。
Apple 官方 skills 未加载；Xcode MCP 未连接。云编译的历史夹具成功不等于本版本应用验收。
Windows x64 为本次发行实测平台；其他平台资产存在不等于其全部检查已通过。

原 wiring 检查可能放过空 handler；原图片检查按行扫描，紧凑链式写法可能误报。
原生 facts checker 校验字段和溯源，不证明完整语义。独立行为 AC 与真实运行证据仍是最终验收要求。
