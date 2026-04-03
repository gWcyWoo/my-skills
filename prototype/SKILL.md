---
name: prototype
description: Design-to-page rapid prototyping for non-technical users. Takes a design mockup link, generates a visible static page, then iteratively refines UI, interactions, and data through guided conversation. Produces a complete spec and lets the user choose the next step.
---

# Rapid Frontend Prototype

Turn a design mockup into a working page through guided iteration. Built for users who have a design but don't know how to implement it.

**Audience**: Non-technical users. All questions must use plain language — no technical jargon (no "hooks", "state management", "API endpoints", "components"). Translate technical concepts into what the user sees and does.

## When to Use

- User has a design mockup link (Figma, MasterGo, etc.) and wants to see it working
- User wants to iterate on a page visually before committing to full development

## When NOT to Use

- User already has a written spec — use `spec` skill instead
- User wants to discuss requirements without a design — use `spec` skill instead
- Pure backend/API work with no visual output

## Inputs

- A design mockup link (required)
- An existing project with a frontend framework (required — this skill generates pages inside the user's project)

## Outputs

- A working page accessible via dev server
- A complete spec file at `specs/{area}/v{n}/{feature}.spec.md`

---

## Phase 1: UI Confirmation

Goal: user can see a static page that matches the design mockup.

### Step 1.1: Receive Design Link

User provides a design mockup URL. Call d2spec to explore the design:

```
d2spec.list_designs(url)
```

If the user's URL matches a specific design in the results (compare the URL path or design ID), pre-select that design and confirm:

> "This links to the **LoanHub Homepage** design. Is that the page you want to build?"

If the URL points to the project root (no specific design), present the available pages:

> "I found these pages in the design:
> 1. Post list page
> 2. Post detail page
> 3. New post form
>
> Which one should we start with?"

If only one page exists, confirm it directly.

### Step 1.2: Extract UI Structure

For the selected page, call only:

```
d2spec.get_component_tree(url, format="markdown")
```

This returns a markdown description of the page's component tree with layout, sizing, colors, typography, and hierarchy. This is the sole input for understanding the UI structure and for generating the page code. Do NOT call `get_design_data` — it returns raw JSON that is too verbose and not needed.

Summarize the component tree to the user in plain language (do NOT show the raw markdown):

> "I can see this page has: a search bar at the top, a list of post cards in the middle, and a floating button at the bottom right. Does that match what you expect?"

### Step 1.3: Determine Module Path

This step determines WHERE in the project the page will live. The user may not know the project's directory structure, so the skill must guide them.

1. Open `~/.agents/skills/my-explore/SKILL.md` to examine the project's existing route structure (scan `src/app/`, `pages/`, or equivalent).
2. Analyze the design content to infer the page type (list page, detail page, form, dashboard, etc.).
3. Suggest a module path in plain language:

> "This looks like a list page for community posts.
> Your project already has a community section. I'd put this page here:
> **Community > v1 > Post List**
>
> Does that sound right? Or should it go somewhere else?"

Behind the scenes, this maps to a framework-specific file path (e.g., `pages/community/v1/list.vue` in Vue, `src/app/(protected)/community/v1/list/page.tsx` in Next.js). The user only sees the human-readable description.

4. User confirms or suggests a different placement (e.g., "No, this is for the feedback section").
5. Once confirmed, derive:
   - The file path for the page
   - The spec directory: `specs/{area}/v{n}/`
   - The URL path the user will visit

### Step 1.4: Generate Static Page

1. Load the project's frontend shared rules from `~/.agents/shared-rules/frontend/` based on the detected framework (Next.js, Vue, React, etc.).
2. Generate the page using:
   - The d2spec component tree markdown as the visual reference (layout, sizing, colors, typography, hierarchy)
   - The project's tech stack and conventions from shared rules
   - Mock static data for all dynamic content (hardcoded arrays, placeholder text/images)
3. Write the page file to the confirmed path.
4. Write the initial spec file to `specs/{area}/v{n}/{feature}.spec.md` with the UI section filled:

```markdown
# {Feature} Spec

## Meta
- **Area**: {area}
- **Version**: v{n}
- **Created**: {date}
- **Last Updated**: {date}
- **Design**: {design_url}

## Changelog

| Date | Type | Sections Affected | Description |
|------|------|-------------------|-------------|
| {date} | New Feature | UI | Initial UI from design mockup |

## UI

### {Section Name}
{Layout, sizing, colors, typography from d2spec}

## Interaction
(To be determined in Phase 2)

## Data
(To be determined in Phase 2)
```

### Step 1.5: Tell User How to Access

> "The page is ready. Open your browser and go to:
> **{the URL path derived in Step 1.3, on your dev server}**
>
> (Make sure your dev server is running first.)
>
> Take a look and tell me what needs to change."

### Step 1.6: Iterate Until Confirmed

The user views the page and provides feedback. Each round:

1. User describes what's wrong in their own words (e.g., "the cards should be wider", "the font is too small", "the color should be lighter")
2. Modify the page code to address the feedback
3. Update the spec's UI section to reflect the change
4. Ask the user to refresh and check again

Repeat until the user says the UI is correct.

> When the user confirms, respond:
> "Great, the UI is locked in. Now let's talk about what happens when someone uses this page — what each button does, where things link to, and where the data comes from."

---

## Phase 2: Interaction + Data Confirmation

Goal: capture all user interactions and data sources, and complete the spec.

### Step 2.1: Identify Interactive Elements

From the UI structure, identify elements that likely have interactions:
- Cards / list items (tap/click targets)
- Buttons (actions)
- Input fields (user input)
- Tabs / navigation (switching views)
- Pull-to-refresh / scroll loading (list behavior)

Do NOT enumerate every element. Focus on the high-probability ones and group related elements (2-3 per question).

### Step 2.2: Guided Discussion

Ask about interactions and data together in natural flow. Use plain language with multiple-choice options when possible.

**Static UI additions**: When an interaction reveals a new visual element (e.g., a popup, a confirmation message, an empty state), add it to the prototype page as static content so the user can see the layout immediately. Update the spec's UI section accordingly. This keeps the "show, don't describe" principle alive during Phase 2.

> "When someone taps on a post card, what should happen?
> a) Go to the post detail page
> b) Expand to show more content
> c) Something else?"

