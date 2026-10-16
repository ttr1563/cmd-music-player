"""Exercise the PR job against a fake GitHub CLI; no network or credentials."""

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/create-maintenance-pr.yml"
SHA = "a" * 40
MOCK_GH = """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

root = Path(os.environ['MOCK_ROOT'])
state = json.loads((root / 'state.json').read_text())
args = sys.argv[1:]
with (root / 'calls.jsonl').open('a') as output:
    output.write(json.dumps(args) + '\\n')
if state.get('fail'):
    raise SystemExit(1)
if args[:2] == ['pr', 'list']:
    print(json.dumps(state['pulls']))
elif args[:2] == ['pr', 'create']:
    body = Path(args[args.index('--body-file') + 1]).read_text()
    (root / 'created.json').write_text(json.dumps({'args': args, 'body': body}))
    print('https://github.com/example/repository/pull/1')
elif args[0] == 'api':
    path = args[1]
    if '/git/ref/heads/' in path:
        print(state['current'])
    elif '/compare/' in path:
        print(state['ahead'])
    elif '/commits/' in path:
        print(state['message'])
    else:
        print('true' if state['private'] else 'false')
else:
    raise SystemExit('Unexpected CLI command')
"""


@unittest.skipIf(os.name == "nt", "The Actions job uses Linux bash and jq")
class MaintenancePRTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="fest-pr-job-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        command = self.root / "gh"
        command.write_text(MOCK_GH)
        command.chmod(0o755)
        self.state = {
            "private": False,
            "current": SHA,
            "pulls": [],
            "ahead": 1,
            "message": "修正内容\n\n変更理由: 不具合修正\n影響範囲: 検索\nテスト結果: 成功",
        }

    def run_job(self, branch="feature/maintenance-example"):
        (self.root / "state.json").write_text(json.dumps(self.state))
        script = textwrap.dedent(WORKFLOW.read_text().split("        run: |\n", 1)[1])
        return subprocess.run(
            ["bash", "-c", script],
            cwd=self.root,
            env=dict(
                os.environ,
                PATH=f"{self.root}:{os.environ['PATH']}",
                MOCK_ROOT=str(self.root),
                RUNNER_TEMP=str(self.root),
                GH_REPO="ttr1563/cmd-music-player",
                GH_TOKEN="synthetic-test-token",
                BRANCH=branch,
                HEAD_SHA=SHA,
                BASE="develop",
                REVIEWER="ttr1563",
            ),
            capture_output=True,
            text=True,
            timeout=10,
        )

    def created(self):
        path = self.root / "created.json"
        return json.loads(path.read_text()) if path.exists() else None

    def test_creates_reviewable_pr_without_a_checkout(self):
        result = self.run_job()
        self.assertEqual(result.returncode, 0, result.stderr)
        pr = self.created()
        self.assertEqual(pr["args"][pr["args"].index("--base") + 1], "develop")
        self.assertEqual(pr["args"][pr["args"].index("--reviewer") + 1], "ttr1563")
        self.assertIn("[feature/maintenance-example] 修正内容", pr["args"])
        self.assertIn("テスト結果: 成功", pr["body"])
        self.assertIn(SHA, pr["body"])
        calls = (self.root / "calls.jsonl").read_text()
        self.assertNotIn('"merge"', calls)
        self.assertNotIn('"review"', calls)

    def test_existing_open_pr_is_not_duplicated_or_modified(self):
        self.state["pulls"] = [{"number": 1, "state": "OPEN", "headRefOid": SHA}]
        result = self.run_job()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(self.created())

    def test_closed_pr_is_not_reopened_for_the_same_commit(self):
        self.state["pulls"] = [{"number": 1, "state": "CLOSED", "headRefOid": SHA}]
        self.assertEqual(self.run_job().returncode, 0)
        self.assertIsNone(self.created())

    def test_new_commit_can_be_proposed_after_a_closed_pr(self):
        self.state["pulls"] = [{"number": 1, "state": "CLOSED", "headRefOid": "b" * 40}]
        self.assertEqual(self.run_job().returncode, 0)
        self.assertIsNotNone(self.created())

    def test_superseded_push_is_skipped(self):
        self.state["current"] = "b" * 40
        self.assertEqual(self.run_job().returncode, 0)
        self.assertIsNone(self.created())

    def test_branch_without_changes_is_skipped(self):
        self.state["ahead"] = 0
        self.assertEqual(self.run_job().returncode, 0)
        self.assertIsNone(self.created())

    def test_api_failure_does_not_create_pr(self):
        self.state["fail"] = True
        self.assertNotEqual(self.run_job().returncode, 0)
        self.assertIsNone(self.created())

    def test_private_repository_is_rejected(self):
        self.state["private"] = True
        self.assertNotEqual(self.run_job().returncode, 0)
        self.assertIsNone(self.created())

    def test_branch_text_cannot_execute_commands(self):
        result = self.run_job("feature/maintenance-$(touch injected)")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "injected").exists())
        self.assertFalse((self.root / "calls.jsonl").exists())

    def test_commit_text_is_only_pr_content(self):
        self.state["message"] = "修正\n$(touch injected) `touch injected`"
        self.assertEqual(self.run_job().returncode, 0)
        self.assertFalse((self.root / "injected").exists())
        self.assertIn("$(touch injected)", self.created()["body"])


if __name__ == "__main__":
    unittest.main()
