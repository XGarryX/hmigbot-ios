# Mac Codex 接手：HMigBot-iOS Windows改造后的原生实证与后续实现

更新：2026-10-22。本文面向没有旧聊天、Windows知识库或MultiCA运行记录的新Mac会话。先读本文即可理解项目、已完成改造、未完成问题和下一步，不需要恢复历史记忆。

## 0. 最新授权与交付状态

用户目标：把hmigbot-ios打造成最好用的iOS→原生HarmonyOS工具，支持20万行以内，架构保留远期50万行扩展；UI准确率100%、功能完备度100%；10万行完整转换≤2小时，全部模型调用token严格<20M。

用户原先要求只分析；随后明确授权：**Windows能做的立即施工，验证后推送GitHub，Mac需要修改/验证的部分做好交接。** 因此“只研究、不施工”是旧阶段限制，已被当前授权更新。继续已授权范围无需重复确认；新产品选择和不可推断的权限/账号问题仍应具体处理。

本轮基于main `73b318316e52ff4d943593d0b287a8ca24ff478d`实施四个Windows可测基础包：规程与作者接线、同次调度hash去重、在途token预留、源分析host回执/provider预检。改造说明见 [Windows施工合同](WINDOWS-FOUNDATION-20261022.md)，真实验证结果见 [VALIDATION](VALIDATION.md) 顶部本轮条目。不要把计划中的项目当作已实现。

本轮验证工具/合同与安装，不认证完整App迁移成功。Mac/Xcode、完整双端视觉/业务、真实100k/200k整工程和2h/20M同时达标仍待验证。最新工具版本从仓库 `pyproject.toml` 读取；接手记录真实 `git rev-parse HEAD`，不要把上述输入基线当成改造后的提交。

Windows最终结果：1366项通过、52项跳过、1700子测试通过；12项发行检查、96份官方技能校验、27项独立安装/升级/卸载检查通过。52项中48项缺准确冻结的C7源/框架快照（`HMIGBOT_C7_SOURCE` / `HMIGBOT_C7_FRAMEWORK_SOURCE`），3项缺符号链接权限、1项不是venv启动；这些未算通过。C7快照不是随便一个旧Cuike目录，应按 `tests/test_capability_closure.py` 的20文件只读源及工程回执要求找回准确输入；本轮未取得，缺口与平台无关。其余App级待验仍按本文继续，不继承旧成功。

## 1. 三个项目是什么

| 项目 | 定位与关系 | 地址 |
|---|---|---|
| HMigBot / HMigBot CodeX | 原始独立Android→HarmonyOS框架；模型按技能规程理解、设计、编码，脚本做机械检查/调度/证据。不是HMigBot Plus | 工具仓内 `vendor/hmigbot` 为1.6.1资源，`vendor/hmigbot-1.7.0` 为选定1.7.0调度核心 |
| hmigbot-ios | 通用原生iOS→原生HarmonyOS工具，本任务优化对象；保留原目标侧技能和控制主线 | https://github.com/liuxingwen1016-sys/hmigbot-ios.git；Windows `D:/Ios2Harmony/hmigbot-ios` |
| cuike-ios / 萃刻 | 小型真实iOS源应用，用来暴露通用工具问题；离线手冲咖啡伴侣，SwiftUI/SwiftData、豆/配方/冲煮/手记、OCR、Widget、ActivityKit、App Intent | https://github.com/liuxingwen1016-sys/cuike-ios.git；Windows `D:/Ios2Harmony/ios`；研究源SHA `131ef8d1468bf5fb6d73d69a900a5dd404c096bb` |
| Cuike-HarmonyOS-* | Windows不同实验轮次的鸿蒙目标现场，不是工具或iOS源 | 不随上述两个Git仓自动转移。缺目标时建独立新目录；需要续跑旧现场时先取得其完整文件和证据 |

原主线：`a2h-init → a2h-spec → a2h-plan → a2h-execute → a2h-verify → a2h-retrospect`。执行四拍为 `next-batch → dispatch → receipt → land-results`。稳定page/F/AC ID、索引计划、执行brief、唯一文件owner、`spec/.a2h/open-findings.json`及三份控制账本的原工具写者必须保留。不要改成另一套1to1/arch流水线，不批量重写共享arkts/hmos技能或vendor。

