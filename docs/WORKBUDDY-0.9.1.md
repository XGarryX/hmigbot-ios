# 0.9.1：WorkBuddy 评估整改

本轮以 0.9.0 的独立复现为依据修改工具，不修改 Chunky 现场。MD 指定作者应如何产出和消费规格；catalog/schema 限定格式；Python 执行可机械判断的检查。三者一起发布，格式通过仍需独立源语义复核。

| 已确认问题 | 工具修改 | 对迁移的作用 |
|---|---|---|
| 数据单元格含“目标”会覆盖表头；UI 状态存在第二套扫描 | 共享真实 Markdown 表解析，目标列白名单；围栏和缩进示例没有声明权；同步 Spec MD | 防止合法目标丢失和源符号冒充目标合同 |
| 核心状态列掩码泄漏到相邻/业务表 | catalog 限定产物、节、完整表头、稳定 ID 和状态列；typed segments 避免占位符碰撞；同步 Plan MD | Owner、依赖、范围和业务状态变化不能继续使用旧计划 |
| raw Swift 字符串被错误解码 | lexer 保留原文与跨度；不支持的语义只给 unresolved，不生成 value；资源 MD 规定消费者行为 | 防止错误文案进入资源和 ArkUI 实现 |
| 缺件重复报错、旧标题覆盖、会话短语误报 | 同路径合并并保留规则来源；核心标题歧义阻断；正则只检查显式未完成承诺 | 降低无效返工，不把词表匹配当语义审查 |
| 旧规格缺少可执行的升级诊断 | [只读诊断与明确选择候选](SPEC-UPGRADE.md)，源/输入哈希及 ID 保真检查 | 先识别格式差距；缺失行为由原作者补齐，不自动继承 PASS |
| 汇总只数回执，报告没有真正消费 | 当前计划、原调度身份/落账、回执及输出摘要逐页关联；只从本页 UI/显式 AC 绑定推导行为；重新读取原始日志 | 未落账、过期、别页失败和未执行不再被全局结果掩盖 |
| 报告模板成功数可被照抄 | `spec-summary` 的 schema 2 合同；确定性 `migration-report` 与 `--check`；Execute/Verify MD 真正调用 | 报告手改或证据过期会被拒绝，阶段细节另外记录 |

## 报告使用

```text
python scripts/a2h_ios.py spec-summary --project <目标工程> --output <目标工程>/spec/reports/spec-summary.json
python scripts/a2h_ios.py migration-report --project <目标工程> --output <目标工程>/spec/migration-report.md
python scripts/a2h_ios.py migration-report --project <目标工程> --check <目标工程>/spec/migration-report.md
```

有当前真实 `build.json` 时，三条命令都传相同的 `--build-evidence <build.json>`。缺少构建证据时保留 not_run。生成报告不能作为状态写者；只有原调度器写三个控制账本。结构检查、视觉与行为各自保留独立证据。

`spec-summary` 的 schema 2 定义在 [Harness schema](../schemas/ios-harness-v2.schema.json) 的 `specSummary/pageEvidence/evidenceAxes`，生成和报告消费者都执行校验。派生 JSON 只写对应规范文件名或 `spec/reports/derived/`；迁移报告只写 `spec/migration-report.md`、`spec/reports/migration-report.md` 或 `derived/` 下的 MD，避免覆盖原始执行证据或产生自引用。

## 验证边界

新增回归保留 RED/GREEN，独立审查再次补反例；安装副本运行相同核心消费者。中性源样本与完整小工程流程见 [评估材料](../evaluations/wb-0.9.1/README.md)，发行检查以 [验证记录](VALIDATION.md) 为准。

本轮不声称 Chunky 整 App 完成、不声称 iOS 编译或双端设备验收通过，也不从结构检查推算语义提升百分比。构建只证明当前工程成功产出 HAP；宿主逻辑测试不能证明设备 UI。
