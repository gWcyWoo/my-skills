# 指标与工具限制

仅在汇总指标或诊断相关工具结果时读取。已记录限制须结合当前脚本和运行确认，不能据此直接豁免验收。

## stage3-metrics.json

汇总所有步骤的记录项,一个页面一份。用于跨页面横向对比。

计数只用于定位差距，不替代需求到用例的映射。脚本 `interaction_gap` 按正例数量估算：一个有效场景覆盖多个需求时可能报差距，许多重复用例也可能掩盖漏验。须逐项核实实际断言与结果，不能为消除数值差距添加重复测试或改写原始统计。

命令:
```
metrics.py --work-dir <page-work-dir> --title <page-title> --platform <platform> --output stage3-metrics.json
```

指标键与流程步骤映射 (流程 Step 3/4 为模型驱动,无确定性产出文件,不纳入指标;流程 Step 6 拆为 struct_diff + visual_diff + attribution 三个指标块):

| 指标键 | 流程步骤 | 产出文件 |
|---|---|---|
| step1_blueprint | Step 1 蓝图提取 | layout-blueprint.json |
| step2_contract | Step 2 接口契约 | api-contract.json |
| step5_probe | Step 5 渲染采集 | probe-result.json |
| step6_struct_diff | Step 6 辅助预检 | struct-diff.json |
| step7_visual_diff | Step 6 视觉对比 | visual-diff.json |
| step8_attribution | Step 6-7 归因 | attribution-ledger.json |
| step9_behavior | Step 7 行为验证 | behavior-result.json |

```json
{
  "title": "单期还款",
  "platform": "android",
  "timestamp": "...",
  "step1_blueprint": { "blueprint_components": 5, "blueprint_texts": 11 },
  "step2_contract": { "contract_apis": 1, "contract_apis_resolved": 1, "contract_apis_mock": 0, "contract_interactions": 4, "contract_components": 3, "contract_component_types": {"new": 2, "existing_shared": 1} },
  "step5_probe": { "render_ok": true, "render_view_nodes": 28 },
  "step6_struct_diff": { "struct_texts_expected": 11, "struct_texts_matched": 11, "struct_texts_missing": [], "struct_components_expected": 5, "struct_components_matched": 5, "struct_components_missing": [], "struct_hierarchy_ok": true },
  "step7_visual_diff": {
    "visual_pass": true,
    "visual_issues": []
  },
  "step8_attribution": { "total_rounds": 2, "attributions": {"codegen": 3, "environment": 1} },
  "step9_behavior": { "behavior_total": 5, "positive_total": 3, "positive_passed": 2, "negative_total": 2, "negative_passed": 1, "mock_violations": 0, "quality_rewrites": 0, "interaction_gap": 1 }
}
```

## 复盘数据点

| 指标 | 来源 | 优化信号 |
|---|---|---|
| 编译修复轮数 | checklist (模型记录) | 高 → 代码生成 prompt/约束需改进 |
| 编译错误类型分布 | checklist (模型记录) | 集中在某类 → 针对性加 prompt 约束 |
| 文案覆盖率 | step6_struct_diff.struct_texts_matched / struct_texts_expected | 低 → 蓝图提取或代码生成遗漏文案 |
| 视觉修复轮数 | step8_attribution.total_rounds | 高 → 初次生成与设计稿还原能力弱 |
| 归因分布 | step8_attribution.attributions | codegen 占比高 → 代码生成 prompt 需改进 |
| 视觉问题明细 | step7_visual_diff.visual_issues | 各条目含 severity,统计分布定位系统性缺陷 |
| 正例通过率 | step9_behavior.positive_passed / positive_total | 低 → 交互实现能力或接口契约质量 |
| 反例通过率 | step9_behavior.negative_passed / (behavior_total - positive_total) | 低 → 缺少前置条件缺失时的降级处理 |
| mock 违规数 | step9_behavior.mock_violations | >0 → 测试绕过了框架边界,有效性不可信 |
| 测试重写次数 | step9_behavior.quality_rewrites | 高 → 模型首次生成的测试层级/断言质量不达标 |
| 交互覆盖差距 | step9_behavior.interaction_gap | >0 → 正例总数 < contract_interactions,有交互未被测试覆盖 |
| 单页总耗时 | timestamp diff | 基线,跨页面对比 |

## 已知限制

