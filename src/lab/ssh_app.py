"""Run an experiment script on any machine you can SSH into (a RunPod or Prime pod, Lambda, your own box).

    lab run -H "..." -- python -m lab.ssh_app --host root@203.0.113.7 --port 22042 \
        --script train.py --args "--lr 3e-4"

Copies the experiment folder, the campaign's locked/, the lab's lib/ and the lab package to
<root>/<campaign>-<run id>-<suffix> with rsync (a folder of its own, printed at the start), installs
requirements.txt if present, and starts the script there detached from the SSH session, so a dropped
connection does not stop it. Its output streams here; if SSH drops, this reconnects for up to
--reconnect-minutes. When the script ends, metrics, figures and artifacts are copied back into the run
and the folder is removed; if they cannot be copied, the folder stays and the run is marked failed.
Ctrl-C or SIGTERM here stops the script on the machine. HF_TOKEN and WANDB_API_KEY are passed in a 0600
env file, not argv, and deleted once the script has read it.
Cost is not logged: lab records only amounts a service reports.
Checkpoints: write them under --root on the machine (a network volume on RunPod), not artifacts.
`--host local` runs the same steps without SSH (for testing the path).
"""

import argparse
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from lab import run_dir
from lab.core.snapshot import SKIP_DIRS
from lab.remote import SECRETS, pack, scratch_name, shipped, unpack

PACKAGE = Path(__file__).resolve().parent
EXCLUDE = [f"--exclude={pattern}" for pattern in (".*", *SKIP_DIRS)]  # the rule snapshots use
POLL_SECONDS = 2
SSH_FAILED = 255  # ssh's own exit code when it cannot connect, or when a stalled connection is given up
MARK = b"@@lab@@"  # starts the status line of a poll, so a login shell's own output before it is skipped
RESULTS = ["--include=metrics.jsonl", "--include=figures/***", "--include=artifacts/***", "--exclude=*"]
TRIES = 3  # attempts at copying the results back


class Machine:
    def __init__(self, host: str, port: int, key: str | None):
        self.host, self.port, self.key = host, port, key
        self.local = host == "local"

    def _ssh(self) -> list[str]:
        return [
            "ssh",
            "-p",
            str(self.port),
            "-o",
            "StrictHostKeyChecking=accept-new",
            *("-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"),
            *(["-i", self.key] if self.key else []),
        ]

    def target(self, path: str) -> str:
        return path if self.local else f"{self.host}:{path}"

    def _rsync(self, *args: str, **kwargs) -> None:
        transport = [] if self.local else ["-e", shlex.join(self._ssh())]
        subprocess.run(["rsync", "-az", *transport, *args], check=True, **kwargs)

    def push(self, source: Path, dest: str) -> None:
        self.shell(f"mkdir -p {shlex.quote(dest)}")
        self._rsync("--delete", *EXCLUDE, f"{source}/", self.target(dest) + "/")

    def pull(self, source: str, dest: Path) -> None:
        self._rsync(*RESULTS, self.target(source) + "/", f"{dest}/", capture_output=True)

    def _command(self, command: str) -> list[str]:
        return ["bash", "-lc", command] if self.local else [*self._ssh(), self.host, f"bash -lc {shlex.quote(command)}"]

    def shell(self, command: str) -> int:
        return subprocess.call(self._command(command))

    def capture(self, command: str) -> subprocess.CompletedProcess:
        return subprocess.run(self._command(command), capture_output=True)


def status(machine: Machine, base: str, offset: int) -> tuple[str, bool, bytes] | None:
    """One poll: the exit code if written, whether the script's process is alive, and new output.
    None when SSH could not get through."""
    q = shlex.quote
    poll = machine.capture(
        f"printf '{MARK.decode()} %s %s\\n' \"$(cat {q(base)}/exit 2>/dev/null)\" "
        f'"$(kill -0 "$(cat {q(base)}/pid 2>/dev/null)" 2>/dev/null && echo alive || echo gone)"; '
        f"tail -c +{offset + 1} {q(base)}/out.log 2>/dev/null"
    )
    if poll.returncode == SSH_FAILED or MARK not in poll.stdout:
        return None
    line, _, output = poll.stdout[poll.stdout.index(MARK) + len(MARK) :].partition(b"\n")
    *code, state = line.decode().split()
    return (code[0] if code else ""), state == "alive", output


def follow(machine: Machine, base: str, reconnect_minutes: float) -> int:
    """Stream the detached script's output until it writes its exit code; ride out dropped connections."""
    offset, dropped_at, gone = 0, None, 0
    while True:
        poll = status(machine, base, offset)
        if poll is None:
            if dropped_at is None:
                dropped_at = time.monotonic()
                print("lab: lost the connection, retrying", file=sys.stderr)
            elif time.monotonic() - dropped_at > reconnect_minutes * 60:
                print(f"lab: no connection for {reconnect_minutes:g} min; the script may still be running in {base}",
                      file=sys.stderr)  # fmt: skip
                return SSH_FAILED
            time.sleep(POLL_SECONDS)
            continue
        dropped_at = None
        code, alive, output = poll
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
        offset += len(output)
        if code:
            return int(code)
        # The exit code is read before the process is checked, so one "gone" can be a script ending right then.
        gone = 0 if alive else gone + 1
        if gone == 2:
            print("lab: the script ended without an exit code (it could not start, or it or the machine was killed)",
                  file=sys.stderr)  # fmt: skip
            return 1
        time.sleep(POLL_SECONDS)


