---
name: arkts-icon-sizing
description: "iOS 图片/符号尺寸校验与修复：核对 iOS 图片/符号的真实布局、Asset Catalog scale 与目标 ArkUI 尺寸；只按源码和资源证据修复，禁止用统一密度替所有图片自动猜尺寸。当用户反馈鸿蒙页面上图标/图片“太大/太小/被拉伸/被压扁/比例异常/图标变形”，或要求“统一检查/修复各页图标比例”，或刚做完 iOS→ArkUI UI 迁移（SwiftUI Image / UIKit UIImageView 被转成 ArkUI Image）时触发。不要用于：文本截断（arkts-text-truncation）、大字体布局溢出（arkts-large-font）、深色模式图标变色（arkts-dark-mode）、生成全新 UI（arkts-component-builder）。"
metadata:
  type: domain
  domain: ui
  tags:
  - ios
  - ui
  - migration
  - icon
  - image
  - sizing
---

> **定位与联动**：本 skill 只读检测 + 定向修复「丢了尺寸的 ArkUI `Image`」，不自动改代码、不统一推测密度。原生预检由 `arkts-structural-closure` 的 pipeline 模式在跑原结构引擎前调用本入口：有欠约束 Image 时返回 `NATIVE_INPUT_REQUIRED`（exit 3），先按本 skill 从真实 iOS 布局/asset scale 修复再重跑——防止旧默认密度自愈误改 iOS 页面。
>
> 本 skill **不派发 subagent**，主会话（或作为 structural-closure / a2h-execute 子步骤）执行。路径约定：`$IOS_SRC` 从 `<target>/.migbot/config.json` 的 `ios` 字段读取；产物落 `<target>/spec/`，禁落会话临时目录。本 skill 自有脚本：`scripts/icon_audit.py`（只读检测器）。

# arkts-icon-sizing — iOS 图片到 ArkUI 的尺寸校验

## 0. 定位与纪律

- **前置**：`<target>/.migbot/config.json` 存在且 `source_platform=ios`；先有源布局/源资源映射。
- **输入**：源布局/源资源映射、实际 Asset Catalog scale/point 尺寸及目标 `Image` 引用。
- **输出**：欠约束 Image 清单报告 + owned_files 内按已核实布局的尺寸/比例修复 + 复检/编译/设备验证记录。动态/未知来源保留待查项。
- **硬约束**：**只按源码和资源证据修复，禁止用统一密度替所有图片自动猜尺寸**；本入口**不自动改代码**。
- **第一条可见输出必须是一行校验计划**（检测 → 判定源意图 → 定向修复 → 复检/编译/设备），然后才执行 §1。
- 无人值守处置阶梯（门禁 FAIL 一律套用）：FAIL → 按命令 `retry_hint`/错误原文派修复并重跑，最多 2 轮；2 轮仍不过或确定模型修不了 → 记欠账放行；要拍板的模型自决并留痕；任何分支不得停机呈报人工。

## 1. 检测入口（只读，沿用 HMigBot Image 约束检查器）

```text
python <skill>/scripts/icon_audit.py --project-root <target> --output-json <report>
```

- exit 0 且 `status=passed` → 无欠约束候选；非 0 / `status != passed` → 有 `flagged` 项，读报告按 §3 判定源意图后修复。
- 检测项：缺 width/height（`NO-DIMS`）、仅单边无宽高比（`ONE-DIM-NO-ASPECT`）及 `ImageFit.Fill` 拉伸线索；判定后**回读真实目标组件上下文**，不只看链式属性。
- 本入口**不自动改代码**：不写 `.width()/.height()`，不迁移资源，源平台专用的尺寸推断器不注册为本包可执行入口（原资源与二进制保留在 vendor 中）。

| 脚本 | 职责 |
|---|---|
| `scripts/icon_audit.py` | 只读检测器（经 `native_helpers` 派发 `icon-audit`），扫 `*.ets` → 输出欠约束 Image 清单；**从不用默认密度反推 iOS scale** |

## 2. 问题与成因（iOS semantics）

iOS 里 `UIImage(size:)` 是**点（point）语义**，Xcode Asset Catalog 用 `@1x/@2x/@3x` 提供同一逻辑点的多倍率位图；SwiftUI 的 `Image` 用 `resizable/aspectRatio/frame`、UIKit 用 `contentMode/intrinsicContentSize/约束` 决定最终渲染尺寸。迁移时若丢掉了框架给的尺寸/比例，只有 Asset Catalog 位图被拷进 `resources/base/media`，ArkUI 会按位图**字面像素当 vp** 渲染——一张 `90×90 px` 的 `@3x` 图标本意是 `30×30 pt`，就显示成 `90×90 vp`（大 3 倍），非方形资源还会明显失真。

修复要点：**标称 pt = 位图像素 ÷ asset scale（@1x/@2x/@3x 分别为 1/2/3）**，宽高各自独立相除以保留真实宽高比。**但点尺寸不等于目标 vp 的无条件换算**——同一 asset 在不同 iOS 布局上下文（`frame` 固定值、`aspectRatio` 比例、约束拉伸、`contentMode` 裁剪）下的最终尺寸可能不同，必须回读源布局定意图，不能对“点→vp”做机械 1:1 猜测。

| asset scale | 倍数 |
|---|---|
| `@1x` | 1 |
| `@2x` | 2 |
| `@3x` | 3 |

