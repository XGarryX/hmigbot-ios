# Slice Step 3a：UI 补充

输入 slice_file、page_spec_paths、owned_files、已存在 UI、原生 facts 与 design tokens。
profile 2 同带plan_item_refs/ac_ids、精确spec_refs与contract_refs闭包，按_common.md分批消费并报告consumed_refs/unread_refs/contract_conflicts。
检查页面 converted 状态和真实 .ets；已转换页仍参与本 slice 的接线工作。
缺 UI 时按 ios-ui-to-arkui 实现指定页面/嵌入组件，保持 source_anchors 与业务事件接口。
页面源事实不足回 a2h-spec 按需补齐；不要据名称合成空白页面后声称转换完成。
读取 tokens 和资源映射，若主题输入存在则实际运行 theme_brief 并保留真实回执。
返回变更文件、需实例化/注册组件、资源/占位及检查结果；共享接线交 Step 3d closer。