| 编号 | 范围 | 说明 | 影响 |
|---|---|---|---|
| L1 | blueprint | Stage 1 提取了 opacity/border-radius/borders/shadows/blur,但 blueprint.py 未读取 | 代码生成缺少圆角和阴影信息,视觉还原靠模型从截图推断 |
| L2 | blueprint | 文本 style 仍仅取 spans[0]；多填充已通过 layers 保留完整顺序 | 多样式文本段仍需核对 enriched 中的原始 spans；不能把首段样式用于整段 |
| L3 | struct_diff | 检查文案内容和层级顺序,不检查空间位置 | 文案在页面中位置错乱不会被 struct_diff 发现 |
| L4 | validate | 不验证代码是否使用了 resolved.path/method/auth | 代码可能硬编码错误路径或 auth 策略,validate 不报错 |
| L5 | visual loop | 无确定性自动闸门,完全依赖模型判断 | 视觉修复质量取决于模型能力 |
| L6 | probe | 导航验证仅要求 ≥1 条文案匹配 | 到达错误页面但碰巧含公共文案时误判为成功 |
| L7 | blueprint | 负 spacing/padding 表示子元素重叠或溢出容器,平台 spacedBy()/Padding() 无法表达 | 模型需自行判断使用 stack/offset 替代 |
| L8 | test_lint | ≥2层交互的层级匹配 + 链路内 mock 检查靠模型自查,无脚本 | 4层交互用组件测试可全绿 |
| L9 | validate | extract_shared affected_not_referenced 仅搜索 gen_dir 内的代码,affected 组件通常在其它 feature 目录 | 始终触发 warning,不区分已重构/未重构 |
| L10 | validate | 绝对定位比例豁免检查 offset 起始行+4 行窗口,变量间接引用 (val y=maxHeight*0.3; ...多行...; offset(y=y)) 不豁免 | 超窗口的比例引用 offset 被误报 |
| L11 | test_lint | error-handling 降级路径的 error token 仅匹配英文关键词 | 纯 CJK 本地化错误文案的测试被误标 pattern-mismatch |
| L12 | blueprint | inner_padding 取 ALL children min(left-gap),children_widths baseline 排除 full-bleed 后取 min | padding=0(被 full-bleed 拉低) 而 children_widths=fill(baseline 排除 full-bleed 后仍有余量)——同一子组件的 padding 与 width 判定不一致 |
| L13 | test_lint | file_mock_vars 为文件级,不区分同文件内的多个测试类 | 两类同名变量 val repo 会跨类误报 mock-assert |
| L14 | blueprint | children_widths 以成员 name 做 key,Lanhu 导出的自动命名(编组/矩形)重复 | 重名子元素产出歧义 fill/fixed 对 |
| L15 | blueprint | image 类型 fill 输出蓝湖 CDN url,无本地资产映射 | 模型可能生成 Image.network() 引用设计工具 CDN |
| L16 | blueprint | members 是 DFS 展平的子树,layout/spacing/children_widths/padding 在混合深度上计算 | 中间层(卡片/区块)的 frame 与其子级共存于同一列表,产出负 spacing 和错误的 fill/fixed 判定;L7 描述的负值主因即此 |
| L17 | blueprint | classify_members 丢弃无 fills 且无 shared_style 的 artboard(如仅有 border/shadow/radius 的描边卡片) | 其 frame 从布局计算中消失,padding/children_widths 失真(assets 不受影响,遍历 raw members) |
| L18 | blueprint | 非 artboard/symbolInstence 容器以首个子级 frame 作为 container_frame,该子级同时留在 content | 容器高宽 = 子级高宽 → padding/width 基准失真;container_fill 重复出现在 fill 和 child_fills |
| L19 | blueprint | children_widths 仅用 column 逻辑(pad_start/pad_end)判定 fill/fixed,不读 layout 字段 | row 内子元素全判为 fixed → 模型生成硬编码像素宽度;无 wrap/intrinsic 值 |
| L20 | blueprint | infer_layout band 容差 4px + 平票归 column → 两元素横排(top 偏差 ≤14px)误判 column | 缩略图+文字列表行产出 column + 负 spacing |
| L21 | validate | DTO 字段搜索在整个拼接源码中 \b 匹配;Kotlin `data class` 的 `data` 满足 response envelope 的同名字段;len(snake)<3 的字段(id/ok/qr)被跳过 | 字段存在性检查过松——别处出现的同名标识符、语言关键字和短字段均可静默通过 |
| L22 | test_lint | error-handling 降级路径的 error token 搜索整个 block_text,变量名(errorFree)和 mock setup(throws)均可满足 | 测试无需断言降级 UI 即可通过 error-handling 模式检查 |
| L23 | probe/struct_diff | Web 目标:浏览器以 waitUntil:load 抓取 DOM,SPA(React/Vue/Flutter web)的水合前 shell 无应用文案 | struct_diff 文案覆盖 ≈0% → 正确代码误判 FAIL;截图为空白页 |
| L24 | struct_diff | 层级顺序以 view-tree DFS 索引比较,非几何坐标;uiautomator bounds / idb AXFrame 在 parse 时丢弃 | Stack/overlay/FAB 先于 body 出现在语义树 → order_correct=False 误报;L3 的位置盲点即源于此 |
| L25 | validate | uikit 和 android-views 两个平台无 _OFFSET_PATTERNS 条目,绝对定位检测静默跳过 | 这两个平台上的硬编码 frame/translationX/setX 不报错 |
| L26 | validate | 文件级 scope_re 豁免:文件内任意位置出现 BoxWithConstraints/LayoutBuilder/GeometryReader 即跳过整个文件的绝对定位检查 | 一个响应式 composable 缴械同文件全部硬编码 offset;Stage 3 常单文件多 composable |
| L27 | struct_diff | HTML 正则解析只取开标签后的首段直接文本([^<]*),子元素后的尾文本(tail text)丢失 | Web 端 `<div>a<b>x</b>b</div>` 只取 "a",丢 "b" → 文案覆盖率偏低 |
| L28 | blueprint | fill/fixed 阈值(2px/4px)使用原始导出像素,未除以 scale;3x 导出下 4px≈1.3dp | 高倍率导出下 fill 被误判 fixed → 模型硬编码像素宽度 |
| L29 | blueprint | frame 字段以下标访问(f["top"]/f["height"]),上游 bind.py 透传蓝湖 frame 无字段校验 | 蓝湖返回不完整 frame(缺 height)时 KeyError 崩溃 |