**scale 是逐 asset 的，不是全局的**：多数工程对同一逻辑点只发一个 scale 档，但别假设——读取每个 asset 实际所在 scale 目录（`.xcassets/Images.xcassets/…/@3x` 结构）再定。Swift 源码里 `.imageScale`、SF Symbol 的 `font` 关联、`resizable(capInsets:)` 都会改变最终尺寸，先回读源布局，不默认按 `@3x` 全局除 3。

## 3. 判定源意图（分资源类型，不能统一处理）

| 类型 | 判定方式 |
|---|---|
| 常规位图 | 按 `UIImage.size`、asset scale、`resizable/aspectRatio/frame`、`contentMode/intrinsic size/约束` 确定源意图 |
| vector / SF Symbol | 矢量按标称尺寸渲染，只可能“尺寸错”、不会“比例错”；按源布局取本意 pt 显式设，勿用统一倍数 |
| 动态加载（`Image(this.foo())`、三元、`@Builder` 参数） | 顺方法/三元追踪到具体资源名，逐个解析；只报告/手工修，不自动改 |
| capInsets（可拉伸九宫格） | 保留拉伸意图，核对 insets 与容器约束，不当作普通图标缩比 |
| 动态字体关联图标 | 与字号缩放联动，单列处理，不并入普通位图换算 |

**`ImageFit.Fill` 的 `shape_*_bg`** 是可拉伸横幅背景的有意为之，放着别动；只在“真图标盒子比例 ≠ 图标比例”时才管。**已带尺寸的图标不要碰**——缺陷只针对那部分丢了尺寸的 `Image`，全局改资源密度会破坏本来正确的图标。

**决策规则（逐条）**：
- **方形 SVG 不会失真**：方形 `viewBox` 的矢量按标称 pt 渲染、比例正确，只可能“尺寸错”——若渲染过大，按源布局的 `frame`/约束取本意 pt 显式设，不用统一倍数。
- **`shape_*_bg` 上的 `ImageFit.Fill`** 是可拉伸横幅背景——放着别动。
- **别碰已带尺寸的图标**：重点就是欠约束的那部分，全局改资源/scale 会破坏本来正确的项。
- **多 target / SwiftPM 多 `.xcassets`**：把每个资源根都纳入源映射，scale 查找才能命中真实目录；资源跨模块时以实际所属 target 的 asset 为准。

## 4. 修复与验证

1. 在 `owned_files` 内、依据 §3 已核实的源布局补尺寸/比例：`NO-DIMS` → `.width(W).height(H)`（还原标称 pt 并乘像素换算）；`ONE-DIM` → `.aspectRatio(W/H)`——**保留容器约束和原宽高比**，已设的一维不重写。
2. 重跑只读检测（`status` 应为 passed 或仅剩有意跳过的动态项与 Fill 背景）。
3. 编译工程（`python <runtime>/scripts/a2h_ios.py build --project <target>` 或 hvigorw assembleHap）；插入的都是普通 `.width/.height/.aspectRatio`，编译通过即确认语法。
4. 在可用设备校验真实显示；动态/未知来源保留待查项，不猜值补齐。

## 5. 与 arkts-structural-closure 的联动

- structural-closure 的 **pipeline 模式**在调用原结构引擎前先跑本只读检测器，生成 native-images 报告；有欠约束 Image 时返回 `NATIVE_INPUT_REQUIRED`（exit 3），**不进入会修改图片尺寸的原 pipeline**。
- 处置顺序固定：先按本 skill 从真实 iOS 布局/asset scale 修复，再重跑 structural-closure；**不统一推测密度**。预检无候选后才进入原 pipeline（原尺寸自愈此时无待改对象）。
- 校验期间独占目标写锁；`NATIVE_INPUT_REQUIRED` 的责任 owner = 资源/源事实/结构输入方，修复后回到 structural-closure 重跑。

## 6. 检测器已知边界

- 按行识别链式属性：同一行 `Image(...).width(...).height(...)` 可能误报 `NO-DIMS`。**先核对原代码**，在 `owned_files` 内改成属性分行的等价写法后重跑；**不能把误报当作真实缺尺寸并猜值**。
- 动态源图片只报告、不自动改；检测器读不出 `Image(this.vipRes())` 的尺寸，这类按 §3“动态加载”逐项追踪。
- `width('100%') + height('100%')` 视为有意的满铺，不标记；只应在真图标盒子比例失真时处理。
- 检测器只认修饰链的宽高/宽高比标注，**看距离近 ≠ 已约束**——同一行链式写法与跨行写法都可能被漏读或误读，判定前先回读真实目标组件上下文，再决定要不要在 `owned_files` 内把链式属性分行。

## 7. 读取时机（references）

| 触发时机 | 必读 |
|---|---|
| 执行前；原生预检协议与 `NATIVE_INPUT_REQUIRED`（exit 3）语义 | ../arkts-structural-closure/SKILL.md |
| 源布局/资源映射事实 | ../ios-ui-analyzer/SKILL.md（若有 UI facts） |
| 同类 UI 消费侧修复的边界 | ../arkts-truncation-fix/SKILL.md（反向：裁切/溢出） |

## 8. 交接

- 交付：欠约束 Image 清单 + 修复 diff + 复检/编译/设备验证记录 + 仍待查的动态/未知项清单。
- 修复后交回 structural-closure 重跑 pipeline 或交 a2h-execute 继续；**残留待查项不得当作“已修”宣告**，未核实源布局的尺寸不得凭空猜值补位。