# iOS 1.5.2-ios.14 · 字号单位知识修正（2026-10-24）

- 修正从安卓 1.5.2 沿用的 `arkts-large-font` 知识矛盾：`SymbolGlyph.fontSize` 的裸数字默认 fp；固定系统字体缩放依靠局部 `minFontScale(1).maxFontScale(1)`，是否固定仍按源语义决定。仅修正该 skill 与 patterns 的四处说明，现有 API 示例调用、流程、模板和门禁保留。
- 依据本机官方 SDK `ets/component/symbolglyph.d.ts:619–641` 的 `Unit: fp`、`:778–805` 的缩放 API 声明。该结论只适用于 `fontSize`，不将 width/height/padding 的裸数字单位改成 fp。
- 独立副本实施；本条不是新轮流水线完成或设备验收证明，实际回归与重跑证据单独记录。

# iOS 1.5.2-ios.13 · Mac 官方输入适配（2026-10-23）

- 当前安装面向 Mac；直接发现完整 Xcode、编译器及 SDK。
- OpenStep 语法转交 Apple plutil；正式 Swift 词法、声明、枚举及静态字符串解码使用 SwiftParser / SwiftSyntax。
- 原子条件查询与完整表达式对照使用目标 iOS 编译器，SwiftIfConfig 在原始坐标选择分支；保留 unknown 与原证据校验。
- 新增真实 Release 查询/无签名构建捕获；仅去重 Xcode 逐字段相同的配置条目，缺省 flags 与实际 SwiftDriver 参数核对。
- 原阶段、F/AC、模板、覆盖门禁与原编译程序保留；历史 Windows 回归不冒称本轮 Mac 验证。当前验证以独立本轮报告为准。
- 修正结构检查读取 CRLF frontmatter 名称的行尾处理；安装时仅对本包清单内、当前架构且哈希核对一致的原生程序逐文件处理下载隔离标记，保留原升级保护及事务回滚。
- 官方数字 token 消除 `$0` / `$1` 的伪常量；十进制下划线数字标准化并保留原表达式，未解码的非十进制数单独记账。INIT / 原生输入说明同步 Mac 本地捕获与自动 provider 流程。

- 2026-10-24 Mac 实测补修：收口器将宿主精确的纯文本非法任务名拒绝归为失败派发，保留原请求及错误；不改名、不造句柄、不放行旧失败。未知纯文本仍拒绝，原JSON错误/成功与授权空工程恢复语义不变。专项12项回归通过；本轮EXECUTE尚未完成。

- 2026-10-24 Mac 构建实测补修：原签名探测引擎传绝对项目路径会误报配置不存在；Mac launcher 对单个已存在项目目录先解析调用方路径，再用对应 cwd 与 `.` 调原引擎并同步 PWD。原签名判断、证书链及 profile 到期检查、输出和退出码保留，不改用户签名或引擎字节。14 项真实引擎对照通过；回归见 `evaluations/test_signing_path.py`，R4 在正式 assemble 前停止并按授权重新从空工程运行。

# iOS 1.5.2-ios.12（2026-10-23）

- 修复环境体检公开 argv 入口，支持项目路径、报告、帮助和有界超时。
- 补齐 SDK/工具版本、设备列表、签名材料、HAP 权限与库模块边界；修复 JSON5 转义、跨平台路径及继承输出句柄问题。
- 原编译二进制字节保留；原生诊断实现和边界明确披露。保留 ios.11 的日志范围和恢复登记修复。
- Windows 完整回归 644 passed、2 skipped、51 subtests passed，exit 0。两项 skip 为 WinError 1314 目录符号链接权限。结构检查 99 skills / 22 agents PASS。独立 Clidex Claude 仅文字复核，最终未发现阻断项，未独立执行测试。Mac/Linux 真实环境未验证；本版 INIT→EXECUTE 尚未完成，没有最终 HAP 或应用行为结论。

# iOS 1.5.2-ios.11（2026-10-23）