def copy_back(machine: Machine, base: str, here: Path) -> bool:
    """The run's metrics, figures and artifacts into the run here, retried; False when they could not be copied."""
    for attempt in range(TRIES):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                machine.pull(f"{base}/run", Path(tmp))
                unpack(pack(Path(tmp)), here)
            return True
        except subprocess.CalledProcessError as error:
            if attempt == TRIES - 1:
                print(f"lab: could not copy the results back from {machine.target(base)}/run: "
                      f"{error.stderr.decode().strip()}; copy that folder into {here}", file=sys.stderr)  # fmt: skip
            else:
                time.sleep(POLL_SECONDS * 2)
    return False


def stop(_signum, _frame):
    raise KeyboardInterrupt


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", required=True, help="user@host, or 'local'")
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--key", help="ssh identity file")
    p.add_argument(
        "--root", default="lab-work", help="working directory on the machine (relative to home, or absolute)"
    )
    p.add_argument("--script", default="train.py")
    p.add_argument("--args", default="")
    p.add_argument("--python", default="python3")
    p.add_argument("--no-setup", action="store_true", help="skip pip install -r requirements.txt")
    p.add_argument("--reconnect-minutes", type=float, default=30, help="how long to retry a dropped connection")
    a = p.parse_args()
    for signum in (signal.SIGTERM, signal.SIGHUP):  # lab forwards these to stop a run: stop the remote script too
        signal.signal(signum, stop)

    here = run_dir()
    run_id = here.name if here else "manual"
    machine = Machine(a.host, a.port, a.key)
    if any(c.isspace() for c in a.root):
        raise SystemExit("lab: --root cannot contain spaces (rsync splits remote paths at them)")
    root = str(Path.home() / a.root) if machine.local else a.root  # ssh resolves it from home too
    base = f"{root.rstrip('/')}/{scratch_name(run_id)}"
    print(f"lab: working in {machine.target(base)}", file=sys.stderr)
    q = shlex.quote

    machine.push(Path.cwd(), f"{base}/exp")
    machine.push(PACKAGE, f"{base}/pkg/lab")
    for source, name in shipped():
        machine.push(source, f"{base}/{name}")

    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp) / "env"
        env_file.write_text("".join(f"export {k}={q(os.environ[k])}\n" for k in SECRETS if os.environ.get(k)))
        env_file.chmod(0o600)
        machine.push(Path(tmp), f"{base}/secrets")

    python = shlex.join(shlex.split(a.python))  # "uv run python" is three words
    setup = "" if a.no_setup else f"[ -f requirements.txt ] && {python} -m pip install -q -r requirements.txt; "
    script = (
        f"{setup}mkdir -p ../run && . ../secrets/env && rm -rf ../secrets && "
        f'export LAB_RUN_DIR="$(cd ../run && pwd)" LAB_RUN_ID={q(run_id)} LAB_LOCKED_DIR="$(cd .. && pwd)/locked" '
        f'PYTHONPATH="$(cd .. && pwd)/pkg:$(cd .. && pwd)/lib${{PYTHONPATH:+:$PYTHONPATH}}" PYTHONUNBUFFERED=1 && '
        f"{python} {q(a.script)} {shlex.join(shlex.split(a.args))}; echo $? > ../exit"
    )
    # A new session (os.setsid, portable where `setsid` is not) survives the SSH connection and is one group to stop.
    detach = "import os, sys; os.setsid(); os.execvp('bash', ['bash', '-c', sys.argv[1]])"
    launch = (
        f"cd {q(base)}/exp && rm -f ../exit && "
        f"{{ nohup {python} -c {q(detach)} {q(script)} > ../out.log 2>&1 < /dev/null & echo $! > ../pid; }}"
    )
    code = 1
    try:
        if machine.shell(launch) != 0:
            raise SystemExit("lab: could not start the script on the machine")
        code = follow(machine, base, a.reconnect_minutes)
    except KeyboardInterrupt:
        # Stop the group, then give it a moment, so what its SIGTERM handler logs is copied back too.
        machine.shell(f"kill -TERM -- -$(cat {q(base)}/pid) 2>/dev/null; for _ in 1 2 3 4 5; do "
                      f"kill -0 $(cat {q(base)}/pid) 2>/dev/null || break; sleep 1; done")  # fmt: skip
        print(f"lab: stopped the script on {a.host}", file=sys.stderr)
        code = 130
    finally:  # even after Ctrl-C: no token left on the machine, and results recorded
        machine.shell(f"rm -rf {q(base)}/secrets")
        copied = here is None or copy_back(machine, base, here)
        if copied and code != SSH_FAILED:  # an unreachable machine keeps its folder; so do uncopied results
            machine.shell(f"rm -rf {q(base)}")
        elif not copied and code == 0:
            code = 1  # the script ended well, but its results are not in the run
    return code


if __name__ == "__main__":
    sys.exit(main())
