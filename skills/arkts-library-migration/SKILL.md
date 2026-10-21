---
name: arkts-library-migration
description: "三方库/依赖替代方案查找与决策：根据 iOS 源依赖（Swift Package / CocoaPods / .xcframework / 系统框架 / C/C++ 引擎）的真实调用契约选择鸿蒙替代库、服务或 NAPI 适配，保留版本、许可、初始化、类型/句柄与生命周期约束，产出依赖替代矩阵及每条证据。当用户说“这个库在鸿蒙上有吗 / 用什么替代 iOS 的 XX / ohpm 搜索 / 依赖替换 / SPM/Podfile 迁移 / 闭源 SDK 怎么迁”时触发。不要用于：完整业务功能的编排（下拉刷新列表、列表详情页优先 arkts-pattern-library）、源依赖与调用点的盘点（用 ios-api-inventory/ios-project-inspector）、目标代码具体实现（按领域走 arkts-data-layer/arkts-system-capabilities 等）。"
metadata:
  type: domain
  domain: migration
  tags:
  - ios
  - migration
  - third-party-library
  - ohpm
  - napi
  - spm
  - cocoapods
---

> **定位**：本 skill 只做「替代方案查找 + 决策 + 迁移类型与风险定级」，不写业务实现。源侧依赖清单与调用点来自 `ios-project-inspector` 与 `ios-api-inventory`，本 skill 不重复抽取。目标库选型定级后，实现交对应领域 skill。
>
> 本 skill **不派发 subagent**，主会话（或 a2h-execute 子步骤）执行。路径约定：`$IOS_SRC` 从 `<target>/.migbot/config.json` 的 `ios` 字段读取；产物落 `<target>/spec/`，禁落会话临时目录。

# arkts-library-migration — iOS 依赖到鸿蒙依赖

## 0. 定位与纪律

- **前置**：先读 `ios-project-inspector` 和 `ios-api-inventory` 的依赖清单与调用点；不重复抽依赖。
- **输入**：iOS 源真实调用契约（用到的 API 子集、数据模型、初始化、回调线程、错误与释放行为）。
- **输出**：依赖替代矩阵（每项：iOS 依赖 → ArkTS 替代 → 层级 → 风险 → 迁移类型 → 证据）。
- **确定依赖性质**：是源码、闭源 framework、C/C++ 引擎、系统服务还是远程协议——性质不同走不同路径。
- **只下载/导入依赖不算对应业务功能已完成**；源协议语义与目标依赖版本分别固定，避免后续更新悄悄改变基线。
- **第一条可见输出必须是一行决策计划**（清单 → 逐项定级 → 契约核对 → 实现与测试），然后才执行 §1。
- 无人值守处置阶梯（门禁 FAIL 一律套用）：FAIL → 按命令 `retry_hint`/错误原文派修复并重跑，最多 2 轮；2 轮仍不过或确定模型修不了 → 记欠账放行；要拍板的模型自决并留痕；任何分支不得停机呈报人工。

## 1. 五层查找策略（按成本从低到高）

```
┌ L1：OpenHarmony 三方库（ohpm）— 成本最低，直接 ohpm install
│    搜索渠道：ohpm.openharmony.cn / gitee.com/openharmony-tpc / gitee.com/HarmonyOS-tpc
├ L2：HarmonyOS 原生 API（@kit.*）— 零依赖，需自写业务代码
├ L3：NAPI 桥接 C/C++ 开源库 — 功能完整，集成成本高（FFmpeg/OpenCV/libjpeg-turbo 等）
├ L4：WebView + JS 库 — 开发快、性能有损（Three.js/Fabric.js 等）
└ L5：自研实现或功能降级 / 标记 Skip — 最后手段
```

## 2. 决策树

```
iOS 三方库 X（先读 ios-api-inventory 的真实调用点）
  ├─ ohpm / openharmony-tpc 有直接替代？ → 是 → L1：ohpm install（最优）
  ├─ HarmonyOS 原生 @kit.* 能覆盖？     → 是 → L2：原生 API 实现
  ├─ 该库有 C/C++ 开源核心？             → 是 → L3：NAPI 桥接（交叉编译 .so）
  ├─ JS/Web 生态有等价库？               → 是 → L4：ArkWeb + JS 库
  └─ 无替代                            → L5：自研简化版 / 功能降级 / Skip
```

**核心约束**：先查厂商官方目标支持与版本，再查可信开源实现；逐项记录来源、许可证、更新时间。**同名功能但行为变化进入 decision-ledger**；未知源码/闭源行为以公开契约或测试补证，不靠“名字像”断言等价。

## 3. 每层代价分析

