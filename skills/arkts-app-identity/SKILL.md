---
name: arkts-app-identity
description: "iOS App 身份信息迁移到 HarmonyOS：App 名称（CFBundleDisplayName→app_name）、图标（前景/背景/自适应 layered_image.json）、版本号（MARKETING_VERSION/CURRENT_PROJECT_VERSION）、包名/厂商（app.json5 的 bundleName/vendor）、启动页与 URL scheme/Universal Link。当用户需要迁移这些身份字段、或发现 app.json5 中 bundleName/vendor/versionName 仍是模板默认值时触发，从 Info.plist / Xcode 构建变量 / Asset Catalog / Scene 启动配置提取原值。即使只说“app 名字不对”“图标没迁移”“包名还是默认的”也应触发。不处理全量资源迁移（用 ios-resources-convert）、运行时权限或深度链接的业务实现（用 arkts-system-capabilities）。"
metadata:
  type: domain
  domain: system
  tags:
  - migration
  - app-config
  - bundle-name
  - icon
  - ios
---

> **派发约定**：本 skill 是 **worker 角色**，由 `a2h-execute` Stage 0 按冻结任务书派发（`fork_turns:"none"`，`scope=dev-identity source_root=<$IOS_SRC> feature_base=spec/baseline/feature-base.md`）；也可在 verify 的 CHECK-2 或用户单独点名下由主会话直接执行。本 worker **不派发下级子代理**，只对**计划认领的身份文件**写目标。遵守 Join 协议（收口由派发方负责），本 skill 完成即返回映射报告与证据。
>
> **路径约定**：`$IOS_SRC` 读 `<target>/.migbot/config.json` 的 `ios` 字段；`<target>` = 鸿蒙目标工程根；`<runtime>` = 本包 runtime（`scripts/a2h_ios.py` 所在根）。身份资源先读 `../ios-resources-convert` 身份资源映射，App 显示名读 `spec/baseline/feature-base.md` 的 App 身份段（锁定值）。本 skill 无自有 `references/`/`templates/`/`scripts/` 目录，细则跨技能引用。

# arkts-app-identity — iOS 应用身份迁移

## 0. 定位与纪律

- **前置**：`<target>/.migbot/config.json` 存在且 `source_platform=ios`；源 target 的 Info.plist、Asset Catalog、Scene/启动配置、URL schemes、associated domains 与目标 bundle 决策可读。先读 `../ios-resources-convert/SKILL.md` 的 §7 身份输入，按该身份资源映射落地。
- **输入**：iOS 源身份（Info.plist / Asset Catalog AppIcon / Xcode 构建变量 / Scene 启动配置 / URL scheme / Universal Link）+ 目标 bundle 决策；可选 `spec/baseline/feature-base.md` 的 App 身份段、`scope`（`full` 默认 / `dev-identity`，见 §Step 3）。
- **输出**：`AppScope/app.json5`（bundleName/vendor/versionCode/versionName/icon/label）、`AppScope/resources/base/element/string.json`（app_name）、图标资源（foreground/background/layered_image.json/startIcon）、`entry/src/main/resources/base/element/string.json`（EntryAbility_label）、源身份→目标配置→资源引用表 + identity 报告与证据。
- **唯一交互点 = 输出映射报告后的目标 bundle 确认**（bundleName 可能需调整前缀）；其余禁交互追问。机械检查由 exit code 判定（build：0=编译通过并产出收据，非0=FAIL）。
- **第一条可见输出必须是一行身份迁移计划**（读锁定名 → 检查目标 AppScope/module.json5 → scope 分流 → 写身份资源 → 编译 → 设备冷启核对），然后才执行 §Step。
- **硬约束（黑体）**：**App 显示名在 spec 阶段锁定（CFBundleDisplayName 经 source-index/facts 进 feature-base.md App 身份段），本 skill 读该锁定值、不得从 iOS 源 Info.plist 反推**；**不复制 iOS provisioning/entitlements/签名账号作为目标配置**；**用户可见身份不应被模板值替代**；**静态配置正确 / HAP 可编译 / 安装身份正确是三种不同状态，缺设备不写 installed/verified**。