- 顶层及内部收口入口以实际 CODEX_THREAD_ID 绑定自身完整原生日志，修复按同目录混计不同会话的缺陷。
- 增加授权恢复后的同宿主尝试登记：完整归档、核验事先批准的空备份并安装后，在 INIT 前登记；旧失败保留，原日志不修改，当前任务仍需真实 completed 与产物契约。
- 补齐完整任务列表的筛选及调用时序检查、失败派发的补派要求、历史任务别名及子树隔离、安装文件实物哈希核对。
- seal 要求显式传入事先批准的空备份清单 SHA；拒绝将含 spec 或迁移配置的目录作为空备份。登记写出 created 后又非零退出的调用不再被当作可忽略失败。
- 保留 ios.10 的枚举词边界、跨行逗号及关联值/switch 修复。
- 规范登记绑定实际独立进程，支持从同一真实进程 session 的空 stdin 续取退出码；拒绝进程编号复用、输出截断预算及非规范调用。
- Windows 完整回归 617 passed、2 skipped、51 subtests passed（exit 0）；两项 skip 为 WinError 1314 目录符号链接权限。结构检查 99 skills / 22 agents PASS。独立 Clidex Claude 仅做文字复核，最终回复未发现阻断项，未独立执行测试。Mac provider 构建与 App 运行尚未验证；本版 INIT→EXECUTE 尚未重跑，无 HAP 或应用行为验证结论。

# iOS 1.5.2-ios.10（2026-10-23）

- 修正 ios.9 枚举扫描器的切片词边界回归：参数标签 showcase value: Int 不再误报 value；.lowercase 后换行的真实 case disabled 不再被吞掉。
- 在原字符串位置匹配 case，核对前置分隔符并排除括号/方括号内部，保留 ios.9 的关联值、switch 和嵌套 enum 修复；用真实 Swift 语法样例和原门禁回归。
- 修复合法的跨行逗号枚举声明，例如 `case a,` 换行接 `b`、以及 `case a` 换行接 `, b`；保留真实漏项的 exit 2 门禁。
- 补齐 CRLF、注释、字符串及正则边界回归；扩展正则在 Swift 词法入口明确要求语法提供器，避免括号污染、enum 外伪声明和 #// 吞掉同一行真实 case。保留直接枚举扫描的防御检查。裸正则仍属于已知词法限制。

# iOS 1.5.2-ios.9（2026-10-23）

- 修正 Swift enum case 实例提取：关联值中的逗号与 enum 内 switch 模式不再生成伪实例，嵌套 enum 的 case 归属其实际类型。
- 嵌套 enum 实例 ID 语义变更：例如原误归属的 `enum:WalkSuitabilityLevel.recommend` 改为 `enum:DisplayTier.recommend`；旧短 ID 不自动视为新 ID 的记账声明，规格需按新 ID 复核。
- 保持真正未对账实例的 `INSTANCE_UNACCOUNTED` 严重度及 exit 2 门禁。

# iOS 1.5.2-ios.8（2026-10-23）

修正可达阶段的原生源语言与页面示例输入；原阶段、目标门禁与全部已验证修复保留。验证结果以本版最终交付记录为准。

# iOS 1.5.2-ios.7（2026-10-23）

修复原生 UI 图身份字段与原只读校验、查询接口的接线；校正原生 UI 输入文档和映射参考。原阶段与目标引擎保持，既有修复保留。

# iOS 1.5.2-ios.6（2026-10-23）

修复独立内部流水线任务的原生日志收口作用域；顶层继续使用原引擎，子线程按同一直接子任务规则解析自身完整原始记录。此前原生输入和发行身份修复保留。

# iOS 1.5.2-ios.5（2026-10-23）

统一插件、运行模块、安装身份与发行说明的主动版本，增加包含隐藏清单的版本契约回归及实际安装/升级断言。此前原生输入与门禁修复全部保留，历史记录不覆盖。

发行版本 `1.5.2-ios.N` 对应 Python PEP 440 版本 `1.5.2.N`。安装版本权威记录为 `.hmigbot-ios/install.json`，来源为包内 `.codex-plugin/plugin.json`；项目配置的 `tool_package` 是稳定包标识，不是发行版本，不新增冗余字段。

# iOS 1.5.2-ios.1（2026-10-23）

独立移植 iOS 1.5.2 输入层，保留原流程、模板结构和规则；复用已验证的 iOS 工程、Release 条件、资源与路径修复。独立安装、项目归属和包内路径隔离；C4.6b 显式采用原 ownership 兜底。详细边界见 README.md 和 docs/RELEASE-INPUT.md；验证证据单独交付。

---

# Changelog

本文件记录 hmigbot-CodeX（原 migbot-CodeX，2026-08 改名）（Codex 版 iOS → ArkTS / HarmonyOS 迁移插件包）各迭代的关键改动。

## [version v1.5.2] - 2026-08-31

