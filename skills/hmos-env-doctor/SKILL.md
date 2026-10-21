---
name: hmos-env-doctor
description: "鸿蒙目标开发环境检查与修复：检查原生 iOS 迁移的鸿蒙目标环境——DevEco、SDK、Node、JDK、ohpm、hvigor、hdc 和签名，按实际缺项修复；源理解不依赖本机 Xcode。当用户说“编译失败 / 环境有问题 / hvigorw 找不到 / 签名错误 / 真机运行白屏 / 检查一下环境 / 为什么编译不过 / 跑不起来”时触发；也适用于迁移前环境预检与项目初始化后健康检查。不要用于：iOS 源码问题定位（走 ios-source-analysis）、目标构建报错的具体修复（走 hmos-fix-build-errors）、iOS 侧 Xcode/设备能力协商（走 a2h-init §7 / ios-source-analysis）。"
metadata:
  type: tool
  domain: engineering
  tags:
  - ios
  - tooling
  - environment
  - deveco
  - hvigor
  - signing
---

> **职责边界（本 skill 的两个层面，必须分清）**：
>
> 1. **doctor CLI 输出**：`python <runtime>/scripts/a2h_ios.py doctor --project <target>` 是本包的单点**只读**机械诊断——不运行任何外部程序、**不递归扫盘、不运行 Swift**、不写文件、不联网，只做存在性/配置/宿主能力探测，并输出 `host_profile`、`sections`、`overall`。它只负责“事实快照”，不做版本相容、不做签名内容校验、不枚举设备。
> 2. **skill 规程**：本 skill 把 doctor CLI 的事实 + validate 的机器校验 + 需要真正执行的核对（版本相容、ohpm 锁、签名路径、hdc 实际返回、真实 build 日志）组织成“诊断 → 修复 → 复检”流程。
>
> CLI 报告 FAIL 的项才需动手修复；PASS 的项不要重复人工复查。本 skill **不派发 subagent**（主会话执行）。路径约定：`<target>` = 鸿蒙目标工程根；`<runtime>` = 本包 runtime（`scripts/a2h_ios.py` 所在根）；产物落 `<target>/spec/`，禁落会话临时目录。

# hmos-env-doctor — 鸿蒙目标开发环境检查

## 0. 定位与纪律

- **前置/输入**：读取 `.migbot/config.json` 与当前目标工程；**只对任务相关环境做诊断**，先查显式配置与已知 DevEco 位置，**不递归扫描所有磁盘、不覆盖用户系统环境**。
- **输出**：诊断报告（PASS/FAIL/WARN/unavailable + 根因 + 修复动作）+ 复检结果。
- **第一条可见输出必须是一行诊断计划**（doctor 快照 → validate → 配置/工具链/签名/设备逐项 → 修复 → 复检），然后才执行 §1。
- 无人值守处置阶梯（门禁 FAIL 一律套用）：FAIL → 按命令 `retry_hint`/错误原文派修复并重跑，最多 2 轮；2 轮仍不过或确定模型修不了 → 记欠账放行；要拍板的模型自决并留痕；任何分支不得停机呈报人工。

## 1. 机械只读诊断（doctor CLI，先跑）

```text
python <runtime>/scripts/a2h_ios.py doctor --project <target> [--config <cfg>] [--text]
```

- 只读契约：`tools_executed=false`、`network_accessed=false`、`mutations=false`、`read_only_verified=true`；**只 stat 源根、不递归扫盘、不运行 Swift / 不运行任何外部程序、不重新 ran 旧 PASS**。
- 读输出三块：`overall`（blocked / config_error / needs_project / partial / source_analysis_ready）、`host_profile`（`source.mode`=native/static/static_fallback；`capabilities.ios.xcode_project_membership`、`ios.swift_compiler_context`、`harmony.build` 等）、`sections.{source_analysis,harmonyos_build,device_verification}`。
- **只做事实，不做判定**：存在性 ≠ 版本相容 / 可执行 / 已验证环境；`signing_profile`、`device_id` 默认 `not_verified`/`unknown`（真实内容校验接 §5/§7 的 skill 规程）。
- 显式 `--config` 坏/缺失**不回退**默认配置、不给 ready；`--node/--hvigor/--ohpm/--java/--sdk` 是显式覆盖入口，不是扫盘手段。

