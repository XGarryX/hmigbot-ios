---
name: ios-api-inventory
description: "iOS→HarmonyOS 迁移源分析第 4 类（API 接缝层）：从 Swift/ObjC 源码提取外部服务契约（URLSession/Alamofire/GraphQL/WebSocket/SSE/WKWebView bridge）、系统框架与权限/entitlements/privacy、三方 SDK 与本地桥接接缝，产出带源锚点与调用证据的 api-inventory。当用户说“梳理这个 iOS 项目的接口/API/权限/三方 SDK”“盘点 iOS 侧系统能力”或 a2h-spec 组织四类分析时使用。不要用于：工程边界与 target 成员（用 ios-project-inspector）、UI 结构（用 ios-ui-analyzer）、功能行为链（用 ios-feature-analyzer）、目标库选型与移植实现（用 arkts-library-migration 等 arkts-* 技能）。"
metadata:
  type: domain
  domain: migration
  tags:
  - ios
  - analysis
  - api
  - evidence
---

> **调用关系**：本 skill 是 `ios-source-analysis` 组织的四类分析之一（API 类），负责「服务/系统能力/权限/三方接缝」维度。本 skill **不派发 subagent**，全部步骤在主会话或由派发方（a2h-spec / ios-source-analysis）作为子代理调起执行；若作子代理调起，任务书自足（写清源锚点、scope=api、输出契约），完成后由派发方按 Join 协议收口——**完成的唯一合法信号是 `agent_status=completed`，绝不是产物文件存在**；本 skill 自身不嵌套外派。
>
> 路径约定：`$IOS_SRC` 从 `<target>/.migbot/config.json` 的 `ios` 字段读取；`<target>` = 鸿蒙目标工程根；`<runtime>` = 本包 runtime（`scripts/a2h_ios.py` 所在根，可用 `<skill>/scripts/run.py --runtime-root` 解析）。产物落 `<target>/spec/`，**禁落会话临时目录**。机器信号文件（`ios-api-signals.json`）由 facts-view 单写，主会话/作者禁手改。

# ios-api-inventory — 外部服务、系统能力与三方 SDK 接缝

## 0. 定位与纪律

- **前置**：`<target>/.migbot/config.json` 存在且 `source_platform=ios`；上游已跑 `source-index` + `facts`（缺 → 提示先由 a2h-spec 完成 §1 基线启动，不代跑）。API 事实建立在机器 `facts` 之上，不另起炉灶。
- **输入**：iOS 源码（Swift/ObjC 调用点）、`Info.plist`、`.entitlements`、`PrivacyInfo.xcprivacy`、`Package.resolved`/`Podfile.lock` 等依赖锁定文件、公开接口与源测试。**依赖名只用于候选定位，不证明被使用**——真正调用点靠沿源码追。
- **输出**：`spec/baseline/api-inventory/{api-inventory.json,api-inventory.md}`（分层形态另加 `common.md` + `apis/<模块>.md`）；机器事实视图 `spec/ref/ios-api-signals.json`（facts-view 单写）。JSON 保留 HMigBot 契约 `services[].endpoints[].static.{http_method,path,protocol}` 与 `services[].auth_type`，另加 `source_platform: "ios"`、`source_anchors`、`fact_ids` 与平台能力表。
- **唯一交互点**：无。机械检查由 exit code 判定（0=PASS，非 0=FAIL）；业务判断全部下沉到门禁与 facts 裁决，不交互追问。
- **第一条可见输出必须是一行阶段计划**（机器事实 → 外部服务 → 系统能力 → 配置隐私 → 三方桥接 → 目标决策 → 验收），然后才执行 §1。

### 无人值守处置阶梯（每道门禁 FAIL 一律套用）

> FAIL → 按命令 `retry_hint`/错误原文派修复并重跑同一命令，**最多 2 轮**；2 轮仍不过或确定模型修不了 → **记欠账放行**（账记全：修过几轮、每轮失败原因、判“修不了”的依据）；要拍板的模型自决并留痕；任何分支不得停机呈报人工。设备/账号类门可欠账；静态门即便开了 `stage_debt` 也照常修到 PASS。

