# Stage 1 converter 任务契约

派发 a2h-ios-converter，输入 page_id/source_root/page_spec/ui_info/target、
ios-semantics 对应事实、owning_slice、wiring_ownership_map、registered_placeholders、owned_files。
profile 2 同带 plan_item_refs、ac_ids、页面精确spec_refs与contract_refs闭包，按_common.md读取并报告consumed_refs/unread_refs/contract_conflicts。
读取 ios-ui-to-arkui 与 arkts-component-builder 及当前相关目标参考。
保存源状态/Binding/约束/事件语义，实际生成归属页面与组件；共享装配由 batch closer 完成。
读取 ui-manifest 全局 design tokens，不硬编码替代已有 token。
占位写明确 P-ID 和归属，返回实际文件、资源请求、接线需求、未决问题和检查结果。
不得用空 handler 视作业务完成；新发现源缺口回 Phase A/B，不猜布局或运行证据。
