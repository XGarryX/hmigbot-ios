---
name: arkts-icon-sizing
description: "核对 iOS 图片/符号的真实布局、Asset Catalog scale 与目标 ArkUI 尺寸；只按源码和资源证据修复，禁止用统一密度替所有图片自动猜尺寸。"
---


# iOS 图片到 ArkUI 的尺寸校验

输入源布局/源资源映射、实际 Asset Catalog scale/point 尺寸及目标 Image 引用。
静态检测沿用 HMigBot Image 约束检查器，入口为：

```text
python <skill>/scripts/icon_audit.py --project-root <target> --output-json <report>
```

1. 检测缺 width/height、仅单边无宽高比及 Fill 拉伸线索，回读真实目标组件上下文。
2. 按 UIImage.size、asset scale、SwiftUI resizable/aspectRatio/frame、UIKit contentMode/
   intrinsic size/约束确定源意图。点尺寸不等于目标 vp 的无条件换算。
3. vector/SF Symbol、动态加载、capInsets、动态字体关联图标分别处理，不能统一除以 3。
4. 在 owned_files 内按已核实布局补尺寸/比例，保留容器约束和原宽高比。
5. 重跑只读检测、编译，并在可用设备校验真实显示。动态/未知来源保留待查项。

本入口不自动改代码。原结构 pipeline 在运行前先做此原生预检；有欠约束图片时
返回 NATIVE_INPUT_REQUIRED，待依据源事实修正后重跑，防止旧默认密度自愈误改 iOS 页面。
原资源和二进制保留在 vendor 中，但源平台专用的尺寸推断器不注册为本包可执行入口。

检测器已知边界：按行识别链式属性，同一行 Image(...).width(...).height(...) 可能误报 NO-DIMS。先核对原代码，在 owned_files 内改成属性分行的等价写法后重跑；不能把误报当作真实缺尺寸并猜值。
