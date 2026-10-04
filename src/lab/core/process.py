"""Running one command under supervision: output teed to a log (and the terminal unless quiet).

Signals: the command runs in its own process group, so a shell wrapper and everything it starts stop
together. Ctrl-C, SIGTERM and SIGHUP sent to lab are forwarded to that group; lab keeps draining the
output while it shuts down, and a second signal kills the group. Any of these ends the run as KILLED.
The command gets no terminal input (stdin is /dev/null): a background group reading it would stop.
"""

import contextlib
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .model import Status

EXIT_CANNOT_START = 127
FORWARDED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


@dataclass(frozen=True)
class Outcome:
    status: Status
    exit_code: int
    seconds: float


def run(command: list[str], cwd: Path, env: dict[str, str], log_path: Path, quiet: bool = False) -> Outcome:
    started = time.monotonic()
    with open(log_path, "wb") as log:
        try:
            child = subprocess.Popen(
                command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, process_group=0,
            )  # fmt: skip
        except OSError as error:
            message = f"lab: could not start {command[0]!r}: {error}\n".encode()
            log.write(message)
            sys.stderr.buffer.write(message)
            sys.stderr.flush()  # before the result line that follows on stdout
            return Outcome(Status.FAILED, EXIT_CANNOT_START, time.monotonic() - started)

        stopped = False

        def forward(signum, _frame):
            nonlocal stopped
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL if stopped else signum)
            stopped = True

        previous = {s: signal.signal(s, forward) for s in FORWARDED}
        try:
            _drain(child, log, echo=not quiet)
            code = child.wait()
        finally:
            for s, handler in previous.items():
                signal.signal(s, handler)
    status = Status.KILLED if stopped else Status.OK if code == 0 else Status.FAILED
    return Outcome(status, 128 - code if code < 0 else code, time.monotonic() - started)  # killed by N: 128 + N


def _drain(child: subprocess.Popen, log, echo: bool) -> None:
    for chunk in iter(lambda: child.stdout.read1(65536), b""):
        log.write(chunk)
        if echo:
            try:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            except BrokenPipeError:  # `lab run ... | head` closed early: the run goes on, logged
                echo = False
