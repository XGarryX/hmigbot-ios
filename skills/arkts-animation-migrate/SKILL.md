---
name: arkts-animation-migrate
description: "iOS→HarmonyOS 迁移动画还原：读取 SwiftUI/UIKit/Core Animation/Lottie/第三方动画的时间、状态与生命周期语义，复用 ArkTS 动画能力还原目标效果与取消/重入行为，输出源状态→目标状态映射、参数表、未等价项和对应 AC。当用户说“原版 iOS 有动画现在鸿蒙是静态图 / 这个 Lottie 用不了吗 / 选中态没有动画 / 卡片切换没有过渡 / 共享元素 / 转场没生效 / 序列帧 / SVGA 礼物动画 / 这个动画在 ArkTS 怎么写”，或 a2h-execute 还原 iOS 页面时在 Swift/Storyboard/XIB 里发现 withAnimation/matchedGeometryEffect/UIView.animate/CAAnimation/Lottie 调用时使用，即使用户没明说“做动画”也要触发。不要用于：纯 UI 静态样式对齐（用 arkts-text-truncation/arkts-ui-alignment 等专项）、纯 router 跳转无视觉过渡（不算动画）、Web/H5 内嵌动画（非 ArkTS 域）；纯 ArkTS 动画 API 写法细节与可运行 demo 走 arkts-animation-builder。"
metadata:
  type: domain
  domain: ui
  tags:
  - ios
  - ui
  - animation
  - migration
  - lottie
  - transition
  - shared-element
---

> **定位与分工**：本 skill 专注「iOS 动画源识别 + 语义映射 + 资源迁移 + 平台特有 API 接入 + 迁移陷阱」。
> **ArkTS 动画 API 写法细节统一在 [arkts-animation-builder](../arkts-animation-builder/SKILL.md)**——完整可运行的 demo 组件走 builder，避免双源不同步。
>
> 本 skill **不派发 subagent**，主会话（或作为 a2h-execute 的子步骤）执行。路径约定：`$IOS_SRC` 从 `<target>/.migbot/config.json` 的 `ios` 字段读取；`<runtime>` = 本包 runtime（`scripts/a2h_ios.py` 所在根）；产物落 `<target>/spec/`，禁落会话临时目录。

# arkts-animation-migrate — 从 iOS 动画源还原目标动效

## 0. 定位与纪律

- **前置**：`<target>/.migbot/config.json` 存在且 `source_platform=ios`；先读 `arkts-animation-builder` 的目标 API/动画规程，再读受影响页面的 facts。
- **输入**：动画源代码、页面 facts、资源与实际运行证据。
- **输出**：源码状态→目标状态映射、参数表、未等价项和对应 AC。
- **不能靠文件格式或相同 duration 判等价**；编译通过不能当动画对齐证据，视觉/交互验证由真实设备场景完成。
- **第一条可见输出必须是一行还原计划**（识别源 → 选型 → 参数映射 → 资源搬迁 → 验证），然后才执行 §1。
- 无人值守处置阶梯（门禁 FAIL 一律套用）：FAIL → 按命令 `retry_hint`/错误原文派修复并重跑，**最多 2 轮**；2 轮仍不过或确定模型修不了 → **记欠账放行**（账记全：修过几轮、每轮失败原因、判“修不了”的依据）；要拍板的模型自决并留痕；任何分支不得停机呈报人工。

## 1. 识别 iOS 动画源（决策树）

迁移目标页面存在视觉变化时，按真实调用定位是那一类动画：

```
目标页面/组件存在视觉变化
  ├─ .json 动画 + 配套图集（bodymovin/图集特征）?  →  ① Lottie（@ohos/lottie + LottieView 复用）
  ├─ .svga 文件?                                  →  ⑥ SVGA（无官方等价：首选转 Lottie，兜底拆帧）
  ├─ CABasicAnimation/CAKeyframeAnimation/隐式动画? →  ② implicit/explicit 属性动画（animateTo / .animation()）
  ├─ UIView.animate / UIViewPropertyAnimator?       →  ③ 显式属性动画（animateTo，含曲线/弹簧/阻尼）
  ├─ withAnimation + if/else + transition 修饰符?   →  ④ 转场（.transition() + TransitionEffect）
  ├─ matchedGeometryEffect / custom transition?     →  ⑦ 共享元素转场（geometryTransition / sharedTransition）
  ├─ CASpringAnimation / spring(response:damping:)?  →  ⑧ 物理/弹簧动画（curves.springMotion）
  ├─ Image 序列帧 / sprite sheet / APNG 逐帧?       →  ⑤ 帧动画（ImageAnimator）
  └─ UIViewController 转场 / navigationTransition   →  ⑨ 页面进出转场（pageTransition / customNavContentTransition）
```

