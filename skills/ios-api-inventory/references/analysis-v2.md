# API 和平台接缝协议

先读取 facts-view --scope api 与工程依赖。沿真正调用点识别 URLSession/三方 client、存储、系统框架、权限、entitlements、xcprivacy、登录/支付/广告/客服接缝；包名存在不证明被使用。

服务事实对象保存 endpoint/method/headers/auth/request encoding/response/error/cancel/cache。系统事实保存调用、数据/句柄、初始化、权限申请时机、拒绝/受限、回调和销毁。原生 SDK 保存真实版本、许可、公开类型和实际调用表；平台特有能力先记源事实，再交明确决策。

Permission 文案、entitlements 与实际请求点共同核对。不能只把 Info.plist 的键复制到目标；不复制签名、团队或 provisioning 数据。源工程没有凭据时记录所需环境，不用假账号或 mock 成功替代真实行为。

输出模板：api/system ID、source anchors/fact_ids、接口契约、权限/生命周期、三方依赖版本与调用、可观测影响、独立 contract/device AC、待决策差异、来源置信度。API 与 UI/功能的共享事实单一 owner，使用 ID 引用，避免重复登记。

目标库核验交 arkts-library-migration/hmos-sdk-docs；选择依据须匹配当前 SDK 与实际接口，不能靠相似名称。未知继续 finding，源码接缝错误不能用设备 unavailable 放行。发布报告分开列生成、编译、协议观察与设备结果。