`bin/a2h`是运行支持，不是独立语义转译器。宿主Codex和受支持角色按MD规程实施；不能只跑Python脚本就宣称业务转换完成。包内全部技能、模板、角色及原资源随Git提供，不需要Windows的旧发行目录或binding包。

通用工具中禁止写Cuike专用页面名、业务数值、路径或例外。Cuike问题应被一般规则和中性负例覆盖。

## 2. 这轮研究怎样形成方案

CodeBuddy、Qoder CN（均DeepSeek V4 Pro/max）与当前Codex先独立分析，再交换方案、纠正假设，对10项原则及4项剩余边界回签。MultiCA任务THEF-91/92/93完成的是研究，不是App目标达标。

统一顺序为：A指标/源分母/完整计量/终局验收最小合同先明确；B规程一致性、已有prompt_scope作者接线、同次去重；C原生证据和真实Cuike闭环。B/C可在A最小合同后并行；Mac环境发现与源构建不必等待所有性能实现。

原始三方材料在Windows `D:/MultiCA/deliveries/hmigbot-ios-triad-20261022/`，新Mac无需该目录才能继续。关键裁决已写入本文和 [施工合同](WINDOWS-FOUNDATION-20261022.md)：

- 缓存input也计入总token；缓存仅可能降低付费和延迟，不能从20M口径扣除。
- 完整必验视觉/业务/构建矩阵计入同一2小时挑战；抽样只作诊断。
- 所有未知、未支持、未跑继续列账；独立源分母不能被机器facts或active AC自证。
- 自动scope仅作候选，由作者/计划明确采用；无scope决策继续全局传播，不能因没有直接fact引用而删除共享约束。
- 200k容量与质量分证；500k只是远期架构/压力目标。Cuike2109物理代码行和合成提取数据不能外推完整规模、时间或用量。
- 先量关键路径再决定分片、跨运行缓存、Windows运行时stage复用和更复杂并发；不把猜测的收益写成结果。

## 3. Windows具体改了什么，Mac哪些仍要验

| 已改范围 | 根因与处理 | Mac接手动作 |
|---|---|---|
| a2h/源分析规程 | 决策账本统一为 `spec/decision-ledger.md`；源准备与目标构建准入分开；源硬门失败不允许靠“两轮记债”绕过 | 跑同一规程/安装回归；确认新安装副本没有残留旧MD |
| prompt_scope作者入口 | 运行时已有能力但缺作者指导；增加参考、模板/schema和真实采用规则 | 用真实Plan检查必要共享约束、无scope广播和范围投影；不得自动缩分母 |
| ios_scheduler输入去重 | 同文件多任务/heading重复hash；先检查每个路径与hash冲突，再同次step读取一次 | 相同回归在macOS重跑；不改最终全图/当前证据门，不跨运行继承PASS |
| usage在途预留 | 原账本只看已用，无法阻止并发争用余额；增加锁内预留、同ID结算、明确取消、未结算状态 | 重跑锁/进程并发、真实宿主用量归一与预留许可；补Darwin计时身份，见后文 |
| source-analysis准备回执/预检 | host仅doctor展示；无效provider后项可能被迟发现；每次回执记录当前能力发现，provider整单先预检 | 真Mac确认发现与执行分开；真实provider另配置、执行和验收，不自动解除源提取硬门 |

完整验证发现后追加了provider Windows长路径修复：`provider_runs`及计划路径预检复用既有 `core.io_path`，真实超过260字符的项目/config/bundle已验证成功发布、失败保留与重试；相对合同路径保持正常形式。Mac重跑相同生命周期；Windows专属路径用例在其他平台跳过是明确平台范围，不代表Mac真实provider已验证。

同文件100任务×2引用的读取探针由200次降到1次，仅说明该校验循环的逻辑读取量。不是整个迁移200倍加速。错hash、冲突、越界、缺文件、下次同mtime/size内容变化仍必须拒绝。

## 4. Mac拿代码和准备独立工作区

在适当项目目录克隆两个仓库；已存在时先保护本地改动，再fetch并检查分支，不用reset清空。

```sh
git clone https://github.com/liuxingwen1016-sys/hmigbot-ios.git
git clone https://github.com/liuxingwen1016-sys/cuike-ios.git
cd hmigbot-ios
git status --short --branch
git log -5 --oneline
git rev-parse HEAD
python3 --version
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
```