## 1. 定位

从 iOS 项目提取 App 身份信息（名称、图标、版本号、包名、启动页、链接），生成 HarmonyOS 对应配置。在迁移管线中的位置：`a2h-execute` Stage 0 的资源/身份 worker（`scope=dev-identity`），在进 Stage 1 之前落地 dev 安全字段；`scope=full` 也可在部署期/用户点名时独立运行。

```
iOS 项目（Info.plist + Asset Catalog + Scene）→ [本 skill] → app.json5 + string.json + 图标资源 + identity 报告
```

## 2. 输入

先读 `../ios-resources-convert/SKILL.md` 的身份资源映射，再自动定位：

- `Info.plist`：`CFBundleDisplayName`（缺省回退 `CFBundleName`）、`CFBundleIdentifier`、`CFBundleShortVersionString`、`CFBundleVersion`、`CFBundleURLTypes`、`UILaunchStoryboardName`/`UILaunchScreen`
- Xcode 构建变量（.xcodeproj / Package.swift）：`PRODUCT_BUNDLE_IDENTIFIER`、`MARKETING_VERSION`、`CURRENT_PROJECT_VERSION`、`PRODUCT_NAME`、`ASSETCATALOG_COMPILER_APPICON_NAME`
- `Assets.xcassets` 的 `AppIcon.appiconset`（图标变体，区分构建变量和展开值）
- Scene/启动配置（`Info.plist` 的 `UIApplicationSceneManifest` / LaunchScreen）、URL Types、associated domains（entitlements）
- 实测/展开后的**实际安装名称、不同语言名称、图标变体与启动表现**——区分构建变量与展开值，不能把占位 `${PRODUCT_NAME}` 当最终值

## 3. 输出

| 文件 | 内容 | 说明 |
|------|------|------|
| `AppScope/app.json5` | bundleName、vendor、versionCode、versionName、icon、label | 更新已有文件，不覆盖无关字段 |
| `AppScope/resources/base/element/string.json` | `app_name` 字段 | 写锁定值 |
| `AppScope/resources/base/media/{foreground,background}.png` | 前景/背景图标 | 从 Asset Catalog 提取 |
| `AppScope/resources/base/media/layered_image.json` | 自适应图标配置 | 生成或验证 |
| `entry/src/main/resources/base/media/startIcon.png` | 启动图标 | 复制前景或 AppIcon |
| `entry/src/main/resources/base/element/string.json` | `EntryAbility_label` | 更新为 app_name 一致值 |
| identity 报告（资源映射 + 控制台） | 源身份 → 目标配置 → 资源引用表 | 供用户确认 |

## 4. 核心映射规则

```
iOS                                →  HarmonyOS
────────────────────────────────────────────────────────
CFBundleDisplayName / CFBundleName →  app.json5 label ($string:app_name)
  规则: 读 feature-base.md App 身份段锁定值；无锁定值才回退读取，并标记待确认
CFBundleIdentifier / PRODUCT_BUNDLE_IDENTIFIER → bundleName      ⚠️ 仅 scope=full
  规则: 保持原值或用户自定义前缀
CFBundleShortVersionString / MARKETING_VERSION → versionName
  规则: 保持一致
CFBundleVersion / CURRENT_PROJECT_VERSION → versionCode
  规则: 保持整数编码一致
bundle 前缀第二段 / 开发者组织名       → vendor             ⚠️ 仅 scope=full
AppIcon.appiconset（最大尺寸变体）    → foreground.png / background.png
icns 层次 / AppIcon 前景背景          → layered_image.json
  格式: { "layered-image": { "background": "$media:background", "foreground": "$media:foreground" } }
UILaunchStoryboardName / UILaunchScreen / Scene → 启动页（entry loadContent + 首帧）
CFBundleURLTypes / CFBundleURLSchemes         → URL scheme / deep link（skills + uriFilter）
associated domains（entitlements）            → Universal Link（scheme   host）
```

