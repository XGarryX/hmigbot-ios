# 0.9.2 验证范围与复现

- 新增24项独立回归已通过：精确Xcode缓存排除、真实共享/本地Scheme及配置变化、13份native记录的完整性、字段schema、typed事实、N/A矛盾、附录/主功能锚点、过期输入、只读候选与正式门禁消费。
- 全量529项：527通过、2项目录符号链接测试因本机Windows权限不足跳过，0失败。缓存损坏反例修复后，8项快照回归再次通过。
- 11项发行检查通过：单元回归、原资源/调度器/专业资料审计、原流水线兼容、版本、技能/角色、便携入口与文档链接。另实际运行本机官方 skill-creator 的 quick_validate，96份Skill全部通过；外部插件validator未配置，不声明已运行。
- 最终全量单元及ZIP独立安装/升级/卸载结果，使用本轮交付的 full-final.log、release-checks.json 和绑定ZIP摘要的 package-check.json；历史数字不用于推定当前结果。
- [修复与旧索引升级](SOURCE-AUTHORING-0.9.2.md)；[生成操作协议](../skills/a2h-spec/references/native-authoring.md)。本轮只验证工具；不修改实际应用源/规格，不代表应用构建或设备验收。

## 0.9.1 历史验证

## 2026-10-16 WorkBuddy 整改验证

- 全量独立用例 348 项通过（401.397 秒）；0.9.0 的 246 项保留，本轮新增 102 项。不是把同一组多次重跑相加。覆盖原调度落账、旧语义门禁与新增边界。
- 新增解析、缩进/围栏与真实 AC、精确进度冻结、raw 字符串、升级 API/CLI、逐页证据和独立反例；保留各组 RED/GREEN。中间的并行接线失败已保留并收口，不能计为一次全通过。
- [Counter 最终重跑](../evaluations/wb-0.9.1/results/attempt-02/result.json) 完成源门禁、Plan 检查、原四拍全部落账与 done；真实构建 exit 0、BUILD SUCCESSFUL，产生 15,472 字节 unsigned HAP。生产 ArkTS Model 宿主输出 `[0,1,2]`，`+=2` 变异输出 `[0,2,4]`，被独立期望区分。迁移报告生成后 `--check` 返回 current。
- 完整行为报告仍 UNVERIFIED：F001-AC02 的设备 UI 未执行。`hdc list targets` 为 `[Empty]`；没有 iOS 编译、双端设备或视觉结果。Binding/导航、UIKit/IB、跨页异步样本只做源矩阵与事实提取；[评估说明](../evaluations/wb-0.9.1/README.md) 保留作者候选性质、首轮 stale 和已知限制。
- 发行及安装验证证据保存在忽略目录 `work/wb-fixes-0.9.1/`；随包保留可重放样本、脚本与紧凑结果，不上传 Chunky 输入或本机完整测试工程。官方插件 validator 未配置，不能声明已执行。

以下为历史记录，其数字不用于 0.9.1 验收。

## 0.9.0 验证记录

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
