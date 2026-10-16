# 0.9.0 验证范围与复现

## 2026-10-16 本轮验证

- 全量测试245项通过；收尾新增“附录不能重复计为feature”的回归后，质量视图模块21项全通过（累计246个独立用例，非两次数字相加）。基线147项保留；Spec/Plan/证据新负例与真实原调度、只读plan-check哨兵测试均包含在内。
- 独立代码审查的问题已修复并复测：正文/JSON/task对账、上游创建归属与依赖、MD依赖环、必需FV1/FV2、精确进度语法、占位六态及验收文件运行中改写。MD/JSON/schema/消费者同步，局部表格完整不能代替语义复核。
- 实际模型旧/新规则生成与第二轮返修均保存源、规则及产物摘要；第二轮三份产物局部格式和独立源复核通过。首轮失败保留，未将其改写为一次生成成功；不是盲测，没有语义提升百分比。见[生成与独立复核](../tests/evaluations/spec-plan-v2/README.md)。
- 发行检查、原消费者/资源审计、技能检查及ZIP安装副本结果以本轮`release-checks.json`和`package-check.json`为准；运行证据保存在忽略的`work/spec-quality-0.9/`，不纳入Git。源码/夹具/规则与复现入口保留在仓库。

本轮验证工具合同、执行消费与发行使用，没有运行Chunky等完整App的iOS/鸿蒙双端验收。以下为历史记录，旧数字不用于本版验收。

新增固定资源完整性、主题路由、缺审阅/越界锚点阻断，及真实隔离 stdio 服务的协议交互、
错误/超时/白名单/过期/无关/篡改证据测试。原调度、回执、源义务与行为检查继续回归。
release 检查增加 expertise-audit；ZIP 安装副本独立运行 expertise audit 和新测试。
真实 Serena/SourceKit/Xcode 和完整 App 双端行为未实测，不能用隔离服务结果代替。

## 2026-10-12 本地验证

- Windows x64 完整测试 116 项通过，其中 12 项覆盖外部资料/审阅/MCP 的正反例。
- 原流水线消费者与负例检查 19 项通过；原 1.6.1 的 3,516 个资源、选定 1.7.0 的 314 个资源，以及新导入的 87 个资料文件摘要核验通过。
- 96 个启用技能、29 个角色、版本/目录/文档链接检查通过；官方 skill quick validator 检查 96 个技能通过。
- 独立 ZIP 安装、升级、卸载、安装副本执行的最终结果与包 SHA256 记录在交付目录的 `package-check.json`。测试服务仅为协议夹具，未代替真实 MCP 或设备。

本轮没有执行官方插件校验器；本仓插件清单及版本由 release 检查核验。包校验报告保存在包外，避免把某个 ZIP 的自引用摘要写入 ZIP 内。

历史 0.5.0 交付验证在 Windows x64 完成：82 项自动化测试、19 项真实原流水线消费者与负例检查、96 个技能及 29 个角色结构检查通过；官方插件/技能校验器通过。3,516 个随包原资源文件的 SHA256 与导入清单一致。完整 ZIP 的 10 项安装、升级、卸载及独立使用检查通过。

0.6.0 新增事实/义务/回执/原调度循环/行为链/恢复的正反例、原 1.7.0 资源摘要核验和独立使用评估。0.7.0 在此基础上增加专业审阅与 MCP 证据边界。最终测试数与结果以本轮 release-checks.json、package-check.json 和日志为准，旧版数字不作为新版验收。

原始报告和运行日志保留在本地交付资料中，不纳入 Git 历史。仓库保留测试源码、必要夹具、资源校验清单与以下复现入口。每次执行必须使用新的输出目录。

```powershell
python -X utf8 scripts/validate_release.py --output work/release-check
python scripts/package_plugin.py --output dist/hmigbot-ios-0.9.0.zip
python scripts/smoke_package.py --package dist/hmigbot-ios-0.9.0.zip --output work/package-check.json
```

`validate_release.py` 默认运行单元测试、原资源审计、启用规程扫描、原流水线兼容、版本、目录、角色和文档链接检查。官方插件/技能校验器需通过 `--plugin-validator` / `--skill-validator` 指定本机脚本路径；未提供时不会冒充已执行。上述输出均为本机生成，不应提交。

这里验证的是工具和契约；本版尚无完整用户源 App 的 iPhone/鸿蒙双端行为验收。Apple 官方 skills 未加载，Xcode MCP 未连接。其他平台的随包资源存在不代表已在该平台实测。详见[实施状态](IMPLEMENTATION-STATUS.md)和[原生适配边界](NATIVE-ADAPTATION-AUDIT.md)。
