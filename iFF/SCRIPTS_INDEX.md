# iFF 脚本职责总表(权威索引)

> 按固定链 **取稿 → scene → render_plan → canvas → fixture → 交互 → 数据 → trace → fidelity → 10 道门** 归类。
> 每条列**消费 → 产出 → 验它的门**,数据流(artifact 链)显式可见——加/删脚本时,断链(产出无人消费)和
> 漏注册(不在 `verify_pipeline_scripts.py`)一眼可查。I/O 来自各脚本 argparse 实测,非记忆。
> 约定:产物默认落该设计 `spec_dir`(`lanhu/specs/<设计名>/`);app 代码落 `lib/`。**消费/产出方含"模型"**,不只脚本。

## ① 取稿
| 脚本 | 消费 | 产出 |
|---|---|---|
| `reconcile_feature` | lib-root, title | reconcile_decision.json(模型读它定归属) |
| `fetch` | url, cookie | **raw.json** + 切图 |
| `write` | raw.json | spec.md(人读) |
| `download_cover` | url, cookie | **reference.png** |
| `classify_design` | raw.json, reference.png | **classification.json** |

## ② scene
| 脚本 | 消费 | 产出 |
|---|---|---|
| `export_figma_scene` | raw.json, assets | **scene.json** |
| `check_figma_scene` | scene.json | (门)scene 合法性 |
| `export_tokens` | scene.json | **tokens.json** |
| `export_assets_manifest` | scene.json | **assets_manifest.json** |
| `group_figma_layout` | scene.json | **groups.json** |
| `make_figma_layout_contract` | scene.json, groups.json | **layout_contract.json** |

## ③ render_plan
| 脚本 | 消费 | 产出 |
|---|---|---|
| `make_render_plan` | scene.json, assets, layout_contract | **render_plan.json**(每节点渲染方式,核心) |
| `check_render_plan` | render_plan.json | (门)整图铺底/合法性 |
| `check_design_artifacts` | spec-dir | (门)全 artifact id 互相可回溯、尺寸一致 |

## ④ canvas
| 脚本 | 消费 | 产出 |
|---|---|---|
| `make_component_manifest` | render_plan, classification, groups, scene | **component_manifest.json** + 动态文本槽候选 |
| `generate_canvas` | **render_plan, tokens** | **canvas.dart + expected.json + slots.json + colors**(带 key 数据驱动画布,模型写0像素) |
| `copy_assets` | assets_manifest, target | assets/images/* |
| `update_pubspec_assets` | pubspec, asset | pubspec.yaml 注册 |
| `sync_project_rules` | implementation_rules, project-root | 注入工程 CLAUDE.md |

## ⑤ fixture
| 脚本 | 消费 | 产出 |
|---|---|---|
| `make_visual_fixture` | feature, slots.json | **`<Feature>VisualFixture`**(同源 fixture) |
| `check_fixture_source` | root, fixture-name | (门)test ∧ runtime 引用同一 fixture |

## ⑥ 交互
| 脚本 | 消费 | 产出 |
|---|---|---|
| `parse_interactions` | 交互散文, input | **interaction_contract.json** |
| `check_interaction_completeness` | interaction_contract | (门)被忽略的规则句必须提取/登记 |
| `make_interaction_tests_plan` | interaction_contract, api_contract | **interaction_test_plan.json** |
| `check_interaction_wiring` | lib-root, test-root, contract | (门)每规则有运行时调用点 |
| `check_interaction_coverage` | test_plan, test-root, evidence | (门)每 case red(exit≠0)→green(exit=0)、非 skip |

## ⑦ 数据
| 脚本 | 消费 | 产出 |
|---|---|---|
| `normalize_api_contract` | OAS(Apifox) | **api_contract.json** |
| `bind_data_slots` | component_manifest, api_contract, interaction_contract | **data_slot_bindings.json**(模型确认绑定) |
| `check_api_integration` | api_contract, lib-root | (门)每端点有 repo 调用点 |

## ⑧ trace
| 脚本 | 消费 | 产出 |
|---|---|---|
| `gen_layout_trace_test` | expected.json, page-import/type | 真实页 trace 测 → **actual_layout_trace.json** |

> 喂 trace/fidelity 前的**真机诊断旁路**:`capture_runtime_screenshot`(→actual.png 真机像素)· `visual_diff`(像素 diff,**仅诊断**,跨引擎天花板)· `make_repair_plan`(diff→repair_plan.json,单次修复输入)。

## ⑨ fidelity
| 脚本 | 消费 | 产出 |
|---|---|---|
| `check_render_fidelity` | trace, expected, tokens | **视觉 PASS 门**:真实渲染 vs render_plan 逐节点(bbox≤2/色≤3/字号·圆角≤1/文案·token 100%) |

## ⑩ 10 道门(done 前 barrier)
done 前统一再跑一遍,全过才 `done`(SKILL.md L280-300)。**不是另外 10 个脚本**——是各阶段的门 + 4 个跨切面门汇总:
- 跨切面门:`check_visual_manifest`(actual=真机非派生)· `check_implementation_plan`(产前对齐)· `check_implementation_map`(可见节点覆盖率)· `check_worker_compliance`(worker 加载当前规则)。
- barrier 再跑的阶段门:`check_render_plan` · `check_design_artifacts` · `check_fixture_source` · `check_interaction_completeness` · `check_interaction_coverage` · `check_interaction_wiring` · `check_api_integration` · `check_render_fidelity`。

## 编排 / 辅助(不在链上)
- `verify_pipeline_scripts`(预检:39 脚本齐全)· `make_worker_prompt`(命令式 worker todo)。
- `common`(共享库,~24 脚本 import)· `selftest_canvas`(可见层回归自测,corpus 驱动)· `classify_blocker`(自进化路由,旁路)。

## 断链/漏注册自查规则
> 消费/产出方含"模型":`implementation_map.json` 由模型写、被 `check_implementation_map` 消费;`repair_plan.json`/`data_slot_bindings.json` 由模型读。判死链前先确认不是"模型产/模型消费"。
1. 任一脚本的产出 artifact 必须有下游消费(脚本或模型),否则死产物。
2. 任一被消费的 artifact 必须有上游产出(脚本或模型),否则 worker 读到空。
3. 各阶段的核心产物(scene/render_plan/canvas/contract/api_contract…)必须有 ≥1 道门验它。
4. 所有非辅助脚本必须在 `verify_pipeline_scripts.py` REQUIRED 中(曾抓到 generate_canvas 漏注册)。
