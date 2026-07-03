---
name: diagnose-process
description: Diagnose the running PROCESS (and scheduled triggers) before touching files. Use when a tool/CLI is broken/flaky after an update, "I deleted it but it came back" (an artifact keeps regenerating), "it still says X after I fixed it", "can't launch a new session/instance", or something can't start because a lock is held. Rules out mundane causes first; asks before killing or deleting.
---

# diagnose-process

A tool looks broken and the obvious move is to fix the *files* — re-delete the stray
package, re-edit the config, re-run the installer. That's how you lose 90 minutes. When a
cleaned-up artifact keeps coming back, the cause is something **writing** it — a running
process, or a scheduled/event trigger — and until you find the writer you're playing
whack-a-mole. Find the writer first; touch files second.

**But rule out the boring causes first.** Most "broke after an update" is mundane: a shim or
PATH entry pointing at the wrong version, a stale cache, a changed default, a half-downloaded
binary. Check the *resolved* binary's version and the changelog before any process forensics —
five minutes here often closes it. The process hunt below is for when that doesn't.

**Cardinal rule: find the writer before you delete the file.** Re-deleting a regenerating
artifact without identifying what re-creates it is whack-a-mole — and the loop will outlast
your patience.

> Platform note: the commands below assume **Linux / procfs**. On macOS there's no `/proc`
> and `ps`/`lsof` flags differ; in a container, PIDs and mounts are namespaced and the writer
> may live on the host. Adapt accordingly.

## The checklist (run in order, mostly read-only)

1. **Identify the binary that's actually running.**
   `readlink /proc/$$/exe`; then for the tool: `ps -eo pid,ppid,etime,cmd | grep -i <tool> | grep -v grep`
   and `readlink /proc/<pid>/exe` for each hit. Don't trust `which` alone — a long-lived
   process can be running something else entirely.

2. **Treat a `(deleted)` exe as the prime suspect.** If `readlink /proc/<pid>/exe` ends in
   `(deleted)`, a live process is running code that no longer exists on disk — the textbook
   signature of a ghost re-creating state. Resolve *this* process before anything else.

3. **When an artifact reappears, find its writer — not the file.** `lsof <path>` (or reason
   about which live PID owns it). Re-delete only after the writer is dead.

4. **If no live writer holds it, hunt the scheduled / event-driven one.** A regenerator that
   isn't running *at the moment you look* shows nothing in `ps`/`lsof` — this is the dominant
   false-negative. Check: `systemctl list-timers`, `systemctl list-units --type=path`,
   `crontab -l` and `/etc/cron*`, file-watchers / sync daemons (Syncthing, Dropbox), and
   package post-install hooks. "Nothing running" is *not* "no writer" until you've cleared these.

5. **Read lock files for their owner.** `cat <path>.lock` → PID → walk ancestry with
   `ps -p <pid> -o ppid=,cmd=` up to PID 1. A held lock explains "can't start a new instance."

6. **Read the user's own config comments first.** `.bashrc`, dotfiles, and inline notes often
   document the exact failure mode and the defenses already in place. The answer is frequently
   already written down.

7. **Separate symptom from cause; verify the loop is actually broken.** Don't hand back on an
   instant re-check or "open a fresh terminal" — that passes simply because the trigger hasn't
   fired yet, giving a false all-clear. Either **disable/kill the identified trigger** (process,
   timer, unit, watcher), or **wait through one trigger interval**, *then* confirm the artifact
   stays gone.

8. **Don't assume the obvious daemon.** Before declaring anything safe to kill, verify the real
   service. "SSH access" may be Tailscale SSH (`tailscaled`), not `sshd`; the access path may be
   tmux over a VPN. Check what's actually listening and how the user is connected.

## Boundaries

- **Read-only by default.** Steps 1–6 and 8 mutate nothing — run them freely.
- **Ask before killing or deleting.** Surface what you found (the PID or trigger, its exe, its
  ancestry, what it's re-creating) and get an explicit go before `kill` or `rm`. After killing,
  re-verify the loop is broken (step 7) and that unrelated daemons/sessions survived.
- **Establish topology once, up front:** which binary runs, where it lives, install metadata vs.
  reality, PATH order, live processes *and* scheduled triggers. Five minutes here replaces an
  hour of guessing.