判定依据是**真实调用点**，不是文件名或“看起来像动画”。SwiftUI 的 `withAnimation`/`.animation(_:value:)`/`.transition`/`.matchedGeometryEffect`，UIKit 的 `UIView.animate`/`UIViewPropertyAnimator`/`addAnimation`，Core Animation 的 `CABasicAnimation`/`CAKeyframeAnimation`/`CASpringAnimation`/`CATransition`，以及 Lottie（`LottieAnimationView`/`LottieView`）都要沿实现追到实际动画，不能停在属性名。

## 2. 选型速查表（iOS 源 → ArkTS 等价，模板在 builder）

| # | iOS 源框架 | ArkTS 等价 | 详细模板（builder references） |
|---|---|---|---|
| ① | Lottie | `@ohos/lottie` + 自建 `LottieView` 组件 | [../arkts-animation-builder/SKILL.md](../arkts-animation-builder/SKILL.md) |
| ② | 隐式/显式属性动画（`.animation` / `CABasicAnimation`） | `.animation()` + `animateTo()` + `keyframeAnimateTo` | [v2-explicit-animation.md](../arkts-animation-builder/references/v2-explicit-animation.md) |
| ③ | `UIView.animate` / `UIViewPropertyAnimator` | `animateTo`（时长/曲线/延迟/完成回调） | [v2-explicit-animation.md](../arkts-animation-builder/references/v2-explicit-animation.md) |
| ④ | `withAnimation` + `transition` 修饰符 | `.transition(TransitionEffect)` + `animateTo` | [v2-transition-patterns.md](../arkts-animation-builder/references/v2-transition-patterns.md) |
| ⑤ | 序列帧/sprite sheet/逐帧 | `ImageAnimator` | [../arkts-animation-builder/SKILL.md](../arkts-animation-builder/SKILL.md) |
| ⑥ | SVGA | **无官方等价**——首选转 Lottie，兜底拆帧 | [../arkts-animation-builder/SKILL.md](../arkts-animation-builder/SKILL.md) |
| ⑦ | `matchedGeometryEffect` / 自定义 VC 转场 | `geometryTransition`（同页）/ `sharedTransition` / `customNavContentTransition` | [v2-extra-animation.md](../arkts-animation-builder/references/v2-extra-animation.md) |
| ⑧ | `CASpringAnimation` / `spring(...)` | `curves.springMotion` / `curves.springCurve` | [v2-explicit-animation.md](../arkts-animation-builder/references/v2-explicit-animation.md) |
| ⑨ | VC 进出转场 / navigation transition | `pageTransition()` / `customNavContentTransition()` | [v2-transition-patterns.md](../arkts-animation-builder/references/v2-transition-patterns.md) |

**索引规则**：定位到类型后直接打开对应 builder reference——里面有完整代码模板、对照表与常见坑，SKILL.md 不重复这些细节。

## 3. 迁移执行（按序）

1. **识别源框架**（§1 决策树）——读 Swift/Storyboard/XIB/资源目录，定位是哪一类。
2. **提取实际动画语义**：记录驱动状态、起止值、曲线/弹簧参数、延迟/重复、叠加（多层并发）、交互进度和 completion；把视图身份与结构插入/移除、可中断/反向、取消和资源销毁一并纳入转换决策。
3. **打开对应 reference**（§2 速查表）——按 reference 里的模板与对照表执行；非法混用 V1/V2 装饰器的写法不要照抄。
4. **逐参数验证**：使用目标 `animateTo`/`transition`/属性动画或明确帧序列，**逐参数验证单位和效果**；共享元素、path/mask、自定义 shader 无直接支持时记录替代方案与视觉影响。
5. **三方动画资源**：验证目标库版本/支持特性，保留版权与素材来源，不保证所有 JSON 可直接播放。
6. **资源搬迁**：JSON 模板 + 图集 + 序列帧 PNG 完整搬到 `entry/src/main/resources/rawfile/`（或 `resources/base/media/`），缺一张 `img_X.png` 就是“看不到 + 静默 fallback”。HarmonyOS 文件系统大小写敏感，复制后立刻核对大小写。
7. **编译 + 跑设备**——动画只看代码不算数，必须真机/模拟器看一眼。