## 1. 机器事实与信号（先读，不手改）

| # | 命令 | 产物 | exit / 处置 |
|---|---|---|---|
| 1.1 | `python <runtime>/scripts/a2h_ios.py facts --project <target>` | `spec/baseline/ios-facts.json` + `ios-obligations.json` | 非 0 读错误原文修配置重跑，最多 2 轮 |
| 1.2 | `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope api` | `spec/ref/ios-api-signals.json`（机器信号） | 非 0 = 依赖/调用点信号未抽全，补 facts 后重跑 |

- 先读 `ios-api-signals.json` 与工程依赖，**沿真正调用点**识别 URLSession/三方 client、存储、系统框架、权限、entitlements、xcprivacy、登录/支付/广告/客服接缝。**禁止手写或篡改机器信号**，也不采用上游重构建议改写源行为。
- 事实读法（源码证据分级）按 `../ios-source-analysis/references/source-semantics.md`；证据强度区分“源码位置 / AST / 符号服务 / 构建 / 运行”，**不能互相升级**，未解析的动态分派/宏/闭源模块进未知清单。

### 单写者分区（违者 PROCESS_VIOLATION）

| 文件 | 唯一写者 | 内容 |
|---|---|---|
| `spec/baseline/ios-facts.json` + `ios-obligations.json` | facts 命令 | 机器事实/义务 |
| `spec/ref/ios-api-signals.json` | facts-view 命令 | API 机器信号 |
| `spec/baseline/api-inventory/*` | 本 skill（模型作者） | 人类/机器契约 |
| `spec/.a2h/open-findings.json` | 产生该 finding 的检查 | 未关闭发现 |

主会话与作者手改上表“机器/命令单写”文件即契约违规。

## 2. 外部服务契约

- 从实际调用（URLSession、URLRequest、自定义 client、Alamofire、GraphQL、WebSocket、SSE、WKWebView bridge）追 `method/path`、base URL 选择、header、编码、签名、token 刷新、超时、重试、分页、缓存与错误信封。
- **源码未确定的 URL 片段/响应类型显式标 `dynamic`/`unknown`，不拼造完整端点**。endpoint 三段式契约中本 skill 只写 `static` 段，`runtime`/`reconciled` 一律留 `null`（归 arkts-network-troubleshoot 侧回填）。
- 公共鉴权与公共参数放 `common.md`；每个功能 spec 引用所属 endpoint ID，不重复展开。响应结构强制记录 `model_class`（响应类型），读不到时标 `model_class: "unknown"` + 原因，**不省略整个 response**。
- 硬约束：**不抄源签名/账号配置到目标**；目标 bundle、证书、支付/推送注册各自核验，目标是另一套凭据域。

## 3. 系统能力矩阵

- 为每个使用点记录：框架、方法、触发、返回数据/句柄域、回调线程、权限前后状态、应用与扩展可用性、设备/版本限制、后台约束、失败表现。
- 覆盖实际出现的相机/媒体/相册/位置/蓝牙/NFC/通知/后台/联系人/日历/文件/分享、StoreKit、Sign in with Apple、HealthKit、CloudKit、WidgetKit、App Intents 等能力。**列表只是检查线索**：未出现的能力写「不适用」，不能给任意应用捏造接口。

## 4. 配置与隐私

- 交叉核对调用点、usage descriptions、entitlements、URL schemes、associated domains、ATS、App Groups、Keychain groups、背景 modes 与 privacy manifest。
- **用途字符串只证明声明，不能证明用户实际授权**；权限拒绝与撤销路径继续读实现，不能停在 Info.plist 键。
- 隐私事实按 `../a2h-privacy/SKILL.md` 的口径记录敏感数据流（存在时），仍以本 skill 的接缝身份交出权限边界。

## 5. 三方与本地桥接

- 每个依赖记录版本、源码可见性、调用点、数据协议、资源、初始化/释放与平台限制。优先查厂商官方鸿蒙支持与对应版本，再查公开实现；保留来源日期与实测状态。
- **NAPI 方案必须定义类型、缓冲区、所有权与线程边界；禁止把 `.xcframework` 改扩展名当目标库**。无法读到的内部行为记 `opaque` 并指定所需公开契约或运行证据。

