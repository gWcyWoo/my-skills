# iFF 脚本职责总表(权威索引)

> 39 条流水线脚本 + 3 辅助。**消费 → 产出 → 验它的门**逐条列清,数据流(artifact 链)显式可见——
> 新增/删除脚本时,断链(产出无人消费)和漏注册(不在 `verify_pipeline_scripts.py`)一眼可查。
> 来源:各脚本 argparse 实测 I/O(非记忆)。改脚本必须同步本表 + preflight 清单。

约定:产物默认落在该设计的 `spec_dir`(`lanhu/specs/<设计名>/`);app 代码落 `lib/`。

## 预检 & worker(3)
| 脚本 | 消费 | 产出 | 说明 |
|---|---|---|---|
| `verify_pipeline_scripts` | skill-dir | (exit码) | 预检 39 脚本齐全,缺一即停 |
| `make_worker_prompt` | row-json, spec-dir, project-root | worker prompt | 命令式 worker todo(强制先跑工具) |
| `check_worker_compliance` | skill-dir, manifest | (exit码) | worker 真加载当前 SKILL/规则(哈希一致) |

## 阶段 0 取稿 & 分类(5)
| 脚本 | 消费 | 产出 | 验它的门 |
|---|---|---|---|
| `reconcile_feature` | lib-root, title | **reconcile_decision.json**(模型读它定归属) | — |
| `fetch` | url, cookie | **raw.json** + 切图 | — |
| `write` | raw.json | spec.md(人读) | — |
| `download_cover` | url, cookie | **reference.png** | — |
| `classify_design` | raw.json, reference.png | **classification.json** | check_design_artifacts |

## 阶段 2–3 编译机器视觉产物(8)
| 脚本 | 消费 | 产出 | 验它的门 |
|---|---|---|---|
| `export_figma_scene` | raw.json, assets | **scene.json** | `check_figma_scene` |
| `export_tokens` | scene.json | **tokens.json** | check_design_artifacts |
| `export_assets_manifest` | scene.json | **assets_manifest.json** | check_design_artifacts |
| `group_figma_layout` | scene.json | **groups.json** | check_design_artifacts |
| `make_figma_layout_contract` | scene.json, groups.json | **layout_contract.json** | check_design_artifacts |
| `make_render_plan` | scene.json, assets, layout_contract | **render_plan.json**(核心) | `check_render_plan` |
| `check_figma_scene` | scene.json | (门) | — |
| `check_design_artifacts` | spec-dir | 总审计:全 artifact id 互相可回溯/尺寸一致 | — |

## 阶段 5 组件树 & 同源 fixture(2)
| 脚本 | 消费 | 产出 | 验它的门 |
|---|---|---|---|
| `make_component_manifest` | render_plan, classification, groups, scene | **component_manifest.json**(+动态槽候选) | check_implementation_map |
| `make_visual_fixture` | feature, slots.json | **`<Feature>VisualFixture`** | `check_fixture_source`(同源) |

## 阶段 6 交互契约(3)
| 脚本 | 消费 | 产出 | 验它的门 |
|---|---|---|---|
| `parse_interactions` | 交互散文, input | **interaction_contract.json** | `check_interaction_completeness` |
| `check_interaction_completeness` | interaction_contract | (门)漏抽规则 FLAG | — |
| `make_interaction_tests_plan` | interaction_contract, api_contract | **interaction_test_plan.json** | check_interaction_coverage |

## 阶段 6.5–8 计划/规则注入/画布/资产/数据(8)
| 脚本 | 消费 | 产出 | 验它的门 |
|---|---|---|---|
| `check_implementation_plan` | implementation_plan, spec-dir | (门)产前强制对齐 | — |
| `sync_project_rules` | implementation_rules, project-root | 注入工程 CLAUDE.md | — |
| `generate_canvas` | **render_plan, tokens** | **canvas.dart + expected.json + slots.json + colors**(核心,模型写0像素) | check_render_fidelity |
| `copy_assets` | assets_manifest, target | assets/images/* | — |
| `update_pubspec_assets` | pubspec, asset | pubspec.yaml 注册 | — |
| `normalize_api_contract` | OAS(Apifox) | **api_contract.json** | check_api_integration |
| `bind_data_slots` | component_manifest, api_contract, interaction_contract | **data_slot_bindings.json** | check_api_integration |
| (模型实现) | 全部上游 artifact | repository/DTO/页面接线 | 下方 12 门 |

## 阶段 9–11 真机截图 & 单次修复(3)
| 脚本 | 消费 | 产出 | 性质 |
|---|---|---|---|
| `capture_runtime_screenshot` | manifest, route, w/h | **actual.png**(真机) | 诊断 |
| `visual_diff` | reference.png, actual.png, layout | **diff_report.json** | **仅诊断**(跨引擎天花板) |
| `make_repair_plan` | diff_report, layout, render_plan | **repair_plan.json** | 单次修复输入 |

## 阶段 12 done 前审计门(8)
| 门 | 消费 | 验什么 |
|---|---|---|
| `gen_layout_trace_test` | expected.json, page-import/type | 生成真实页 trace 测 → **actual_layout_trace.json** |
| `check_render_fidelity` | trace, expected, tokens | **视觉 PASS 门**:真实渲染 vs render_plan 逐节点(bbox≤2/色≤3/字号·圆角≤1/文案·token 100%) |
| `check_interaction_wiring` | lib-root, test-root, contract | 每规则有运行时调用点 |
| `check_interaction_coverage` | test_plan, test-root, evidence | 每 case red→green |
| `check_api_integration` | api_contract, lib-root | 每端点有 repo 调用点 |
| `check_implementation_map` | render_plan, implementation_map, min-cover | 覆盖率 |
| `check_render_plan` | render_plan | 整图铺底/合法性 |
| `check_visual_manifest` | reference, actual | provenance(真机非派生) |
| `check_fixture_source` | root, fixture-name | 同源(test∧runtime 都引用) |

## 辅助(3,不在主流程预检)
- `common` — 共享库(~24 脚本 import)。
- `selftest_canvas` — 可见层工具链回归自测(corpus 驱动:`evolution/regression/*`)。
- `classify_blocker` — 自进化路由器(失败→①自改/②强契约/③升级/④天花板);**尚未接主流程**。

## 断链/漏注册自查规则
> **消费/产出方包含"模型"**,不只脚本:`implementation_map.json` 由模型写、被 `check_implementation_map` 门消费;
> `repair_plan.json` / `data_slot_bindings.json` 由模型读。判死链前先确认不是"模型产/模型消费"。
1. 任一脚本的 **产出 artifact 必须有下游消费**(脚本或模型),否则是死产物。
2. 任一被消费的 artifact 必须有 **上游产出**(脚本或模型),否则 worker 会读到空。
3. 阶段 0–8 的每个**核心产物**(scene/render_plan/canvas/contract/api_contract…)必须有**至少一道门**验它。
4. 所有非辅助脚本必须在 `verify_pipeline_scripts.py` REQUIRED 中(本次就抓到 generate_canvas 漏注册)。