## 4. 验证回环

修改后必须走完：

1. **编译过**（`python <runtime>/scripts/a2h_ios.py build --project <target>`，或 hvigorw assembleHap；失败日志交 a2h-build/hmos-fix-build-errors 诊断）。
2. **装到目标设备**（hdc install -r）。
3. **进入对应页面眼看**：Lottie 在播（非静止帧）+ 图集完整（缺图空白方框）+ 位置不偏不歪；属性动画状态切换有过渡、时长接近源（误差可接受）；转场进/出都有、共享元素位置对齐。
4. **清理与降级场景加验证点**：页面离开时清理 timer/animator/监听；重复进入、减少动态效果（Reduce Motion）和低帧率场景逐项列验证点。
5. **抓 hilog 查错误**（`hdc shell hilog -x | grep -E "lottie|animation|transition"`）。

## 5. 与其他 skill 的关系

- **a2h-execute**：还原 iOS 页面时遇到动画属性/资源 → 触发本 skill 做动画那部分。
- **arkts-animation-builder**：本 skill 的 ArkTS API 写法与 demo 宿主（唯一写法源，避免双源不同步）。
- **ios-ui-analyzer / ios-project-inspector**：动画所在的页面/入口 facts 来源；动画看不到时**先排除是不是数据没来**（无数据 → 列表空 → 没渲染 → 看上去没动画），那走源分析而不是动画 skill。
- **arkts-multi-device / arkts-large-font**：折叠屏展开收起触发 reuse 时 Lottie 容易 destroy 异常、字体层不受 fontSizeScale 影响——独立处理，不混入本 skill。

## 6. 边界

**不处理**：纯静态样式（颜色/字号/圆角对不齐）→ 走 arkts-text-truncation / arkts-ui-alignment 等专项；纯 router 跳转无视觉过渡需求；WebView/H5 内嵌动画（Web 域）；Native 渲染层自绘动画（高级场景独立专项）。
**处理**：任何“原版有动画现在没有 / 动画歪 / 动画卡”的视觉差异修复；Lottie/SVGA/帧动画/属性动画/转场/共享元素/物理动画/页面进出的从零接入与还原。

## 7. 读取时机（references）

| 触发时机 | 必读文件 |
|---|---|
| 执行任何步骤前；ArkTS 动画 API 写法、编译硬规矩（curves/AppStorageV2 import、keyframeAnimateTo 属 UIContext、字段名避撞内置 attribute、onDragEnd） | ../arkts-animation-builder/SKILL.md |
| 显式/属性/弹簧动画写法 | ../arkts-animation-builder/references/v2-explicit-animation.md |
| 属性动画 / 页面进出转场写法 | ../arkts-animation-builder/references/v2-transition-patterns.md |
| 手势跟随动画 | ../arkts-animation-builder/references/v2-gesture-animation.md |
| 共享元素几何转场 / 循环动画 / @ObservedV2 状态封装 | ../arkts-animation-builder/references/v2-extra-animation.md |
| 媒体类动画（播放器/进度） | ../arkts-animation-builder/references/v2-media-app-animations.md |

## 8. 交接

- 交付产物：源动画清单 + 源状态→目标状态映射表 + 参数表 + 未等价项（共享元素/path/shader 等的替代方案与视觉影响）+ 对应 AC + 编译/设备验证记录。
- 动画还原完成后交回调用方（a2h-execute 对应页面 slice）；未等价的视觉差异项记入 decision-ledger，供 a2h-verify 做独立视觉/交互验证。**没有设备验证的动画项不得宣告“动画对齐”**。