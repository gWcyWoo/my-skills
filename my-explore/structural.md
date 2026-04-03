# Structural — find all code matching a pattern

1. ast-grep find_code or find_code_by_rule. NEVER use Grep with regex for structural search.
2. Narrow with `inside`/`has` constraints in YAML rules if too many results.
3. Use ast-grep analyze-imports for import/dependency analysis.