本次 skills 同步（来自 ArkTs-Core `version_830_codex_v`）修掉三类静默失效：领域 agent 装了从不被派发、打点调用指向不存在的二进制、装机脚本重跑会叠加内容。

### 🐛 修复 (Fixed)

* **领域 agent 装了却从不被派发**：22 个 `arkts-*` 领域 agent 随 `agents-codex/` 正常装进 `.codex/agents/`，但「主会话何时派发、派给谁、怎么校验回复末尾的 `loaded_skills:` 行」这条规则只写在上游的 `AGENTS.dispatch.md` 里，`install.sh` / `install.ps1` 从不读它 —— 契约只送到一半（agent 侧的自律条款随 `*.toml` 同步了，调度端的规则没有）。**失败是静默的**：22 个 `.toml` 全部正常，看不出异常，只是永远没被 `spawn_agent`。现在 `install.sh` 新增 §5b、`install.ps1` 新增 §5c，把 `AGENTS.dispatch.md` 以「替换或追加」方式写入 `AGENTS.md` 的 `arkts-domain-agents` 标记块，沿用同文件 `migbot-platform` 块的既有惯用法；`install.sh` 用纯 awk 实现，不引入 python3 依赖。原 §5 的 `migbot` 空标记块逻辑一字未动，两个块共存互不干扰。
* **装机脚本重跑会叠加内容**：上游 `AGENTS.dispatch.md` 的 `arkts-domain-agents:end` 标记原在文件中段，其后的「设备截图落点纪律」一段落在标记块**外面**，而注入是「用整个文件替换标记块」⇒ 每装一次块外内容追加一份（实测 17 → 23 → 29 行）。上游已把结束标记移到文件末尾，整个文件成为一个受管块；三连装稳定 25 行、每块各 1 个。
* **打点调用指向不存在的二进制**：五个流水线 skill（`a2h-spec` / `plan` / `execute` / `verify` / `retrospect`）收尾调的是 `.migbot/bin/a2h-codex mark-stage`，而 v1.0.1 起运行时只装 `a2h`（`a2h-codex` 是已退役的发行别名，`install.sh` 还会主动删除它）。这些调用旁标注「忽略退出码、绝不阻断流水线」，于是 8 处全部 `no such file or directory` 且被静默吞掉 —— 流水线表面全绿，**看板永远收不到阶段水位**。上游已改用 `a2h`，并修掉转换器里把二进制名连同子命令一起替换的改写规则。
* **`validate.sh` 三条硬失败清零**：skill 目录 `ios2hmos_resources_convert` 改名为 `ios-resources-convert`（对齐 `NAME_RE`，与既有的 `hmos_fix_build_errors` → `hmos-fix-build-errors` 同款处理）；`a2h-execute` 参考文档里两处 `.claude/skills` 残留改为单平台陈述；6 个 `agents-codex/*.toml` 里的下划线 skill 名一并更正。

### ⚠️ 升级提示

* 已有工程重装后，`AGENTS.md` 会新增 `arkts-domain-agents` 标记块（幂等，重复安装不叠加）；块内内容由上游生成，请勿手改。
* 若此前手工建过 `.migbot/bin/a2h-codex` 软链作为绕行，`install.sh` 会自动清除，不再需要。

## [version v1.5.1] - 2026-08-30

统一版本线 1.5.1：配套运行时 migbot-runtime-src v1.4.7、服务端 migbot-server v1.2.32。本版把**同意改为安装级**（一台机器同意一次，新工程自动继承），`migbot_session_id` 改为每工程一个，用户数按 `install_id` 去重。

- **Install-level consent (agree once per machine)** (with migbot-runtime-src ≥ v1.4.7, migbot-server ≥ v1.2.32): `a2h init-run` mints/reuses this machine's `install_id` (`~/.migbot/install.json`) and inherits the machine's consent decision into new projects; `a2h-init` §2.1 and `a2h-privacy` §B run `init-run` before showing the agreement, so a project that inherits `granted` no longer prompts. `migbot_session_id` is now **per project** (one dashboard row = one project); users are de-duplicated by `install_id`. `/a2h-privacy status` also shows `install_id` — one deletion request clears every project on the machine.
- Runtime binaries synced to migbot-runtime-src **v1.4.7**.

## [version v1.5.0] - 2026-08-27

版本线统一：自本版起与 hmigbot（Claude Code 线）同号发布（1.5.0），配套运行时 migbot-runtime-src v1.4.3。功能内容承接 v1.0.1（见下），另含 publish 版本门禁与 publish-lite secret 名修正。