## 2. 机器校验（validate）

```text
python <runtime>/scripts/a2h_ios.py validate --project <target>
```

- 校验 `source_platform=ios`、真实 `ios`/`harmonyos` 路径且**互不包含**（道理同 §3），以及目标 app/module/build-profile 等机器可判定项。
- exit 0 = 通过；非 0 = 列失败项，按 §0 阶梯修 2 轮，不造 PASS。

## 3. 配置核对（skill 规程补充）

- `source_platform=ios`；`ios`、`harmonyos` 为真实存在的目录且互相分离；`harmonyos` = 实际目标根（与 `--project` 归一一致）。
- 目标侧：`app.json5`、`module.json5`、`build-profile.json5` 存在且身份/入口不残缺（bundleName 非 `com.example.*`、入口 `main_pages.json` 首项指向实际启动页、`EntryAbility` 的 `loadContent` 与其一致）。
- **源理解不依赖本机 Xcode**：源静态分析的启动条件只有 Python + 真实 iOS 源（见 doctor 的 `overall=source_analysis_ready`），Node/构建链/设备**不是**源分析前置——只有目标 build 才需要它们。

## 4. 工具链核对

- 核对 DevEco 自带 Node、JDK、ohpm、hvigor、SDK **是否存在，且版本与目标工程相容**（hvigor 版本、`compatibleSdkVersion`、Node 主版本、JDK 17+）。
- Java：检查 JDK 的 `java` **可执行文件**；构建进程需要时**局部**设置 `JAVA_HOME/PATH`（仅当前会话、脚本级），这是目标打包依赖，**不代表 iOS 用该语言开发**、不改用户全局 shell 配置。
- 环境变量只作用于当前构建子进程；不落盘、不写用户 profile。

DevEco 自带工具相对路径（按 DevEco 安装根定位，不扫盘）：

| 工具 | 相对路径 | 用途 |
|---|---|---|
| hvigorw | `tools/hvigor/bin/hvigorw[.bat]` | 项目编译 |
| ohpm | `tools/ohpm/bin/ohpm` | 包管理 |
| java | `jbr/bin/java` | Java 运行时（打包需要） |
| node | `tools/node/bin/node` | Node 运行时 |
| SDK | `sdk/default/openharmony/` | HarmonyOS SDK |

版本期望（不匹配 → WARN/FAIL，非“有就行”）：

| 工具 | 期望 |
|---|---|
| hvigorw | 6.x 与 `build-profile.json5` 的 `compatibleSdkVersion` 匹配 |
| java | JDK 17+ |
| node | v18+ |
| ohpm | 有输出且能解析 `oh-package.json5` |

缺失/版本不符时**只给显式候选或让用户设 `DEVECO_HOME`/`DEVECO_SDK_HOME`**，不 `find /`、不 `dir /s` 全盘搜（那正是“20 分钟无结果”的来源）。

## 5. 签名与依赖核对

- 检查 `ohpm install` 锁定依赖、`hvigorfile.*`、`local.properties`（`hwsdk.dir` 指向真实 SDK）、`build-profile.json5` 的 `signingConfigs` 签名路径存在性。
- 签名路径指向其他用户目录/其他机器 → 判定“签名配置来自其他环境”；修复按优先级：自动签名重配 → 移除 `signingConfig` 引用（生成 unsigned 调试）→ 手动重建签名文件。
- **不读私钥、不读证书内容、不记录明文凭据**；签名内容是否有效由 build 真实结果判定。

## 6. build 与真实日志

需要 build 时：`python <runtime>/scripts/a2h_ios.py build --project <target>`；报错调用 `a2h-build` / `hmos-fix-build-errors` 诊断，**保存真实 stderr/stdout 日志与退出码**，不凭猜测改文件。修复后**重跑失败检查**。

## 7. 目标设备（hdc）