When an interaction implies data, follow up naturally:

> "Got it, tapping goes to the detail page. Where do the posts in this list come from?
> a) Your backend has an API for this
> b) The data is in a database but there's no API yet
> c) Not sure yet"

If the user mentions an API, ask for the endpoint or documentation link. Keep it simple:

> "Can you share the API address or documentation? Something like a URL or a document link."

The user can also volunteer information at any time — don't limit the conversation to the skill's questions.

### Step 2.3: Open-Ended Round

After covering the obvious interactive elements, invite the user to add anything missed:

> "Is there anything else on this page we haven't talked about? For example:
> - What happens when the list is empty?
> - Can users pull down to refresh?
> - Are there any features only logged-in users can see?"

Record everything the user mentions.

### Step 2.4: Summary and Confirmation

Present a complete summary in plain language:

> "Here's everything we've decided:
>
> **Interactions:**
> - Tap post card → go to post detail page
> - Tap + button → open new post form
> - Search box → press enter to search
> - Pull down → refresh the list
> - Scroll to bottom → load more posts
>
> **Data:**
> - Post list: from GET /api/posts (fields: title, author, date, thumbnail)
> - New post: submit to POST /api/posts (fields: title, content)
>
> Is this all correct? Anything to change or add?"

If the user wants changes → go back to discussion, update spec, re-summarize.

Repeat until the user confirms.

### Step 2.5: Finalize Spec

After confirmation, update the spec file with the complete Interaction and Data sections:

```markdown
## Interaction

### Post Card
- Tap → navigate to post detail page (/community/v1/{id})

### + Button
- Tap → open new post form (modal)

### Search Box
- Press enter → navigate to search results with query

### List
- Pull down → refresh post list
- Scroll to bottom → load next page

## Data

### Post List
- Source: GET /api/posts
- Fields: id, title, author, createdAt, thumbnail
- Pagination: cursor-based, 20 per page

### New Post
- Submit: POST /api/posts
- Fields: title (string, required), content (string, required)
```

---

## Phase 3: Next Step

Goal: let the user decide what to do with the confirmed prototype and spec.

### Step 3.1: Present Options

> "The page and spec are ready. What would you like to do next?
>
> 1. **Next** — Move on to something else
> 2. **Refactor** — Clean up the current page code to meet coding standards
> 3. **Implement with review** — I'll analyze the spec and walk you through the implementation plan before writing production code
> 4. **Auto-implement** — I'll build the production version automatically with tests and error handling"

Wait for user selection. Do NOT proceed without a selection.

### Step 3.2: Dispatch

- **Next** → End this skill. Return control to the main conversation.
- **Refactor** → Open `~/.agents/skills/refactor/SKILL.md`, passing the prototype file path.
- **Implement with review** → Open `~/.agents/skills/understand/SKILL.md`, passing the spec file path as `requirement_source`.
- **Auto-implement** → Chain `~/.agents/skills/understand/SKILL.md` in `prepare-only` mode with the spec file path as `requirement_source`, then run `~/.agents/skills/auto-tdd/SKILL.md` only if `hld.md` exists in the resulting `procedure_dir`.

---

## Communication Rules

These rules apply to **user-facing messages** throughout all phases. The spec file and code are technical documents — they use proper technical terms for downstream consumption by other skills.

1. **Plain language in conversation** — when speaking to the user, never use: "component", "hook", "state", "prop", "API endpoint", "route", "render", "mount". Instead say: "page", "section", "button behavior", "data source", "web address", "show", "appear". Exception: if the user introduces a technical term themselves, you may echo it back.
2. **Multiple choice when possible** — give options (a/b/c) rather than open-ended questions. Include "Something else?" as the last option.
3. **One topic at a time** — ask 2-3 related questions per message, not 8.
4. **Summarize before moving on** — at each phase transition, show what was decided and get confirmation.
5. **User can always go back** — if the user changes their mind about a Phase 1 decision during Phase 2, accommodate it. Update the spec and code accordingly.
6. **Show, don't describe** — whenever possible, make the change and tell the user to refresh, rather than describing what the change will look like.
