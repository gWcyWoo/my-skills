# ICP component reuse contract v1

Complete component analysis before claiming or dispatching page workers. Record the
project inventory source, searched project-relative paths, and a non-empty summary
even when no reusable demand exists.

For every component demand, choose exactly one decision:

- `reuse`: use an existing component without changing its owned code.
- `extend`: change the closest semantic shared component without breaking existing
  consumers.
- `create-shared`: create a shared component because multiple consumers have the
  same semantic responsibility.
- `create-local`: keep it within one feature/page because reuse would create a
  misleading abstraction; it must have exactly one consumer.

Base decisions on behavior, states, accessibility, data shape, and visual role, not
only names or superficial appearance. Record the chosen code path, consumers, and
evidence. Search existing shared components first, then feature-local analogues,
then choose creation scope.

`extend` and `create-shared` create one shared-component DAG node before all page
consumers. `reuse` creates no edit node. `create-local` remains owned by its single
page node, and all local-component paths must be contained by that page's
`allowed_paths`. Never let two workers own the same shared file.

Prefer this project organization unless stronger local conventions exist:

```text
app entry/navigation
ui/tokens
ui/components
features/<feature>/{data,domain,presentation/components}
```

Promote feature-local code to global shared code only when cross-feature semantic
reuse is proven. Include implementation and focused-test locations in
`allowed_paths`; the declared `code_path` must be one of them. Follow established
repository/module conventions over this fallback layout.
