# Recovery: interruptions, resuming, model escalation

Read this only when you actually hit one of these cases — not as routine background.

## Interruptions

A rate limit/API error skips the Stop hook; `StopFailure` records the interruption and
marks running gate attempts `interrupted`. A crash leaves no trace — check yourself.
Whenever you wake up after one: `bf status` first.

- Gate `interrupted`, subagent still running or finished: `bf resume --running cpNN:gate`
  (continues the same attempt). Subagent gone: `bf resume --redo cpNN:gate` (fresh one).
  Never record a result you didn't see.
- Gate `running` while you know the session broke off: `bf interrupted cpNN gate --reason
  "..."`, then redo the step.
- New session: `bf session ${CLAUDE_SESSION_ID}` (the Stop hook also does this at the end
  of your first turn).

An interruption is not a pause: the run stays in its phase, the viewer shows a notice
("interrupted at 14:32 (rate limit)"), and the next state change marks it resumed.

Time is measured from transcript activity; silence over 10 minutes
(`BUILDFLOW_IDLE_GAP_MIN`) counts as idle, not build time, and waiting phases count as
waiting on the human. You don't need to pause the run for a rate limit to keep the
numbers honest. `bf cost` reports the split.

## Model escalation

When the implementer has failed the same gate twice in a checkpoint, `bf model implement
--cp cpNN` returns `inherit` for the next attempt (it counts failed attempts on the
behavior/build gate; pass `--gate` for another one). Record every failed attempt with
`bf gate ... failed` so this works. Runs created before profiles existed count as
`thorough`.
