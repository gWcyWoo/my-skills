---
name: selfcheck-testcase-code
description: Execute a zero-trust, exhaustive audit on generated test code. Enforces the 1-Mock rule, behavioral observability, and unconditional remediation.
---

# Test Code Audit Workflow (L7 Architecture-Locked)

## Step 1: Orchestrate Codex Audit
Do not perform a manual review. You MUST orchestrate the `codex` skill to execute a "Zero-Trust" audit against the L7 mandates.

1. **Construct Audit Prompt**:
    - **Context**: Load `~/.claude/protocols/testcase-code-review-prompt.md`.
    - **Payload**: Inject the generated test code, the 3-way traceability plan, and the HLD output.
2. **Invoke Skill**:
    - **Skill**: `codex`
    - **Arguments**: 
        - `prompt`: [The constructed exhaustive audit string]
        - `sandbox`: `read-only`

## Step 2: Unconditional Remediation & Verification
If the audit returns violations, adhere to the following strict remediation protocol:

- **UNCONDITIONAL FIX**: You MUST unconditionally fix ALL identified issues until Zero (0) issues remain.
- **SELF-VERIFICATION CHECKLIST**: After remediation, you MUST output a verification table proving every violation ID has been neutralized with code evidence:

| Violation ID | Remediation Action Taken | Self-Verification Proof (Code Evidence) | Status |
|:---|:---|:---|:---|
| [ID] | [Explicit description of the fix] | [Reference specific line/logic change] | ✅ FIXED |

- **INTEGRITY CHECK**: Ensure that fixing a "Mock Overflow" (> 1 mock) did not break the "Behavioral Side-Effect" assertion.

## Step 3: The Architect's Gate (STOP)
After selfcheck passes and the checklist is presented, you MUST stop and wait for explicit confirmation.

**STOP HERE — HARD GATE.**
Your response MUST end with exactly this line and nothing else after it:
> **Please confirm the test code before I proceed to Implementation.**

🚫 **CRITICAL RESTRAINT**: 
- Do NOT read files, do NOT load coding standards, and do NOT call any tool after outputting the gate line.
- If you find yourself about to call Read, Edit, or any other tool in the same response — you have violated this gate.
- If the user provides feedback or modifications, you MUST integrate them into the test code and re-run this selfcheck before asking again.