工具要求Python≥3.11，实际版本从pyproject读取。记录macOS/CPU/Python/Xcode/Swift/SDK/git版本；真实Cuike scheme、配置和目标以工程查询为准。不要照搬Windows驱动器路径、`.venv`或已安装的Python缓存。

需要安装技能时，在仓库根执行 `PYTHON=python3 sh install.sh /absolute/workspace`，先读 `docs/INSTALL.md`；脚本无需依赖Git可执行位。生成的工作区`.hmigbot-ios/plugin`才是已安装运行副本。修改工具后按受支持安装/升级更新副本，不要一边改Git源码一边运行陈旧副本。用户工作区AGENTS与原有配置须保留。

源目录、目标目录互不包含。先创建独立目标目录，再从仓库根运行：

```sh
mkdir -p /absolute/cuike-harmony
python scripts/a2h_ios.py init --source /absolute/cuike-ios --project /absolute/cuike-harmony
python scripts/a2h_ios.py source-analysis --project /absolute/cuike-harmony
```

这些绝对路径是需替换的示例。缺hvigor不阻断源准备，`validate`仍是目标构建准入。已有计划/基线不能用新入口强覆盖，按受审 `facts/source-refresh/replan` 流程，保持原ID。

## 5. 首先验证本轮代码没有平台回归

在工具仓根执行，结果单独保存在Mac新的work目录：

```sh
python -m pytest tests/test_workflow_authoring_contracts.py tests/test_skill_maintenance.py tests/test_prompt_inputs.py tests/test_scheduler_input_dedup.py tests/test_usage_reservations.py tests/test_usage_dispatch.py tests/test_usage_cli.py tests/test_source_analysis.py tests/test_provider_preflight.py -q
python -X utf8 scripts/validate_release.py --output work/mac-foundation-check --unit-timeout-seconds 1800
```

发行检查还会覆盖原资源、原调度、专业资料、原流水线、版本、角色和文档。完整单元测试须看真实结束结果；不要把“进程启动/文件存在”当通过。符号链接、文件锁、路径大小写和shell可执行位要以Mac实际结果记录。

完整套回归已超出旧600秒上限，本轮runner默认单测1800秒，可显式配置1–7200秒。`--test-temp`仅接受新的专属目录；已有文件/目录、盘根及证据目录祖先会拒绝，不能用它清空用户数据。首次Windows超时/长路径失败日志保留；后续完整结果以VALIDATION的新记录为准。原生指令审计的11处合法平台比较现有精确逐行审阅policy，改正文/行尾须人工重审，不能批量重算hash放行。

当前Darwin启动身份未实现，依赖真实宿主时钟的预算CLI/派发测试可能因该已知缺项失败；按6.4先补真实身份再重跑，不以mock或删除断言掩盖平台差距。显式usage预留也会因此拒绝，不能称Mac严格预算现已可用。

然后按 `docs/VALIDATION.md` 的package/smoke入口在新路径做安装/升级/卸载；这仍不是Cuike App验收。外部官方validator只有实际配置并运行才可声称已验。

## 6. 必须在Mac修改/验证的原生证据链

### 6.1 真实Cuike构建和独立源真值

先记录源SHA。工程入口是 `cuike-ios/Cuike.xcodeproj`，研究时scheme为 `Cuike`；先查询，不猜device ID或固定SDK。

```sh
xcodebuild -version
xcrun swift --version
xcodebuild -list -json -project ../cuike-ios/Cuike.xcodeproj
xcodebuild -showdestinations -project ../cuike-ios/Cuike.xcodeproj -scheme Cuike
```

选择真实可用destination后运行构建/测试，保存原始日志、退出码、xcresult与选择身份；target/scheme/config/SDK/成员范围都要记录。签名、商店/账号、系统扩展与持久库状态分别验，普通持久库的重启恢复不能被内存测试替代。编译日志成功只证明该构建，不证明功能100%。