## 5. 工作流程

### Step 1：读锁定值（名称/图标/版本），不从源反推

```
1. 读 spec/baseline/feature-base.md 的 App 身份段（若已存在）：
   → app_name 锁定值（CFBundleDisplayName 已在 spec 阶段锁定）
   → 直接用锁定值，跳过 iOS 源扫描；无锁定值才读 Info.plist 并标记“待确认”
2. 版本：读 Info.plist + Xcode 构建变量，优先 MARKETING_VERSION / CURRENT_PROJECT_VERSION
3. 图标：读 Asset Catalog AppIcon.appiconset，定位最大尺寸变体原图（区分构建变量与展开值）
```

> **App 显示名锁定协议**：显示名在 spec 阶段锁定进 feature-base.md 的 App 身份段（与 `../a2h-init/SKILL.md`“CFBundleDisplayName 等源内事实由 source-index/spec 阶段提取”一致）。本 skill 在 execute 阶段**读锁定值、不得从 iOS 源 Info.plist 反推**，否则会与 spec 已记录名称不一致，触发 a2h-verify CHECK-2 的 FAIL。

### Step 2：检查目标实际引用

```
4. 读 AppScope/app.json5、entry/src/main/module.json5、AppScope/resources/base/element/string.json、
   entry/src/main/resources/base/media/ 的实际引用：
   → 识别模板应用名称（"MyApplication"/"HelloWorld"）、默认图标、错误 entry 页面与未使用资源
   → 识别残留的模板 bundleName(com.example.*)/vendor(example)/versionName(1.0.0)
```

### Step 3：scope 分流（full / dev-identity）

```
5. AppScope/app.json5：仅更新以下字段（保留其他字段不变）
   - versionCode / versionName / icon("$media:layered_image") / label("$string:app_name")：两种 scope 都写
   - bundleName（来自 CFBundleIdentifier）      ⚠️ 仅 scope=full
   - vendor（组织名）                          ⚠️ 仅 scope=full

   > scope=dev-identity（a2h-execute Stage 0 调用）：跳过 bundleName / vendor——
   > 二者与签名证书 / AGC 应用上架强绑定，属部署期决策（迁移 ledger C-类目，对应 D-009）。
   > dev 阶段写入真实 bundleName 会与脚手架签名配置 / 后续 AGC 注册不一致，反致装机失败；
   > 保留脚手架占位值，待部署期由 scope=full（或人工）统一落地。dev 阶段只消除
   > app_name / versionName / 图标的脚手架默认值（这些无签名影响、却卡真机识别与 a2h-verify）。
```

### Step 4：实现名称/图标/启动资源及入口，校验权限与 deep link

```
6. 写 AppScope/resources/base/element/string.json 的 app_name 值（锁定值）
7. 复制/生成图标：foreground.png / background.png / layered_image.json / startIcon.png
8. 更新 entry/src/main/resources/base/element/string.json 的 EntryAbility_label 与 app_name 一致
9. 启动页/入口：按其 iOS Scene/LaunchScreen 表现落到 entry 启动加载与首帧；按目标 SDK 校验权限与
   URL/deep link 接收（uriFilter / skills）
10. 源 Universal Link、分享入口、推送注册有服务端依赖时，列清目标注册与验证条件（不冒充服务端已就绪）
```

### Step 5：编译与设备冷启核对

```
11. python <runtime>/scripts/a2h_ios.py build --project <target>
    → build 收据（status: build_passed / build_failed + <module>/build/*.hap 哈希）
12. 设备可用时（hdc 在线）安装冷启并核对：launcher 名称、图标、入口页是否与锁定值一致
    → 缺设备写 not_run，不得写 installed/verified
```

### Step 6：输出映射报告

```
13. 输出「源身份 → 目标配置 → 资源引用」对照表 + identity 报告与证据，提示用户确认 bundleName 映射
    （可能需要调整前缀；scope=dev-identity 时明确 bundleName/vendor 属部署期遗留）
```

## 6. 边界情况处理

