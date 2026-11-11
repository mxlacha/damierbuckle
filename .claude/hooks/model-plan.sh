#!/usr/bin/env bash
# UserPromptSubmit hook: for non-trivial requests, tell Claude to recommend a
# model and present an execution plan for approval BEFORE doing any work.
# Trivial prompts (short, question-like, slash commands) pass through silently.
#
# Disable temporarily:  CLAUDE_MODEL_PLAN=off   (env var)

[ "${CLAUDE_MODEL_PLAN:-on}" = "off" ] && exit 0
command -v jq >/dev/null 2>&1 || exit 0

prompt=$(jq -r '.prompt // ""' 2>/dev/null)
trimmed=$(printf '%s' "$prompt" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
[ -z "$trimmed" ] && exit 0

# Slash commands and shell escapes are never planned.
case "$trimmed" in /*|!*) exit 0 ;; esac

words=$(printf '%s' "$trimmed" | wc -w | tr -d ' ')

# Very short prompts: greetings, "yes", "go ahead", "thanks", approvals of a plan.
[ "$words" -le 6 ] && exit 0

# Short plain questions with no work verb: just answer them.
action='(build|implement|create|refactor|rewrite|write|add|fix|migrate|set ?up|design|deploy|integrate|generate|update|change|make|convert|remove|delete|install|configure|schedule|draft|send)'
if printf '%s' "$trimmed" | grep -q '?[[:space:]]*$' \
   && [ "$words" -le 25 ] \
   && ! printf '%s' "$trimmed" | grep -qiE "\b$action\b"; then
  exit 0
fi

read -r -d '' ctx <<'MSG'
[model-plan hook] The user wants every non-trivial request to start with a model recommendation and an execution plan, approved before any work begins.

First decide whether this request is trivial. SKIP everything below and just answer/do it if ANY of these hold:
  - it is a simple question or lookup you can answer directly,
  - it is a small, obvious, single-step task,
  - it repeats a task already done earlier in this conversation or recorded in memory, or it is a direct follow-up/approval of a plan you already presented.
When skipping, do not mention this hook.

Otherwise, BEFORE using any tool that changes anything (Edit, Write, Bash writes, git, calendar/email/Drive writes, etc.):
1. Recommend a model, one line each for the pick and why:
     - Haiku 5.5  (claude-haiku-5-5)  : quick, mechanical, high-volume work
     - Sonnet 5.5 (claude-sonnet-5-5) : default for most coding, writing, and tool-driven tasks
     - Opus 5.5   (claude-opus-5-5)   : multi-file changes, tricky debugging, careful analysis
     - Fable 5.2  (claude-fable-5-2)  : hardest/most open-ended problems, deep research, architecture
   Include a suggested effort level (low / medium / high / xhigh) if it matters. Note whether the current session model is already a good fit. You cannot switch your own model mid-turn; if a change is warranted, tell the user to run /model <name> (and /effort if relevant).
2. Present a short numbered plan of execution: the steps, which files/tools/connectors you will touch, what could go wrong, and how you will verify the result. Keep it tight (about 3-8 steps).
3. Ask for a go-ahead with AskUserQuestion (options like "Proceed with current model", "I'll switch models first", "Change the plan"), then STOP and wait for the answer. Read-only research needed to write the plan is fine.
MSG

jq -n --arg ctx "$ctx" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$ctx}}'