源仓已有 `Scripts/verify-mac.sh`，在cuike-ios根用 `bash Scripts/verify-mac.sh` 即可按顺序运行：Xcode版本采集、`swift test`、无签名模拟器App构建、可用iPhone模拟器上的App/UI测试。日志在 `build/`，测试有带时间戳的`.xcresult`；失败会停止，保留已有证据。可先选实际UDID，再用 `CUIKE_SIMULATOR_ID=实际UDID bash Scripts/verify-mac.sh`。脚本已运行核心测试，无需为了凑次数先单独重复一次。

源根Package.swift为CuikeCore（Swift tools 5.9，声明iOS17/macOS14）；单独 `swift test` 只验Core，不构建App、Widget、SwiftData或UI。Xcode工程研究时有Cuike、CuikeWidgets、CuikeTests、CuikeUITests四个target。现有UI用例验证15g×16=240g、调到18g=288g、提前结束→五星手记→均分4.5，以及豆名必填/有效保存；它们只覆盖这些给定路径。`--uitesting`使用内存库，不能证明持久恢复。源入口优先读 `App/CuikeApp.swift`、`App/Data/BrewStore.swift`、`Core/`、`Tests/UITests/CuikeUITests.swift`。无需为打开现有工程运行 `Scripts/generate_project.py`，该脚本会重写工程与配置。

优先观察：冲煮计时→提前结束→手记；后台/重启计时恢复；豆和配方引用约束；编辑/删除持久化；OCR成功/失败/权限；异步取消、迟到结果、重复操作；Widget/Activity/AppIntent接缝。每条记录输入、源状态变化、副作用、错误/取消及独立可观察结果。

### 6.2 SwiftSyntax、编译绑定与提取问题精确裁决

现 `providers/swift-syntax` 是语法工具适配源码，产物名为 `hmigbot-swift-syntax`；协议 `semantic_resolution=False`，消费者保留 `compiler_binding=unresolved`。Package.swift固定Swift工具版本6.0、SwiftSyntax 600.0.1，须先核对新Mac实际工具链兼容性，再按该目录README执行 `swift build -c release`，不能把旧平台解释执行记录当成当前Mac已构建。官方资料、XcodeRead/Grep、语法树、编译绑定和运行观察是不同证据层。host显示macos_xcode只表示能力候选。

待实现方案：

1. 用当前Swift/SDK真实构建并运行provider，显式配置command/version_command，固定源hash、配置与工具版本；先用最小文件验证，保留成功和失败attempt原件。
2. 建三组可证伪样本：复杂字符串/插值/Unicode词法边界；跨文件引用/重载/宏或条件编译；实际target成员与排除。每组有正反例及真实编译上下文。
3. 追踪provider节点如何补齐原facts/obligations、源语义和独立覆盖消费者；在 `refresh` 与 `validate_graph` 中使用同一确定规则。不能只把issue改成resolved而没有补齐事实。
4. 针对具体issue ID/源跨度/target/config建立精确裁决，拒绝过期、错源、错SDK和错配置。parse成功不自动清除TOKEN_BALANCE、Unicode审阅或其他提取完整性问题。
5. 再实现真实原生provider阶段路由；保留Windows静态回退。不要猜scheme、SDK、编译参数，不因Xcode可用就设置symbol_binding=known。

`-showBuildSettings`导入的真实性仍未自动验证，不能独自证明实际源成员或符号绑定。已有真实build membership采集与selected-build消费合同应复用；unknown/incomplete不能缩分母。

### 6.3 Xcode MCP与宿主调试

