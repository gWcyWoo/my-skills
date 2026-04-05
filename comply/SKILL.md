---
name: comply
description: Load relevant coding standards via subagent. Reads project dependencies and extracts only the rules that apply to the current task.
---

# Load Coding Standards

Fill in the task context below, then dispatch as a subagent with `mode: "bypassPermissions"` and `model: "sonnet"`:

---

Read `package.json` in the current project to identify dependencies. Based on the dependencies and the files listed below, read ONLY the matching rule files from `/Users/Woo/.code/shared-rules/`:

- `.ts`/`.tsx` files in scope → `common/typescript.md`
- `react` in dependencies → `frontend/reactjs.md`
- `vue` in dependencies → `frontend/vue3.md`
- `next` in dependencies → `frontend/nextjs.md`
- `next` + files touching server/database → `frontend/nextjs-fullstack.md`
- `express` in dependencies → `backend/express.md`
- `mongoose` or `mongodb` in dependencies → `backend/mongodb.md`
- Backend service/domain files → `backend/ddd.md`
- Frontend component/page files → `frontend/architecture.md`

For each selected file, return only the rules relevant to this task. Skip everything else. Keep the output under 200 lines.

**Task:**
- Summary: [FILL IN]
- Files: [FILL IN]
- Change type: [FILL IN]