## 6. 目标映射与决策

- **映射不是 API 名字替换**。区分「行为等价但实现不同」的 HARD 与「行为变化」的 HARD-DIV。
- **HARD-DIV 必须有决策 ID、源行为、替代数据流、被替代 AC 与新差异 AC**，按本轮授权确认产品选择；未知工具能力不能伪造为可用。
- 目标库核验交 `arkts-library-migration` / `hmos-sdk-docs`；选择依据须匹配当前 SDK 与实际接口，不能靠相似名称。目标实现按实际领域使用 `arkts-system-capabilities`、`arkts-data-layer`、`arkts-login`、`arkts-payment`、`arkts-media-playback`、`arkts-webview` 等技能（引用技能名作下行衔接，不在本 skill 展开）。

## 7. 外部资料与工具证据

1. `python <runtime>/scripts/a2h_ios.py expertise-plan --project <target>` → `spec/ref/ios-expertise-plan.json`；按本轮 API 主题清单读取实际上游资料（swiftui/concurrency/uikit pack 中与本 skill 相关项），再用 `expertise-review --input <review.json>` 提交源观察。未连接工具保持 `unknown`/`unavailable`；**不伪造官方执行**。
2. 需要符号证据时 `python <runtime>/scripts/a2h_ios.py mcp-query --project <target> --server <server.json> --request <query.json>`（示例见 `../ios-source-analysis/assets/mcp-server.example.json` 与 `mcp-query.example.json`）。只有固定源读工具白名单可调用；失败/超时写 failure.json，绝不写成功索引。
3. 工具来源、版本、实际是否执行写入 provenance；源码、Apple 文档、运行 trace 三源分列，不自编规程冠为官方。

## 8. 输出验收（门前自检）

- 每条记录可回到源文件:行；公共字段与 feature 引用一致；动态部分保留表达式与依赖。
- **没有设备或服务账号的测试保留 `not_run`，不用静态调用存在声称设备功能通过**。发布报告分开列生成、编译、协议观察与设备结果。
- 与 UI/功能作者的交接按 `references/analysis-v2.md` §「与功能/UI作者交接」：共享鉴权/数据类型/协议/生命周期放公共合同；领域动作的终态交唯一 feature/base 作者，本清单引用动作 ID 不另写终态。
- 源码变化时：重提 `facts`、重跑 `expertise-plan`、重审受影响项；旧清单/记录归档，旧 PASS 不继承。

## 9. 读取时机（references）

| 触发时机 | 必读文件 |
|---|---|
| 执行前确定机器产物/状态写者 | ../ios-source-analysis/references/harness-v2.md |
| 源码证据分级、动态分派/宏处置 | ../ios-source-analysis/references/source-semantics.md |
| facts 前身份/字段/溯源规则 | ../ios-source-analysis/references/native-facts.md |
| expertise-plan/review、MCP 查询边界 | ../ios-source-analysis/references/external-expertise.md |
| 服务/系统/三方接缝提取与交接 | references/analysis-v2.md |
| 与功能作者定义动作终态 | ../a2h-spec/references/action-contracts.md |
| 产物 profile/格式/作者/消费者 | ../a2h-spec/references/artifact-contracts.md |
| 可选 JSON 协议（api-contract-links.json） | ../a2h-spec/references/optional-json-contracts.md |

## 10. 交接

- 门前闸：`python <runtime>/scripts/a2h_ios.py source-check --harness --project <target>` exit 0 才交接；含 external-expertise 门禁（资料摘要/清单新鲜度/必需审阅/源范围）。FAIL 按 §0 阶梯最多修 2 轮，记欠账放行时如实呈报。
- 移交产物：`spec/baseline/api-inventory/*` + `spec/ref/ios-api-signals.json` + 审阅记录与 provenance 片段。随后把平台能力无法等价的项与决策 ID 交 `decision-ledger`，并把本层证据交回 `ios-source-analysis` / `a2h-spec`（同会话可直接续跑 Phase C 功能 baseline）。
- 本 skill 无独立 stage 水位（无 mark-stage）；`source-check --harness` 绿即是本维度的最终收口。