发现当前Codex实际提供的Xcode/MCP工具和Xcode的外部agent权限，使用真实工具完成查询/构建/调试。工具名随环境变化，不虚构已调用。官方配置参考：[Apple外部agent访问Xcode](https://developer.apple.com/documentation/Xcode/giving-external-agents-access-to-xcode)。

宿主直接调试与工具包 `mcp-query` 证据采集是不同通路；后者受白名单、输入hash及原始响应协议约束。可用/configured/executed分开记录，MCP响应继续是tool evidence，不自动升级为编译绑定或业务真值。新工具/命令先用当前官方文档核对。

### 6.4 Darwin计时身份（明确未完成）

`src/hmigbot_ios/usage_budget.py::_boot_id` 当前只实现Windows注册表和Linux boot UUID，Darwin返回None并使计时UNKNOWN。**本轮没有实现或验证Mac启动身份，因此即使Mac调用用量完整，也不能直接拿账本声称2小时通过。**

在Mac查官方支持的稳定boot/session identity，实际采集并跨进程验证；只读身份不能用可调墙钟推导。补重启/身份变化/读取失败/墙钟回退/单调钟不一致负例，保持不确定性sticky，再回归现有计量。不要为了PASS删除检查或伪造boot id。

## 7. 在途预算怎样用，哪些仍需接宿主

默认账本 `spec/reports/derived/usage-budget.json`，完整工作开始前 `usage-start`。调用前用 `usage-reserve --input <reservation.json>`；实际返回后 `usage-record --input <usage.json>` 用同一call-id与身份结算。确实未发起的预留可 `usage-release --input <release.json>`，原因留账；丢失usage须UNKNOWN，不能取消伪装成未调用。准确字段/示例见 [预留操作说明](USAGE-RESERVATIONS.md)。

API不预测模型开销；上界必须含实际input/cache、输出、允许重试，各attempt另用唯一ID。已用+在途+新预留在锁内核对；实际超过预留也必须记录。预留额度不是实际消耗，未结算不能finish为PASS。不要把聚合和组成调用重复记账。

`next-batch`现有 `--usage-ledger/--usage-run-id`仍是显式检查；**不自动为批次预留、不自动发现主线程/子代理漏报，也不阻止已运行请求继续花费。** 正确顺序是获取待执行批次，再为真正调用预留；额度被现有预留占满时，普通next-batch会拒派更多工作，已有许可的调用由宿主执行。未来完整接线须明确task→call-id/attempt→预留许可→原始usage与失败回收，不把泛检查当执行许可。

后续宿主适配应导出独立调用清单并与账本对账，缺调用/重复范围保持UNKNOWN；自动run绑定、恢复与主/子调用覆盖仍待实现/实证。此项是宿主集成工作，不是只有Mac才能写；Mac会话可继续完成并用真实调用验证。

## 8. 鸿蒙侧与双100%验收还缺什么

Mac可用不表示鸿蒙SDK/JDK/Node/ohpm/hvigor、签名和设备已就绪。按 `doctor` 和原hmos环境/build技能核验；缺项不妨碍独立源采证，不能用iOS成功替代目标成功。

Windows旧目标目录中曾出现HAP/19小时记录或192AC等历史，较新main现场为5features/15pages/134AC但生成状态陈旧、构建/行为/视觉未跑。它们绑定不同工具/源/目标，不能拼接成当前成功。本轮没有修改iOS或鸿蒙应用、旧spec或旧控制账本。

完整终局profile仍需实现实际producer→consumer闭环：独立源页面/状态/环境与行为分母，当前两端同状态截图/操作，当前包/源码/规格/环境绑定，逐状态/AC结果，批准替代/未支持/未知留账，summary/report消费并防止陈旧证据复用。`page_evidence`的visual not_run、局部verify PASS、ALIGN建议都不是完整视觉通过。

先用≥10条独立oracle真实业务链和1–2类变异负例打通执行腿，再完成Cuike全部必验矩阵；“10条”只是试点，不是100%。测单状态和全矩阵耗时，评估设备串行下界。若完整矩阵超2小时，报告未达标并优化场景准备/并行/自动化，不缩分母或把验证移出计时。

## 9. 下一阶段出口与交付

1. Mac基础回归、安装和真实Cuike源构建结果可复现，工具/源/环境与artifact摘要齐全。
2. 原生证据精确消费有正反例，Windows回退无回归；真实语法、绑定、运行分别有据。
3. 当前目标真实构建、业务和双端视觉结果汇入；失败能指向受影响AC和原owner。
4. 20k/50k真实工程再到100k/200k，先测真实LOC与可构建性、固定SHA与技术覆盖。合成100k/200k采集仅约14.8/27.2秒、峰值约328/627MiB，不含转换/模型/序列化全流程，不能当整工程成绩。
5. 100k完整≤7200秒、全调用<20M、双100%须在同一当前输入同时成立。200k容量与质量另证；500k继续是未来扩展测试。

每次交付说明改动、为什么、当前测试/设备证据、未验项及恢复步骤。GitHub有源码不等于新Mac已安装运行正确副本；先核对实际路径和版本，再继续。保持当前失败和中间产物，不补写done/PASS标记。
