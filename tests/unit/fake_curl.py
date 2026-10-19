"""A stand-in for Spruce's curl: answers from a plan and records its arguments.

Each run appends its arguments to ``calls.json`` and replays the next step of ``plan.json``
(the last step repeats): ``stdout``, ``stderr``, an exit ``code`` and an optional ``sleep``.
``answer()`` builds a step with the ``--write-out`` the transport asks for.
"""

from __future__ import annotations

import json
import sys

FAKE_CURL = """\
import json, sys, time
from pathlib import Path

here = Path(__file__).parent
calls = json.loads((here / "calls.json").read_text())
calls.append(sys.argv[1:])
(here / "calls.json").write_text(json.dumps(calls))
plan = json.loads((here / "plan.json").read_text())
step = plan[min(len(calls), len(plan)) - 1]
time.sleep(step.get("sleep", 0))
sys.stdout.write(step.get("stdout", ""))
sys.stderr.write(step.get("stderr", ""))
sys.exit(step.get("code", 0))
"""


class Curl:
    """A fake curl that answers from a plan and records its arguments."""

    def __init__(self, directory):
        self.directory = directory
        self.path = directory / "curl"
        self.path.write_text(f"#!{sys.executable}\n{FAKE_CURL}")
        self.path.chmod(0o755)
        (directory / "calls.json").write_text("[]")
        self.plan()

    def plan(self, *steps):
        (self.directory / "plan.json").write_text(json.dumps(list(steps)))

    @property
    def calls(self):
        return json.loads((self.directory / "calls.json").read_text())

    @property
    def urls(self):
        return [call[-1] for call in self.calls]


def answer(body, status=200, date=""):
    """Build a step answering ``body`` with ``--write-out``'s status and Date lines."""
    return {"stdout": f"{body}\n{status}\n{date}"}