## [version v1.0.1] - 2026-08-27

本次迭代主线是「打点能力与 hmigbot 一致」：二进制统一命名 a2h（a2h-codex 别名退役）、a2h-init / a2h-privacy 改为从 hmigbot commands 机械生成、同意流程幂等化、hook 信任自检。配套运行时 migbot-runtime-src v1.4.1+。

### 🔧 变更 (Changed)

- **a2h-init / a2h-privacy（中英四份）改为从 hmigbot 的 `commands/*.md` 机械生成**，脚本 `scripts/sync-commands.py`（取代一次性的 `.convert/commands.py`）。宿主差异全部收敛在脚本里：`/`→`$`、`a2h-bootstrap`/`a2h-agreement` 路径、plugin 与 install.sh 措辞、剥离 Claude Code 专属 OTel 清理、注入 Codex 专属 hook-trust 自检。**不要再手改这四个 SKILL.md**——改 hmigbot 的 command 后重跑 `python3 scripts/sync-commands.py --src <hmigbot>/commands`；`--check` 可做漂移检查。
- 生成结果与此前手改版对比：a2h-privacy 逐字节相同；a2h-init 仅措辞级差异（以源为准）。


### 🔧 优化 (Improved)

* **遥测二进制统一命名 `a2h-codex` → `a2h`**：运行时二进制与 hmigbot（Claude Code 版）的 `a2h` 本就是同一个程序，`a2h-codex` 只是发行别名。现在两个插件统一使用 `a2h` 这一个名字：`bin/a2h-<os>-<arch>[.exe]` 六个平台产物、`install.sh` / `install.ps1` / `a2h-bootstrap(.ps1)` 就位路径（`.migbot/bin/a2h`、`.migbot\bin\a2h.exe`）、`.codex/config.toml` 的 `[hooks.*]` 命令（`./.migbot/bin/a2h hook`）、全部 skill 中的 `init-run` / `mark-stage` / `hook-trust` / `count-lines` 调用、`validate.sh` 与发布 workflow 的断言、README / PORTING 文档一并改名。子命令集合不变。
* **旧安装自动迁移（幂等）**：`install.sh` / `install.ps1` 若检测到 `.codex/config.toml` 中仍是 `a2h-codex hook` / `a2h-codex.exe hook`，会原地改写为 `a2h`（只替换该 token，其余内容不动，可反复执行）；就位 `a2h` 后同时删除磁盘上残留的 `.migbot/bin/a2h-codex[.exe]`，`a2h-bootstrap(.ps1)` 的清扫列表亦同步加入该旧名。注意：改写 hook 命令行后 Codex 的 hook 信任 hash 会变化，需在 Codex 里重新 `/hooks` 信任一次（安装尾声的 `hook-trust` 自检会提示）。


本次迭代的主线是「让计划变轻、让执行可追责」：plan 产物从 127KB 单体文件重构为「索引 + 逐切片账本」的分层形态并由多个 subagent 并行生成；execute 的收尾链路统一到单一收尾者与脚本化回写，崩溃后秒级恢复；spec 侧引入证据驱动的覆盖门禁与 AC 级追溯，让「被静默漏掉的需求」在每个阶段都会被机械点名。全部改动均由 aippt / jetsnack 多轮端到端验证驱动。