| Level | 开发代价 | 维护代价 | 运行性能 | 适用场景 |
|---|---|---|---|---|
| L1 ohpm | 低 | 低（社区维护） | 高 | 有成熟鸿蒙包的功能 |
| L2 原生 API | 中 | 低（系统级） | 高 | 系统已提供基础能力 |
| L3 NAPI | 高（C/C++ + CMake） | 中（跟进上游） | 高 | 音视频/图像算法等计算密集 |
| L4 WebView | 中 | 中 | 中（JS 桥接开销） | 全景/VR/复杂编辑 UI |
| L5 自研 | 高 | 高 | 视实现而定 | 无任何替代方案 |

## 4. 华为官方四类法

| 类型 | 描述 | 处理方式 |
|---|---|---|
| A 类 | ohpm 已有鸿蒙版 | 直接 `ohpm install` |
| B 类 | 无鸿蒙版但有开源替代 | L2 原生 API 或 L3 NAPI |
| C 类 | 闭源 SDK，厂商已/将适配 | 联系厂商获取鸿蒙版 |
| D 类 | 无替代方案 | L5 自研或功能降级 / Skip |

## 5. C/C++ 与 .xcframework 的硬约束

- C/C++ 源复用须核对：平台调用、架构、编译链、ABI、内存所有权与线程边界。
- **预编译 `.xcframework` 不能直接变为目标库**——它是 Apple 平台打包格式，必须拿到源码或厂商鸿蒙产物重编，禁止改扩展名当目标库用（与 ios-api-inventory §5 的 NAPI 边界一致）。
- NAPI 方案必须定义类型、缓冲区、所有权与线程边界；无法读到的内部行为记 `opaque` 并指定所需公开契约或运行证据。

## 6. 技术栈替换表与风险定级

逐项填写（格式示例）：

```markdown
| iOS 依赖 | ArkTS 替代 | Level | 风险 | 迁移类型 | 证据/备注 |
|---------|-----------|-------|------|---------|----------|
| Alamofire 5.x | @ohos/axios 或 @kit.NetworkKit http | L2 | 🟡 | Manual | 状态机/拦截器适配 |
| SDWebImage | @ohos/imageknife | L1 | 🟢 | Auto | ohpm install |
| Realm/GRDB | relationalStore @kit.ArkData | L2 | 🟡 | Semi-Auto | 手写 SQL/DAO |
| 某闭源 SDK | 联系厂商 / ArkWeb+JS-Bridge 过渡 | C | 🔴 | Manual | 厂商适配状态记录 |
```

风险档：🟢 低（L1-L2 有成熟替代）、🟡 中（L2-L3 API 差异大）、🔴 高（L3-L5 需重写）。

## 7. 常见错误 vs 正确做法

- **错误 1：直接搜 npm 包**——npm 包在 ArkTS 中不可用；正确用 ohpm 包或原生 API。
- **错误 2：假设 iOS 库有同名鸿蒙版**——先查对照/决策树；先查厂商官方支持与版本再查公开实现。
- **错误 3：闭源 SDK 直接标记不可迁移**——先查厂商适配状态，再考虑 ArkWeb + JS-Bridge 过渡。
- **错误 4：把“下载/导入成功”当迁移完成**——只有接口实现 + 编译 + 契约测试（+ 必要设备测试）通过才算该依赖迁移完成。

## 8. 生成检查清单

- [ ] 每个 iOS 依赖都有对应替代方案或标记 Skip
- [ ] 每个依赖标注 Level（L1-L5）/ 迁移类型 / 风险等级（🟢/🟡/🔴）
- [ ] 高风险项（🔴）有缓解策略
- [ ] 闭源 SDK 有厂商联系记录或替代方案
- [ ] C/C++/`.xcframework` 项有 NAPI 类型/所有权/线程边界说明，未“改扩展名冒充”
- [ ] ohpm 包安装命令正确；没有使用 npm 包

## 9. 跨 skill 协作（读取时机）

| 触发时机 | 必读 |
|---|---|
| 源依赖清单与调用点 | ../ios-project-inspector/SKILL.md + ../ios-api-inventory/SKILL.md |
| 目标网络/数据层具体实现 | ../arkts-data-layer/SKILL.md（`references/network-service.md` 等） |
| 系统能力 / SDK 版本证据 | ../arkts-system-capabilities/SKILL.md + ../hmos-sdk-docs/SKILL.md |
| 完整业务功能编排（列表详情等） | ../arkts-pattern-library/SKILL.md |
| API 版本兼容性 / 不确定知识点 | ../arkts-knowledge-verifier/SKILL.md |
| 完整 skill 路由矩阵 | ../arkts-knowledge-verifier/references/skill-routing-guide.md |

## 10. 交接

- 交付：`spec/ref/` 依赖替代矩阵（每项带证据：来源、许可证、更新时间、实际调用点）+ 决策账本中“同名功能行为变化”的 D 条目。
- 每个替代方案按计划在 feature-base 或所属 slice 实现接口、编译、契约测试和必要设备测试；**未实现接口/未跑契约测试的项仍是“待迁移”，不宣告完成**。源协议语义与目标依赖版本固定后，交 a2h-plan/a2h-execute 消费。