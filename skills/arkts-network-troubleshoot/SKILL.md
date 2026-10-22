---
name: arkts-network-troubleshoot
description: "对照 iOS 的真实服务契约排查鸿蒙网络行为差异，检查请求/响应、TLS、鉴权、编码、缓存、取消与错误，并用独立契约证据验证修复。"
---


# iOS 与鸿蒙网络契约核对

先读 ios-api-inventory 的 endpoint/common 契约和受影响 feature AC，
再读 arkts-data-layer 中实际使用的目标网络实现。源静态 URL 线索不是抓包结果。

1. 固定同一账号状态、服务环境、输入和时间条件，区分源/目标/服务端证据。
2. 对比 method、path/query 编码、headers、cookie、token 刷新、请求体、签名字段和时钟。
3. 对比响应信封、HTTP/业务状态、空值、数值/时间单位、分页、缓存与重试幂等性。
4. 核对 ATS/TLS/证书与目标网络安全策略、域名配置、权限和 DNS/代理。
   不能为绕过错误而关闭证书校验或记录明文凭据。
5. 检查 URLSession/Combine/Task 的源取消/顺序，与目标回调是否导致旧响应覆盖新状态。
6. 只有已授权且实际配置的 iPhone/云日志/代理才用于源运行证据；无设备则静态分析。
7. 修复最小根因并执行对应 contract/unit/device 检查，记录真实请求脱敏摘要与退出结果。

涉及认证和用户数据的日志保留最小必要脱敏证据。不能用目标端 mock 响应作为源行为真值。
未连通服务时记录 unverified，保留可复现输入和下一步依赖，不宣告网络等价。
