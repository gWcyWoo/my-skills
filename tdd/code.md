# Implement & Review (Step 3)

## 3a. Load coding standards

Use the `my-subagent` skill to extract only the relevant coding standards. Do not call `spawn_agent` directly.

> 1. Read the relevant `package.json` file or files to identify the frameworks and libraries in use.
> 2. Based on the dependencies and the files being modified, select ONLY the matching rule files from `/Users/Woo/.code/shared-rules/`:
>    - TypeScript files: `common/typescript.md`
>    - `react` in dependencies: `frontend/reactjs.md`
>    - `vue` in dependencies: `frontend/vue3.md`
>    - `next` in dependencies: `frontend/nextjs.md`
>    - `next` in dependencies plus backend or database files: `frontend/nextjs-fullstack.md`
>    - `express` in dependencies: `backend/express.md`
>    - `mongoose` or `mongodb` in dependencies: `backend/mongodb.md`
>    - Backend domain or application-layer files: `backend/ddd.md`
>    - Frontend component or page files: `frontend/architecture.md`
> 3. From the selected files, extract and return ONLY the sections relevant to this task. Do not return entire files.
>
> **Task context:**
> - Summary: [the confirmed understanding from Step 1]
> - Files to modify: [list of files]
> - Type of change: [e.g. state management, API handler, UI component, database operation]

## 3b. Implement

Apply the returned rules during implementation. Keep changes minimal and focused.

## 3c. Review

After implementation is complete, **STOP and ask the user**:

> Implementation complete. Would you like to review before running lint and tests?

- If yes, wait for feedback, apply changes, then ask again whether to proceed to Step 4.
- If no, proceed to Step 4.
