"""Verify scoring against real files while replacing only the Codex process."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evaluate


class FakeCodex:
    returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0


class EvaluationTests(unittest.TestCase):
    def trial(self, task, fix=False, read=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".local/fixtures").mkdir(parents=True)

            def launch(cmd, stdout, **kwargs):
                fixture = Path(cmd[cmd.index("-C") + 1])
                final = Path(cmd[cmd.index("-o") + 1])
                if task == "read":
                    nonce = (fixture / "proof.txt").read_text().strip()
                    final.write_text(nonce)
                    if read:
                        stdout.write(
                            json.dumps(
                                {
                                    "type": "item.completed",
                                    "item": {
                                        "type": "command_execution",
                                        "exit_code": 0,
                                        "command": "cat proof.txt",
                                        "aggregated_output": nonce,
                                    },
                                }
                            )
                            + "\n"
                        )
                elif fix:
                    (fixture / "ranges.py").write_text(
                        "def inclusive_range(a,b):\n    return list(range(a,b+1))\n"
                    )
                return FakeCodex()

            with (
                patch.object(evaluate, "ROOT", root),
                patch.object(evaluate, "codex_flags", return_value=[]),
                patch.object(evaluate, "codex_config", return_value=root),
                patch.object(evaluate.subprocess, "Popen", side_effect=launch),
            ):
                # subprocess.run used by the external edit checker needs the real Popen.
                real_run = __import__("subprocess").run
                original_popen = POPEN

                def checker(*args, **kwargs):
                    with patch.object(evaluate.subprocess, "Popen", original_popen):
                        return real_run(*args, **kwargs)

                with patch.object(evaluate.subprocess, "run", side_effect=checker):
                    return evaluate.evaluate(task, root / "result")

    def test_correct_text_without_file_read_fails(self):
        self.assertFalse(self.trial("read")["passed"])

    def test_actual_read_and_exact_answer_passes(self):
        self.assertTrue(self.trial("read", read=True)["passed"])

    def test_original_bug_fails_external_checker(self):
        self.assertFalse(self.trial("edit")["passed"])

    def test_fixed_function_passes_external_checker(self):
        self.assertTrue(self.trial("edit", fix=True)["passed"])


POPEN = evaluate.subprocess.Popen
