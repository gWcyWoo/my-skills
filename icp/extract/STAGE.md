# Stage 1 — extract

从蓝湖设计稿提取语义组件规格。后续阶段（交互分析、代码实现）的一切基础。

## 流程

```
输入: ui_description(可空) + 蓝湖设计稿 URL
  ↓
Step 0  lanhu_fetch: URL → design.json + slices.json + cover.png + assets/
         (走静态版本数据，不经 lanhu MCP / DDS；详见 ../INPUT.md「取数」)
  ↓
Step 1  prepare: 读 JSON 生成节点摘要(树+扁平列表,标记系统组件)
  ↓
Step 2  模型结合 ui_description + 节点摘要 + 设计图 → 输出语义分组
  ↓
Step 3  bind: 按分组绑定设计数据 → 完备性检查
         ├─ 有遗漏 → 未覆盖节点反馈模型 → 回 Step 2
         └─ 全覆盖 ↓
Step 4  clean: 删除系统组件(Status Bar / Home Indicator)
  ↓
Step 5  enrich: 合并蓝湖切片数据(多倍率 URL) + 标记缺失图片资源
  ↓
Step 6  crop: 按 frame 坐标从整页截图裁切图标 → 写回 asset_path
  ↓
输出: component-spec.json
```

核心不变量：JSON 里每个设计元素都必须归属到某个语义 group，一个不能漏。

## 脚本

`scripts/lanhu_fetch.py` — 取数（Step 0）:

| 命令 | 输入 | 输出 |
|---|---|---|
| （无子命令） | `--url` `--out-dir` `--cookie`(可选) `--skip-cover`(可选) | design.json + slices.json + cover.png + assets/ |

`scripts/bind.py` — 6 个子命令:

| 命令 | 输入 | 输出 |
|---|---|---|
| `prepare` | `--design-json` `--ui-desc`(可选) `--output` | 节点摘要(树+扁平+meta) |
| `bind` | `--design-json` `--grouping` `--output` | 绑定结果 + unbound 列表 |
| `clean` | `--bound-json` `--output` | 去掉系统组件后的结果 |
| `enrich` | `--bound-json` `--slices-json` `--design-json`(可选) `--output` | 合并切片 + asset_required 标记 |
| `crop` | `--enriched-json` `--design-json` `--cover-image` `--output-dir` `--output` | 裁切图标 + 更新 asset_path |

错误输出格式: `{"ok": false, "errors": [{"type": "...", ...}]}`

bind 错误类型: `unknown_node`(分组引用了 JSON 中不存在的 id)、`duplicate_binding`(多个组抢同一节点)

## 模型分组输出格式

模型在 Step 2 输出的 JSON，供 `bind --grouping` 消费：

```json
{
  "groups": [
    {
      "name": "导航栏",
      "role": "navigation",
      "description": "顶部返回按钮+标题+右侧操作",
      "node_ids": ["92:2448", "I92:2448;70:624"]
    }
  ]
}
```

- `name`: 语义组件名（中文，描述这个 group 在页面中是什么）
- `role`: 组件角色（navigation / header / form / list / modal / footer / action / content / decoration）
- `description`: 一句话描述组件职责
- `node_ids`: 该组顶层节点的 id（来自 prepare 输出的节点摘要）。子树自动展开——声明一个父节点即覆盖其全部后代，除非某后代被其他组显式声明

## 模型分组指导

模型做分组时必须综合三个信息源：

1. **设计图**（视觉）：看页面长什么样，哪些元素在视觉上构成一个组件
2. **ui_description**（语义骨架）：如果非空，它描述页面的结构分区（如"结构分为4部份：顶部导航、表单区、按钮区、底部链接"），**以此为分组的骨架**，每个分区对应一个或多个 group
3. **节点摘要**（数据）：prepare 输出的 id/name/type/size/text/componentName/children，用于：
   - 确定 node_ids：每个 group 引用哪些顶层节点
   - `is_system: true` 的节点**也要分组**（保证全覆盖完整性，clean 步骤再删）
   - **root artboard（depth 0，整页那个节点）自身也要占一个 group**（如「页面根」）；
     它的子节点被别的组显式声明不冲突，漏了它必然 `unbound` 一轮
   - 同一个 `componentName` 出现多次 = 复用组件，归同一 group

三者冲突时：设计图 > ui_description > 节点名称。设计图上明显是一个整体的，不因节点名称不同而拆开。

## 完备性循环规则

1. 模型综合设计图 + prepare 摘要 + ui_description → 输出分组 JSON
2. `bind` 检查：JSON 每个节点（含系统组件）是否都归属了某个 group
3. 如果 `unbound` 不为空：
   - `bind` 返回未覆盖节点列表（含 id、name、type、parent_name）
   - 模型看这些节点在设计图的位置，判断它属于现有 group 还是需要新建 group
   - **在现有 groups 基础上追加或调整 node_ids**，输出新的完整分组 JSON
   - 再次调 `bind`，重复直到 `unbound` 为空
4. `unbound` 为空 → `ok: true`，进入 clean
5. 如果 `errors` 不为空（`unknown_node` / `duplicate_binding`）→ 修正 node_ids 后重新 `bind`

禁止：模型不得跳过未覆盖节点、不得凭空编造 node_id（`bind` 会报 `unknown_node`）。

## 职责划分

脚本(确定性):
- 读蓝湖 sketch JSON，建 id→node 索引
- 按 node_id 绑定设计数据，子树自动展开（遇其他组显式声明的节点停止）
- 完备性检查，输出未覆盖节点列表
- 删除系统组件、合并切片、裁切图标

模型(语义判断):
- 看设计图 + 节点摘要 + ui_description → 语义分组（格式见上）
- 收到未覆盖节点时，在现有分组上追加/调整，重新输出完整分组

## 系统组件识别

按名称模式匹配，自动删除:
- `Home Indicator`(iOS 底部指示条)
- `Status Bar` / `StatusBar` / `status_bar`
- `home_indicator`