改动同步自源仓库 ArkTs-Core：[#77 a2h-plan/execute 分层优化]、[#79 Spec 证据驱动覆盖门禁]，及 version_815_planFix 分支的后续调度修正。

### ✨ 新增 (Added)

* **证据驱动覆盖门禁（a2h-spec）**：从 iOS 源码机械检出行为信号与具名实例（埋点事件、桥方法、枚举、阈值等），逐实例记账——每一条要么被 AC 认领、要么显式跳过并披露，漏账即阻断。取代旧的「AC 数量预算」，数量不再参与判定。
* **AC 级跨阶段追溯**：spec → plan → execute → verify 每阶段一份账本、一个 linter，漏认领 / 绑旧断言 / 双实现自动检出并定责到具体阶段；同一问题多轮不收敛自动熔断，转为决策卡交用户裁决。
* **plan 三写并行编排**：ui-plan、base-plan、全部切片账本由三个 subagent 并行生成，主线程只负责全局裁决（拓扑、归属、分组）与收拢审批。
* **统一收尾者 + 回写脚本**：execute 各阶段收尾统一为一个四模式 agent；状态账本与 brief 的落盘交给幂等脚本执行——收尾崩溃后重跑脚本即恢复，不再重做接线与编译。

### 🔧 优化 (Improved)

* **计划体量与读取开销大幅下降**：plan 产物 127KB → 约 33KB（-74%），执行期 plan 相关上下文读取约 -95%；subagent 返回一律压缩为 30 行内信封。
* **编译链路精简**：删除 Stage 1 逐批编译门（页面互不依赖，统一在阶段末一次容忍性编译收口）；全程增量构建 + 环境预热；发布门强制真实构建防「空转假通过」。
* **调度规则收敛**：UI 分批改为纯优先级分组；单任务的组/批一律消除（并组、附挂或并批）；组容量改为直接按切片数计数，不再加权。
* **spec 生成提速**：最长的 api-inventory 子任务前置隐藏约 15–18 分钟；切片生成即自检，覆盖修复不再拖串行尾巴；DataBinding 与自定义资源目录的布局解析一次通过。

### 🐛 修复 (Fixed)

* **切片被按步骤拆成多个 subagent**：废除单元化波次派发（实测有害无益），改为每切片恒一个 worker，确实过大时按依赖断面拆分。
* **444 条「需求未认领」**：根因是记账缺口而非实现缺口——实现认领现由收尾者从计划账本自动抄录、随回写脚本落盘。
* **结构验证产物写错目录**：Windows 下手动驱动脚本时误写 docs/，现脚本层硬拒旧路径并指引正确落点。
* **旧术语泄漏**：生成产物中残留的 handoff 旧称全量清理为 brief。

### ⚠️ 兼容性：

* 旧版单体 feature-plan 会被明确报错并提示重新生成计划（执行进度存于状态账本，重排零损失）；旧产物中的已废弃字段可被解析器容忍，无需迁移。

## [version v0.2.0] - 2026-07-30

本次以**登录能力落地**与**多项 skill 自优化**为主线：新增登录功能，并对 skill 自优化、visual verify、spec 分层分级三条能力线做了一轮打磨。

### ✨ 新增 (Added)

- **登录功能实现**：接入登录能力，迁移插件包在使用前具备账号登录入口。

### 🔧 优化 (Improved)

- **Skill 自优化**：对 skill 自优化闭环做一轮打磨，提升迭代优化的稳定性与效果。
- **Visual verify 优化**：优化视觉校验（visual verify）流程，提升 UI 验证的准确性与可用性。
- **Spec 分层分级优化**：优化 spec 的分层、分级机制，改善规格内容的组织与消费。


## [version v0.1.4] - 2026-07-24

本次以**补齐编排型 skill 的前置配置**为主线：`config-seed.toml` 开箱写入 Codex 多线程编排所需的三项配置，安装器对已有 `config.toml` 的老用户做幂等补写，并新增三键守护校验。本版仅配置与安装器变更，`a2h-codex` 六平台二进制未重编，与 v0.1.2 完全一致。

### ✨ 新增 (Added)

- **`config-seed.toml` 补齐编排三项前置配置**（#2，Closes #1）：编排型 skill（`a2h-execute` / `a2h-verify` / `arkts-visual-verify` / `arkts-ut-verifier`）依赖 Codex 的多线程编排能力，seed 现在开箱写入 `[features] multi_agent = true`、`[agents] max_threads = 6`，并为原有的 `max_depth = 2` 补上默认值说明。
- **安装器对老用户幂等补写**：老用户已有 `config.toml` 时 seed 不会拷贝，此前这三项前置配置只能手工补。`install.sh` / `install.ps1` 镜像 `hooks=true` 的模式新增：
  - **4a'**：幂等补写 `multi_agent = true`——表内插入、不写重复表头；用户显式配置了 `false` 时只告警不覆盖，尊重用户选择。
  - **4a''**：检测到 `max_depth < 2` 时告警不改值。

### ✅ 校验 (Validated)

- `validate.sh` 新增三键守护检查（`multi_agent` / `max_threads` / `max_depth`），本地跑通：`VALIDATE: PASS`（skills checked: 89，agents checked: 7）。

### 📝 文档 (Docs)

- README / `docs/PORTING.md` 同步，顺带修正 `docs/PORTING.md` 过期的 `max_depth = 1` 表述。

### 🔗 配套服务端版本 (Server)

- 无服务端配套要求，本版不涉及打点链路。

> **二进制说明**：本版仅配置与安装器变更，`bin/a2h-codex-*` 六平台二进制未改动，与 v0.1.2 完全一致（未重编）。