- 用 **hdc 的实际返回**区分：未装工具 / 无设备 / 多设备 / 连接失败；不得把“有工具”当“有设备”。
- 设备选择沿用用户已有输入（不替用户换设备）；无工具/无签名/无设备如实标 `unavailable`，**不造 PASS**。

### 7.1 目标运行期问题（编译过但运行异常时查，HarmonyOS 目标侧）

- **白屏/内容为空**：`aboutToAppear` 里 async 失败导致状态变量保持初始空值（关键展示数据同步初始化，async 作增强）；`ForEach` 未提供 key generator 致 class 实例 key 冲突；`INTERNET` 权限缺失致请求静默失败。
- **闪退**：crypto API 在部分设备不可用（`cryptoFramework` 必须 try-catch + fallback）；页面未注册进 `main_pages.json`。
- **网络请求失败**：缺 `ohos.permission.INTERNET`；HTTP 明文传输被安全策略阻止；API 域名不可达（DNS/代理）。
- 这些都是**目标工程**问题，与 iOS 源无关（iOS 侧只负责提供源契约，走 arkts-network-troubleshoot / ios-api-inventory）。

## 8. iOS 独立能力报告（与目标环境并列，不混写）

- iOS 的 **Xcode / 设备 / 官方 skills / MCP 独立报告**：单列 `available / configured / executed` 三态（与 a2h-init §7 口径一致）；**不以本机没有 Mac 阻断静态源分析或目标构建**。
- 云构建日志不能代替 iPhone 安装/功能验证（iOS 迁移固定红线）；`doctor` 只反映 `host_profile` 能力协商，运行/设备能力仍待真实证据。

## 9. 修复边界（硬约束）

- **环境修复不删除用户代码或凭据，不改用户全局安全策略来获得一次构建成功**（不关证书校验、不降 ATS、不关权限）。
- 不递归扫盘、不覆盖用户系统环境变量；局部 `JAVA_HOME/PATH` 只作用于当前构建子进程。
- 没有工具/签名/设备如实标 unavailable 并给出下一步，绝不把“没测”写成 PASS。

自动修复能力（可安全自动修才直接改；其余问/不动）：

| 问题 | 自动修复 | 操作 |
|---|---|---|
| 局部 PATH/JAVA_HOME 未设 | YES | 输出当前会话的 export/`$env:` 命令，不写用户 profile |
| 缺 `INTERNET` 权限 | YES | 追加到 `module.json5`（明示改动） |
| 签名指向其他机器 | YES | 移除 `signingConfig` 引用（明示改动） |
| 入口 `main_pages.json` 错误 | YES | 更新 `src` 数组 |
| bundleName 为模板默认值 | ASK | 提示用户输入正确包名 |
| DevEco/SDK 缺失 | NO | 提示安装位置；不扫盘、不下载 |
| 无真机/签名文件缺失 | NO | 标 unavailable 并给下一步 |

## 10. 常见根因速查

错误 Node/JDK 版本、SDK 目录（`hwsdk.dir`）错、依赖未安装（缺 `ohpm install`）、签名路径指向他机、设备未授权、目标版本与 SDK 不匹配——逐项回落到 §4/§5/§7 的具体检查，修复后重跑对应检查。

## 11. 读取时机（references）

| 触发时机 | 必读 |
|---|---|
| build 报错后定位/修复 | ../hmos-fix-build-errors/SKILL.md（含 `references/known-patterns.md` 等） |
| 目标如何编译/打包 | ../a2h-build/SKILL.md |
| iOS 能力协商与 host_profile 口径 | ../a2h-init/SKILL.md §7 + ../ios-source-analysis/SKILL.md |
| 权限/签名相关的隐私边界 | ../a2h-privacy/SKILL.md（存在时） |

## 12. 交接

- 交付：诊断报告（doctor 快照 + validate + 逐项核对结论）+ 修复动作 + 复检结果 + 未见工具/签名/设备的 unavailable 清单与下一步。
- 环境就绪后交 a2h-build 做编译验证，或交回调用方（a2h-run / 目标 build 流程）继续；**不把“修到能跑一次”当成“环境健康”**，复检通过才算收口。