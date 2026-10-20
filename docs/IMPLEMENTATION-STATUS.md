# 0.10.0 实施与验证边界

新工程准备、待审候选、中文与零对象门禁、覆盖归属、问题身份、Swift 边界和用量/计时账本的范围见 [可靠性工作流](RELIABILITY-0.10.md)。十万至五十万行合成采集测试只衡量 facts 阶段，真实应用的 UI、功能及端到端效率分别验收。发行与应用结果以当轮保存的报告及固定工具提交为准，不能从本文件中的历史测试继承通过。

远端分析新增的固定超时、默认测试收集与预算派发连接已纳入本版；三类中性样本现有独立宿主行为基准及真实行为证据消费者，详见[评估范围](../evaluations/wb-0.9.1/neutral/README.md)。这些样本仍未完成真实 UI、设备、iOS 执行和完整源分析链验收。

## 0.9.1 实施与验证边界

WorkBuddy 评估中的已复现问题已按 [整改对应表](WORKBUDDY-0.9.1.md) 完成工具修改：Spec/Plan 的 MD 合同与解析/冻结同步，raw 字符串保留未知，增加受控旧规格诊断，Execute/Verify 真正消费逐页派生报告及新鲜度检查。不会用代码示例充当目标声明或真实 AC。

中性 Counter 的最终重跑完成当前 profile 2 源门禁、indexed Plan、原四拍落账和真实 hvigor 构建；执行实际 ArkTS Model 的宿主逻辑并区分 +2 变异。设备列表为空，整体行为仍 UNVERIFIED。其它三类样本仅完成源矩阵及事实提取；Chunky、iOS 编译、双端设备与视觉没有新增通过结论。详见 [实际评估](../evaluations/wb-0.9.1/README.md)。

当前发行结果以 [验证说明](VALIDATION.md) 及当轮 release/package 报告为准。以下为 0.9.0 和此前记录。

## 0.9.0 实施记录

本轮以MD规程/模板/角色为主，配套Spec产物catalog/schema、Plan三层对账、合同输入冻结及只读资源/证据视图。新增内容profile 2默认用于新项目；历史项目兼容、升级和运行边界见[0.9.0合同说明](SPEC-PLAN-CONTRACT-0.9.md)。实际模型生成样本保留首轮失败与独立反馈，不以结构完整宣称语义或整App成功；[样本记录](../tests/evaluations/spec-plan-v2/README.md)说明范围。

以下保留此前能力及限制。最终工具与发行验证结果以[本版验证说明](VALIDATION.md)及当轮报告为准。

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
