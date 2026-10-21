---
name: arkts-network-troubleshoot
description: "iOS→HarmonyOS 网络层排查与契约对账：对照 iOS 的真实服务契约（URLSession/Alamofire/组合管道）排查鸿蒙网络行为差异，检查请求/响应、TLS、鉴权、编码、缓存、取消与错误，并用独立契约证据验证修复。正向预防：迁移网络层时逐维度对账（method/path/query/header/token/签名/时钟/响应信封/ATS→鸿蒙安全策略/取消顺序）；反向救火：联调出现 401/500/签名错/空 body/未登录态等典型症状时按症状→维度→修复排查。当用户说“鸿蒙后端调不通 / 接口报错 / 签名错 / 请求/响应不一致 / 下游与 iOS 行为不一样”时触发。不要用于：源接口静态盘点（用 ios-api-inventory）、目标网络层具体实现写法（用 arkts-data-layer）、纯 DNS/代理环境问题（用 hmos-env-doctor）。"
metadata:
  type: domain
  domain: data
  tags:
  - ios
  - network
  - migration
  - troubleshoot
  - contract
  - http
  - sign
  - tls
---

> **定位与边界**：本 skill 只做「iOS↔鸿蒙网络契约对账 + 差异修复验证」。源侧接口/签名/鉴权的**静态**清单由 `ios-api-inventory` 抽取（写 `api-inventory.json` 的 `static` 段）；`runtime`（真实请求实测）与 `reconciled`（static↔runtime DIFF）由本 skill 回填——两个 skill 不抢写同一段。目标网络实现写法走 `arkts-data-layer`。
>
> 本 skill **不派发 subagent**，主会话（或 a2h-execute 子步骤）执行。路径约定：`$IOS_SRC` 从 `<target>/.migbot/config.json` 的 `ios` 字段读取；产物落 `<target>/spec/`，禁落会话临时目录。本 skill 自有脚本：`scripts/extract_startup_requests.py`、`scripts/http-capture-proxy.js`、`scripts/verify-sign.js`。

# arkts-network-troubleshoot — iOS 与鸿蒙网络契约核对

## 0. 定位与纪律

- **前置**：先读 `ios-api-inventory` 的 endpoint/common 契约和受影响 feature 的 AC，再读 `arkts-data-layer` 中实际使用的目标网络实现。**源静态 URL 线索不是抓包结果**。
- **输入**：源真实服务契约（已授权的真机抓包/云日志/代理 或 无设备时的静态分析）+ 目标网络实现 + 联调错误。
- **输出**：逐维度对账结论 + 最小根因修复 + 契约/单元/设备检查结果 + 真实请求脱敏摘要与退出结果。
- **第一条可见输出必须是一行排查计划**（固定证据条件 → 逐维度对账 → 症状定位 → 最小修复 → 独立验证），然后才执行 §1。
- 无人值守处置阶梯（门禁 FAIL 一律套用）：FAIL → 按命令 `retry_hint`/错误原文派修复并重跑，最多 2 轮；2 轮仍不过或确定模型修不了 → 记欠账放行；要拍板的模型自决并留痕；任何分支不得停机呈报人工。

## 1. 证据边界（先固定，后对账）

1. **固定同一账号状态、服务环境、输入和时间条件**，再对比；区分**源 / 目标 / 服务端**三类证据，不混写。
2. **源运行证据门槛**：只有已授权且实际配置的 iPhone/云日志/代理才用于源运行证据；无设备则静态分析，不得用目标端 mock 响应作为源行为真值。
3. 涉及认证和用户数据的日志保留**最小必要脱敏证据**，不记录明文凭据。

## 1.5 底层差异对照（先建立直觉）

iOS 网络栈迁到鸿蒙 ArkTS 时的典型底层差异（原版“9 底层差异”按 iOS 语义改写）。**编译过 ≠ 联调通**，多数运行期失败落在这几类：

| iOS（源） | ArkTS（目标） | 后果与检查点 |
|---|---|---|
| `Codable`/`NSSecureCoding` 字段映射 | JSON 无编译期字段重命名；`JSON.parse as T` 仅不安全 cast | 字段镜像须显式做，核对 `model_class` |
| `URLSession` response 直接可用 | `@kit.NetworkKit` response 需显式 unwrap | 拦截器缺 unwrap → 调用者拿到错对象 |
| ATS（`NSAppTransportSecurity`） | 鸿蒙网络权限 + 明文/证书安全策略 | 缺 `ohos.permission.INTERNET` 请求未发出即被拒 |
| `URLRequest` header 直接构造 | ArkTS `response.header` 为 `Object`，禁 `[]` 索引 | header 提取需 JSON 桥接 |
| `URLSession` 取消（`Task.cancel()`） | 目标回调不感知取消/顺序无保证 | 旧响应覆盖新状态 |
| `URLCache`/`NSURLCache` | 目标缓存属性/策略差异 | 缓存命中路径与失效行为逐项核对 |
| `Combine` `@Published` / delegate 回调 | `@ObservedV2/@Trace` / `@Monitor` 订阅 | 订阅链路、线程归属核对 |
| keychain/凭据注入 | 目标凭据域是另一套（另一 bundle/证书域） | 不抄源账号/签名配置到目标 |

