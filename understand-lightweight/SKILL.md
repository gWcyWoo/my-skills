---
name: understand-lightweight
description: Lightweight understanding based on already-explored code. Identify the gap between requirement and current state, discuss with user until clear, output confirmed result.
---

# Lightweight Understanding

Explore code, understand the gap, discuss until clear, confirm the result.

## Step 1: Explore

Read the user's requirement (spec, ticket, or message) first. Then read and follow `my-explore/SKILL.md` to navigate the codebase — pass the requirement context so exploration has a clear search target.

## Step 2: Understand the Gap

Based on the exploration results and the user's requirement, think through:

**Bug fix:** What is the user reporting? What does the code actually do? Where is the root cause? How should it be fixed?

**New feature / change:** What does the user want? What does the code currently look like? What is the gap between the two? How should it be implemented?

## Step 3: Discuss

If anything is unclear — ask. Do not guess, do not assume.

This is a conversation, not a one-shot output. Go back and forth with the user until both sides are clear on:
- What the problem or requirement is
- How to solve or implement it

## Step 4: Confirm

When the understanding is clear, present the confirmed result:

**Bug fix →** root cause + fix approach

**New feature →** design approach + what to change

**STOP and wait for user to confirm.** Do NOT proceed until confirmed.