| 场景 | 处理方式 |
|------|---------|
| 多 target/多 scheme，Info.plist/图标在子 target | 从 Xcode 工程追踪 target 配置，跨 target 定位实际的 Info.plist/Asset Catalog |
| 名称/版本在 Xcode 构建设置或 Package.swift 动态定义 | 读构建变量展开值，优先 MARKETING_VERSION/CURRENT_PROJECT_VERSION |
| 多语言显示名（CFBundleDisplayName 有 InfoPlist.strings） | 记录不同语言名称；目标侧 app_name 用锁定主值，语言变体交 i18n |
| 无 AppIcon 分层（旧工程单一 AppIcon） | 单一 AppIcon → foreground.png，生成纯色 background.png |
| feature-base.md App 身份段已存在 | 直接从 feature-base.md 读取映射值，跳过 iOS 源扫描 |
| 目标 bundle/vendor/version 未给定且影响外部注册 | 记录待决策，不擅自编造 |

## 7. 跨 Skill 协作

| 协作对象 | 关系 |
|------|------|
| `a2h-spec` | feature-base.md App 身份段提供锁定值（CFBundleDisplayName→app_name），本 skill 消费 |
| `ios-resources-convert` | 它处理全量资源，本 skill 只处理 app 级身份资源；其 §7 身份输入供本 skill 先读 |
| `arkts-project-scaffolder` | scaffolder 生成脚手架模板（含占位 bundleName/app_name），本 skill 填充真实 dev 值 |
| `a2h-execute`（Stage 0） | 以 `scope=dev-identity` 派发本 skill 消除脚手架默认值 |
| `a2h-verify`（CHECK-2） | 校验本 skill 产出（bundleName/vendor 仍模板=FAIL，app_name 与 Spec 记录不一致=FAIL） |

## 8. 读取时机（跨技能 references）

| 触发时机 | 必读文件 |
|---|---|
| 身份资源映射、identity 报告、缺口 | ../ios-resources-convert/SKILL.md（§7 身份输入） |
| 目标 AppScope/module.json5 引用与身份校验规则 | ../a2h-verify/references/static-and-identity.md（CHECK-2） |
| 源内事实（CFBundleDisplayName 等）锁定阶段 | ../a2h-init/SKILL.md（§Notes 源内事实由 source-index/spec 提取） |
| 派发参数与 dev-identity 语义 | ../a2h-execute/references/stage-0-resources.md（§3.0b-bis） |
| v2 机器门禁与状态写者 | ../ios-source-analysis/references/harness-v2.md |

## 9. 交接

- **闸门**：身份文件按 §Step 写入落定 + `build` 编译收据 exit 0（`scope=dev-identity` 时身份字段非编译必需，本 skill 返回非 0 由派发方记 WARN 不阻断 Stage 1，见 stage-0-resources）。
- **三态分离（必写进 identity 报告）**：`静态配置正确`（AppScope/module.json5 引用可解析且非模板值）/ `HAP 可编译`（build 收据 build_passed）/ `安装身份正确`（设备冷启核对名称/图标/入口，无设备 = not_run）——三者不可互相替代，缺设备不写 installed/verified。
- **移交产物**：身份文件变更 + identity 报告（源身份→目标配置→资源引用表 + 三态证据）。
- **下一步**：返回派发方（a2h-execute 继续 Stage 1，或 a2h-verify CHECK-2 复核）。

## 触发 Prompt 示例

```
迁移 app 图标
app 名字不对
配置应用信息
bundleName 还是默认的
图标没迁移
```

---

## 收尾：用量归派发方

本 skill 是被派发的 worker，用量**归派发方（a2h-execute）计账**，不单独上报阶段水位。独立触发（用户点名、a2h-verify CHECK-2 引导）时，若本轮启动了 `usage-start` 账本则执行：

```bash
python <runtime>/scripts/a2h_ios.py usage-finish --project <target> --run-id <本轮run-id>
```

写本地 usage 账本、尽力而为。token 用量由宿主生命周期采集，本步不采集。**忽略其退出码，绝不阻断流水线。**