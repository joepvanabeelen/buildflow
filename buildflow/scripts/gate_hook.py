#!/usr/bin/env python3
"""buildflow Stop/StopFailure hook.

Stop: the orchestrator may not end its turn while a checkpoint has open gates.
StopFailure: the turn ended on an API error (rate limit etc.); record it as an interruption.
A later normal Stop means the session works again: open interruptions are marked resumed, and
gates still marked interrupted are pointed out (`bf.py resume`) so the run and viewer are correct.

Registered from the skill's frontmatter, so it stays active for the rest of the session.
It is a no-op unless the project has an active buildflow run in phase `building`.
It also registers the session id on the run, which is what makes cost measurement work.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bf  # noqa: E402

MAX_BLOCKS_WITHOUT_PROGRESS = 4
MAX_RESUME_NUDGES = 2  # blocks that only ask to settle interrupted gates while background work runs


def main():
    try:
        inp = json.load(sys.stdin)
    except ValueError:
        return 0
    cwd = inp.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    root = bf.find_root(cwd)
    st = bf.load(root, required=False)
    if not st:
        return 0

    changed = False
    sid = inp.get("session_id")
    if sid and sid not in st.get("sessions", []):
        st.setdefault("sessions", []).append(sid)
        changed = True

    # the turn died on an API error (rate limit, overload, ...): log it and close running attempts.
    # Claude Code ignores StopFailure output, so there is nothing to block here.
    if inp.get("hook_event_name") == "StopFailure":
        if st.get("phase") != "done":
            bf.record_interruption(st, inp.get("error") or "unknown", inp.get("error_details") or "")
            changed = True
        if changed:
            bf.save(root, st, resume=False)
        return 0

    # a normal Stop after an interruption: the session is working again
    if bf.resume_interruptions(st, "auto", "stop hook"):
        changed = True

    work = bf.open_work(st)
    # background subagents will wake the orchestrator when they finish; let the turn end
    busy = [t for t in (inp.get("background_tasks") or []) if t.get("status") in (None, "running", "pending")]
    stuck = bf.interrupted_gates(st)
    if busy and stuck:
        # the subagents kept working through the error; the state still says interrupted. Ask once or twice
        # to fix that (it is one command), then let the turn end so the background work can wake us.
        key = ",".join(f"{c['id']}:{g}" for c, g in stuck)
        rg = st.get("resume_guard") or {}
        rg = {"key": key, "count": rg.get("count", 0) + 1} if rg.get("key") == key else {"key": key, "count": 1}
        st["resume_guard"] = rg
        bf.save(root, st, render=changed, resume=False)
        if rg["count"] <= MAX_RESUME_NUDGES:
            print(json.dumps({"decision": "block", "reason":
                  f"buildflow: gate(s) {key} are still marked interrupted while background work runs. If their subagent "
                  f"is one of the running tasks, run `bf.py resume --running {stuck[0][0]['id']}:{stuck[0][1]}` (one per gate) "
                  f"so the run and the viewer show it running again; if it is gone, `bf.py resume --redo <cp:gate>`. "
                  f"Then end your turn and wait for the background work."}))
        return 0
    if not work or busy:
        if st.get("hook_guard"):
            st.pop("hook_guard")
            changed = True
        if changed:
            bf.save(root, st, render=True, resume=False)
        return 0

    # messages the human sent from the live viewer (bf serve) that nobody has handled yet
    inbox = bf.inbox_unhandled(root, st["slug"])

    # progress guard: if the state has not moved since the last block, stop blocking after a few tries.
    # Handling a viewer message counts as progress; a message arriving does too, since it is new work.
    fingerprint = hashlib.sha1((st["phase"] + json.dumps(st["checkpoints"], sort_keys=True)
                                + ",".join(x["id"] for x in inbox)).encode()).hexdigest()
    guard = st.get("hook_guard") or {}
    if guard.get("fingerprint") == fingerprint:
        guard["count"] = guard.get("count", 0) + 1
    else:
        guard = {"fingerprint": fingerprint, "count": 1}
    st["hook_guard"] = guard
    bf.save(root, st, render=changed, resume=False)
    if guard["count"] > MAX_BLOCKS_WITHOUT_PROGRESS:
        print(json.dumps({"systemMessage": bf.t("hook_gave_up", st)}))
        return 0

    reason = ("buildflow: gates are still open, so the work is not done.\n"
              + "\n".join(f"- {w}" for w in work[:6])
              + f"\nNext: {bf.next_action(st)}\n"
              "Keep going. Only stop when a gate genuinely needs a human: then run "
              "`bf.py pause --reason \"...\"` first and ask your question.")
    if inbox:
        reason += (f"\n\nThe human sent {len(inbox)} message(s) from the viewer:\n"
                   + "\n".join(f"- [{x['id']}] {x.get('type')} · {x.get('stage') or '-'}"
                               + (f" · {x['target']}" if x.get("target") else "")
                               + (f": {x['text'][:200]}" if x.get("text") else "") for x in inbox[:6])
                   + "\nRun `bf.py inbox`, handle them (feedback at the next checkpoint boundary unless it asks "
                   "you to stop), then `bf.py inbox handled <id> --note \"...\"`.")
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
