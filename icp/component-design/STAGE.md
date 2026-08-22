# Stage 2 — component-design(规范,未实现)

> 本目录当前只有契约。实现时必须先建 Stage 2 金标准(基于已 verified 的 Stage 1 产物)+ 变异测试,方法与 Stage 1 完全同构。

## 输入
`semantic-blocks.json`(冻结,只读)、API 契约来源(Apifox 项目)、导航参照(路由表)。

## 输出与不变量(裁判脚本待实现,应逐条机器校验)
- `component-spec.json`:组件树,每组件绑定 ≥1 个 Block;Block→组件为满射(无 Block 落空)。
- 交互原子五字段:`condition / state / trigger / behavior / result`,五者齐备,每个原子恰好绑定一个组件;`result` 只能引用已声明的 state、路由或 API 调用。
- API 绑定:每个 `dynamic_content` 成员必须溯源到一个 API 字段或显式标记 `client_state`;虚构接口 = 错误(对照 Apifox 导出的契约哈希)。
- 组件锁:组件命名与边界一旦评审通过即冻结,Stage 3 不得更改。
- 禁令:不得改动 Block 划分;发现划分错误 → 报 `blocking_stage1_defect` 停止,回 Stage 1。

## 循环
与 Stage 1 相同的棘轮/停机/度量机制,判定键 = hash(组件内容 + 绑定的Block集合 + 交互原子集合)。