**写码前决策清单（三类标签）**：`[①源码可定]` 读 iOS 源自查填；`[②需真包]` 抓真实包验 / 无设备标待验；`[③策略待确认]` 先照搬源行为兜底 + 显式标记，待后端确认。工程有 `spec/decision-ledger.md` 时，②③ 先查已有 D 编号决策与 `api-inventory.json` 的 `uncertainties[]` 口径，不重复问、不重新猜；证不了的一律标待 verify，**绝不拿默认值/空值兜底**。

## 2. 对账维度（逐项核对，缺一不可）

| 维度 | 核对点 |
|---|---|
| 请求行 | method、path/query 编码、base URL 选择、URL 常量化是否漏前缀 |
| 头与鉴权 | headers、cookie、token 刷新时机、公参字段与值来源 |
| 请求体 | 字段抽取完整性、编码、签名字段顺序与时钟 |
| 响应信封 | HTTP/业务状态、空值、数值/时间单位、分页、缓存、重试幂等性、`model_class`（响应类型） |
| 传输安全 | ATS/TLS/证书 vs 目标网络安全策略、域名配置、权限、DNS/代理 |
| 取消与顺序 | URLSession/Combine/Task 的源取消/顺序，与目标回调相比是否导致“旧响应覆盖新状态” |

**硬约束**：**不能为绕过错误而关闭证书校验或记录明文凭据**；未连通服务时记录 `unverified`、保留可复现输入和下一步依赖，**不宣告网络等价**。

## 3. 执行路径

### 场景 A：正向预防（迁移网络层时，推荐）

按 §2 维度逐项对账，产生对账结论并落到 `api-inventory.json` 的 `runtime`/`reconciled` 段（对齐 ios-api-inventory 的三段式归属）：

1. 读 `spec/baseline/api-inventory/api-inventory.json` 的 `static` 段（无则先由 ios-api-inventory 产出）。
2. 逐 endpoint 按其真实请求/响应核对，回填 `runtime`；比对 `static` 产 `reconciled` DIFF。
3. 有真包证据的条件，用 `scripts/verify-sign.js` 逐字节核对签名；无真包则标待 a2h-verify 补做，不阻塞实现。

### 场景 B：反向救火（联调已出错）

按「症状 → 维度 → 修复」定位：先落到 §2 的具体维度，再最小修复，回到同一链路重跑验证。常见症状映射：401/未登录态 → 鉴权/token 刷新/cookie；签名错/`signature` 空 → 签名字段/时钟/参数顺序；空 body/异常 → 响应模型空值守卫与 `model_class`；请求未发出即拒 → 网络权限与安全策略。

## 4. 修复与验证

1. **最小根因修复**，不顺手改无关逻辑。
2. 执行对应 contract/unit/device 检查，记录**真实请求脱敏摘要与退出结果**。
3. 修复后回到同一条件重跑，确认差异消除后再继续下一个差异。
4. 任何“硬覆盖”（绕过校验、写死值）必须在 decision-ledger 登记成本/回滚路径。

## 5. 铁律

- **编译过 ≠ 联调通**：字段/字节/时序需真实联调或独立证据验证。
- **不能拿目标端 mock 响应当源行为真值**：源真值来自已授权真实证据或静态分析，且明确标注。
- **未连通服务不宣告等价**：记录 `unverified`，给出可复现输入与下一步依赖。

## 6. 工具（本 skill 自有脚本）

| 脚本 | 用途 |
|---|---|
| `scripts/extract_startup_requests.py` | 冷启动日志 → 有效请求提炼 |
| `scripts/http-capture-proxy.js` | 明文 HTTP 抓包代理（零依赖，抓全 headers+body，对账签名头/请求时序） |
| `scripts/verify-sign.js` | 签名算法离线验证脚手架（真实抓包逐字节核对） |

脚本支持 `--help`；抓包/签名验证仅对已授权且实际配置的源流量执行。

## 7. 读取时机（references）

| 触发时机 | 必读 |
|---|---|
| 执行前；源 endpoint/鉴权/公参 `static` 段 | ../ios-api-inventory/SKILL.md（其 §2 三轮段归属） |
| 目标网络实现写法（拦截器/会话模型） | ../arkts-data-layer/SKILL.md + `references/network-service.md` |
| 受影响功能 AC / 契约 | ../a2h-spec/references/action-contracts.md（动作终态口径） |
| account/服务环境/公参字段来源 | `spec/baseline/api-inventory/common.md`（若有） |

## 8. 交接

- 交付：`api-inventory.json` 的 `runtime`/`reconciled` 段（或独立对账 DIFF 报告）+ 修复代码 + 真实请求脱敏摘要 + 退出结果。
- 未连通/无设备的项标 `unverified` 并附可复现输入与下一步依赖；交 a2h-verify 做设备侧联调收口。**宣告“网络等价”必须以独立契约证据通过为准，不是编译通过**。