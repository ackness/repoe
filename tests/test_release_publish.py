"""Offline tests for RePoE.release.publish: staging, SHA256SUMS, sequence numbers, preflight, release body."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from unittest import mock
import zipfile

from RePoE.release.pins import encoded, pin
from RePoE.release import build, publish

TARGET = {"game": "poe2", "game_patch": "9.9", "realm": "international"}
COMMIT = "c" * 40
CONTRACT = {"repository": "ackness/pobr", "version": 1, "tag": "contract/1.0", "commit": "d" * 40}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout.decode()


class StageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.build_dir = self.root / "build"
        self.build_dir.mkdir()
        build.write_zip(self.build_dir / "game-build-part.zip", {"manifest.json": b"{}\n", "data/a.json": b"[]\n"})
        self.receipt = {
            "schema": build.RECEIPT,
            "target": TARGET,
            "producer": {"repository": "ackness/repoe", "commit": COMMIT, "dirty": False, "contract": CONTRACT},
            "summary": {"generated-identical": 2, "frozen": 1, "passthrough-identical": 1},
            "provenance": {"generated": 2, "passthrough": 1, "frozen": 1},
            "reference": {"package": "previous", "members_identical": True},
        }
        self.write_build()

    def tearDown(self):
        self.temporary.cleanup()

    def write_build(self, receipt=None, described=None):
        receipt = dict(receipt or self.receipt)
        receipt.setdefault("package", described or build.file_pin(self.build_dir / "game-build-part.zip"))
        receipt_raw = encoded(receipt)
        (self.build_dir / "receipt.json").write_bytes(receipt_raw)
        package = {
            "schema": build.PACKAGE,
            "target": TARGET,
            "receipt": {"path": "receipt.json", **pin(receipt_raw)},
            "manifest": {"class": "retained-reference-manifest", **pin(b"{}\n")},
            "package": {
                "path": "game-build-part.zip",
                **build.file_pin(self.build_dir / "game-build-part.zip"),
                "identical_to_reference": True,
            },
        }
        (self.build_dir / "package.json").write_bytes(encoded(package))

    def test_stages_the_three_assets_under_their_release_names(self):
        staged = publish.stage(self.build_dir, self.root / "stage")
        assets = self.root / "stage" / "assets"
        self.assertEqual(sorted(p.name for p in assets.iterdir()), ["SHA256SUMS", "pobr-game-9.9.zip", "receipt.json"])
        self.assertEqual(list(staged["assets"]), ["SHA256SUMS", "pobr-game-9.9.zip", "receipt.json"])
        zip_raw = (self.build_dir / "game-build-part.zip").read_bytes()
        self.assertEqual((assets / "pobr-game-9.9.zip").read_bytes(), zip_raw)
        self.assertEqual((assets / "receipt.json").read_bytes(), (self.build_dir / "receipt.json").read_bytes())
        receipt_sha = hashlib.sha256((assets / "receipt.json").read_bytes()).hexdigest()
        self.assertEqual(
            (assets / "SHA256SUMS").read_text(),
            f"{hashlib.sha256(zip_raw).hexdigest()}  pobr-game-9.9.zip\n{receipt_sha}  receipt.json\n",
        )
        for name in ("pobr-game-9.9.zip", "receipt.json"):
            self.assertEqual(staged["assets"][name], build.file_pin(assets / name))

    def test_sha256sums_is_gnu_format_sorted_by_name(self):
        text = publish.sha256sums({"z.zip": "1" * 64, "a.json": "2" * 64})
        self.assertEqual(text, f"{'2' * 64}  a.json\n{'1' * 64}  z.zip\n")
        # The output checks with sha256sum -c.
        staged = publish.stage(self.build_dir, self.root / "stage")
        result = subprocess.run(
            ["sha256sum", "--check", "--strict", "SHA256SUMS"],
            cwd=staged["directory"] / "assets",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_staging_rejects_a_build_that_does_not_match_its_package_pins(self):
        (self.build_dir / "receipt.json").write_bytes(b"{}\n")
        with self.assertRaisesRegex(ValueError, "receipt.json differs"):
            publish.stage(self.build_dir, self.root / "stage")
        self.write_build()
        with zipfile.ZipFile(self.build_dir / "game-build-part.zip", "a") as archive:
            archive.writestr("extra.json", b"{}")
        with self.assertRaisesRegex(ValueError, "differs from package.json"):
            publish.stage(self.build_dir, self.root / "stage")
        # package.json repinned to the new zip, but the receipt still describes the old one (a stale --reuse).
        self.write_build(described={"bytes": 1, "sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "receipt.json does not pin this zip"):
            publish.stage(self.build_dir, self.root / "stage")

    def test_staging_requires_the_contract_in_the_receipt(self):
        producer = {k: v for k, v in self.receipt["producer"].items() if k != "contract"}
        self.write_build({**self.receipt, "producer": producer})
        with self.assertRaisesRegex(ValueError, "PoBR contract"):
            publish.stage(self.build_dir, self.root / "stage")
        # A local PoBR checkout still stages (a dry run shows the assets); main() refuses to publish it.
        local = {**CONTRACT, "tag": None, "commit": None, "local": ["pobr-data"]}
        self.write_build({**self.receipt, "producer": {**self.receipt["producer"], "contract": local}})
        self.assertIn("pobr-game-9.9.zip", publish.stage(self.build_dir, self.root / "stage")["assets"])

    def test_staging_replaces_only_its_own_directory(self):
        foreign = self.root / "foreign"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("x")
        with self.assertRaisesRegex(ValueError, "non-publish directory"):
            publish.stage(self.build_dir, foreign)
        publish.stage(self.build_dir, self.root / "stage")
        publish.stage(self.build_dir, self.root / "stage")  # its own: replaced

    def test_release_body(self):
        staged = publish.stage(self.build_dir, self.root / "stage")
        body = publish.release_body(staged, "game/9.9-3", 3)
        zip_pin = staged["assets"]["pobr-game-9.9.zip"]
        for expected in (
            "poe2 9.9 (international), sequence 3",
            f"`ackness/repoe@{COMMIT}` (the commit `game/9.9-3` names)",
            "`pobr_data::CONTRACT_VERSION` 1, built against `ackness/pobr` `contract/1.0`",
            f"{zip_pin['bytes']} bytes, SHA-256 `{zip_pin['sha256']}`",
            "Members: 2 generated, 1 passthrough, 1 frozen; root manifest: retained-reference-manifest",
            "Classes: frozen 1, generated-identical 2, passthrough-identical 1",
            "`mise run data:bump ackness/repoe game/9.9-3`",
        ):
            self.assertIn(expected, body)
        self.assertEqual(body, publish.release_body(staged, "game/9.9-3", 3))
        message = publish.tag_message(staged, "game/9.9-3")
        self.assertIn(f"{zip_pin['sha256']}  pobr-game-9.9.zip\n", message)
        steps = publish.commands(staged, "game/9.9-3", COMMIT)
        self.assertEqual(steps[0][-2:], ["game/9.9-3", COMMIT])
        self.assertEqual(steps[1], ["git", "push", "origin", "refs/tags/game/9.9-3"])
        self.assertEqual(
            [Path(a).name for a in steps[2] if a.startswith(str(staged["directory"] / "assets"))],
            ["SHA256SUMS", "pobr-game-9.9.zip", "receipt.json"],
        )
        self.assertIn("--verify-tag", steps[2])


class SequenceTest(unittest.TestCase):
    def test_next_sequence(self):
        self.assertEqual(publish.next_sequence([], "0.5.5.5"), 1)
        tags = [
            "game/0.5.5.5-1",
            "game/0.5.5.5-10",
            "game/0.5.5.5-2",
            "game/0.5.5.5.1-40",  # another patch
            "game/0.5.5-99",  # another patch
            "game/0.5.5.5-03",  # not a sequence number
            "game/0.5.5.5-4-rc",
            "locale/0.5.5.5-50",
            "handoff/rollback-0.5.5.4.2-20261101",
        ]
        self.assertEqual(publish.next_sequence(tags, "0.5.5.5"), 11)
        self.assertEqual(publish.next_sequence(tags, "0.5.5.5.1"), 41)
        self.assertEqual(publish.next_sequence(tags, "0.6.0"), 1)

    def test_remote_tags_peel_annotated_tags(self):
        output = (
            f"{'1' * 40}\trefs/tags/game/9.9-1\n"
            f"{'2' * 40}\trefs/tags/game/9.9-1^{{}}\n"
            f"{'3' * 40}\trefs/tags/game/9.9-2\n"
        )
        self.assertEqual(publish.remote_tags(output), {"game/9.9-1": "2" * 40, "game/9.9-2": "3" * 40})


class GitRepoCase(unittest.TestCase):
    """Temporary repositories: ``origin`` is a local bare repository."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.origin, self.repo = root / "origin.git", root / "repo"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.repo)], check=True, capture_output=True)
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "test")
        git(self.repo, "checkout", "-q", "-b", "master")
        self.commit("a.txt")
        git(self.repo, "push", "-q", "origin", "master")

    def tearDown(self):
        self.temporary.cleanup()

    def commit(self, name):
        (self.repo / name).write_text(name)
        git(self.repo, "add", name)
        git(self.repo, "commit", "-q", "-m", name)
        return git(self.repo, "rev-parse", "HEAD").strip()


class PreflightTest(GitRepoCase):
    def test_clean_commit_on_master_passes(self):
        commit, problems, warnings = publish.preflight(self.repo)
        self.assertEqual((commit, problems, warnings), (git(self.repo, "rev-parse", "HEAD").strip(), [], []))

    def test_refuses_a_dirty_tree(self):
        (self.repo / "a.txt").write_text("changed")
        self.assertRegex(publish.preflight(self.repo)[1][0], "working tree is not clean")
        git(self.repo, "checkout", "a.txt")
        (self.repo / "untracked.txt").write_text("x")
        self.assertRegex(publish.preflight(self.repo)[1][0], "working tree is not clean.*untracked.txt")

    def test_refuses_a_commit_not_on_origin_master(self):
        commit = self.commit("b.txt")
        self.assertEqual(publish.preflight(self.repo)[1], [f"HEAD {commit} is not on origin/master"])
        # The check uses the fetched remote state, not a stale local ref.
        git(self.repo, "push", "-q", "origin", "master")
        git(self.repo, "update-ref", "refs/remotes/origin/master", "HEAD~1")
        self.assertEqual(publish.preflight(self.repo)[1], [])
        self.assertEqual(publish.preflight(self.repo, fetch=False)[1], [])

    def test_unreachable_remote_is_a_warning(self):
        git(self.repo, "remote", "set-url", "origin", str(Path(self.temporary.name) / "missing.git"))
        commit, problems, warnings = publish.preflight(self.repo)
        self.assertEqual(problems, [])
        self.assertRegex(warnings[0], "could not fetch origin/master")
        self.assertIsNone(publish.list_remote_tags(self.repo))
        decision = publish.plan(self.repo, "9.9", commit, None)
        self.assertEqual((decision["action"], decision["sequence"]), (None, None))
        self.assertRegex(decision["problems"][0], "could not be listed")

    def test_plan_from_remote_and_local_tags(self):
        first = git(self.repo, "rev-parse", "HEAD").strip()
        self.assertEqual(publish.list_remote_tags(self.repo), {})
        self.assertEqual(publish.plan(self.repo, "9.9", first, {}), {"action": "new", "sequence": 1, "problems": []})
        git(self.repo, "tag", "-a", "-m", "one", "game/9.9-1")
        # An unpushed tag on HEAD is resumed, never replaced by a new number.
        self.assertEqual(
            publish.plan(self.repo, "9.9", first, {}), {"action": "resume-push", "sequence": 1, "problems": []}
        )
        git(self.repo, "push", "-q", "origin", "refs/tags/game/9.9-1")
        tags = publish.list_remote_tags(self.repo)
        self.assertEqual(tags, {"game/9.9-1": first})
        self.assertEqual(
            publish.plan(self.repo, "9.9", first, tags), {"action": "remote-tag", "sequence": 1, "problems": []}
        )
        second = self.commit("b.txt")
        self.assertEqual(publish.plan(self.repo, "9.9", second, tags), {"action": "new", "sequence": 2, "problems": []})
        git(self.repo, "tag", "game/9.9-2", first)  # local only, on another commit
        self.assertRegex(publish.plan(self.repo, "9.9", second, tags)["problems"][0], "local tag game/9.9-2")


class Runner:
    """Runs git for real in the test repository; answers gh from ``gh``."""

    def __init__(self, repo, gh=None):
        self.repo, self.gh, self.calls = repo, gh or {}, []

    def __call__(self, command, capture=False):
        self.calls.append(command)
        if command[0] == "git":
            return subprocess.run(command, cwd=self.repo, capture_output=True, check=False)
        answer = self.gh.get(command[1] if command[1] == "auth" else command[2], (0, b""))
        if callable(answer):
            answer = answer(command)
        # (returncode, stderr[, stdout])
        return subprocess.CompletedProcess(command, answer[0], answer[2] if len(answer) > 2 else b"", answer[1])

    def commands(self):
        return [" ".join(c[:3]) for c in self.calls]


class MainTest(GitRepoCase):
    """``main()`` against a temporary repository with release:build replaced by a staged fixture."""

    def setUp(self):
        super().setUp()
        self.head = git(self.repo, "rev-parse", "HEAD").strip()
        self.fixture = StageTest("run")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.receipt["producer"]["commit"] = self.head
        self.fixture.write_build()
        root = Path(self.temporary.name)
        for target, value in (
            ("built", lambda args, config: self.fixture.build_dir),
            ("load_target", lambda config: TARGET),
            ("STAGE", root / "stage"),
        ):
            patcher = mock.patch.object(publish, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def main(self, *argv, runner=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        runner = runner or Runner(self.repo)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                publish.main(["--repo", str(self.repo), "--config", "unused", *argv], runner=runner)
                code = 0
            except SystemExit as exit:
                code = exit.code
        return code, stdout.getvalue() + stderr.getvalue(), runner

    def remote_tag(self, tag):
        return git(self.origin, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}").strip()

    def test_without_yes_nothing_runs(self):
        code, output, runner = self.main()
        self.assertEqual(code, 0, output)
        self.assertIn("dry run: nothing was tagged", output)
        self.assertIn(f"tag: game/9.9-1 -> {self.head}", output)
        self.assertEqual(runner.calls, [])
        self.assertEqual(self.main("--dry-run")[0], 0)

    def test_yes_tags_pushes_and_releases(self):
        code, output, runner = self.main("--yes")
        self.assertEqual(code, 0, output)
        self.assertEqual(
            runner.commands(), ["gh auth status", "git tag --annotate", "git push origin", "gh release create"]
        )
        self.assertEqual(self.remote_tag("game/9.9-1"), self.head)
        self.assertIn("--verify-tag", runner.calls[-1])
        notes = (Path(self.temporary.name) / "stage/poe2-international-9.9/release-notes.md").read_text()
        self.assertIn("sequence 1", notes)

    def test_yes_requires_gh(self):
        runner = Runner(self.repo, {"auth": (1, b"not logged in")})
        with mock.patch.object(publish, "built", side_effect=AssertionError("built")):
            code, output, _ = self.main("--yes", runner=runner)
        self.assertEqual(code, 1)
        self.assertIn("gh is not authenticated: not logged in", output)
        self.assertEqual(runner.commands(), ["gh auth status"])
        self.assertEqual(git(self.repo, "tag", "--list"), "")

    def test_yes_refuses_a_dirty_tree_before_building(self):
        (self.repo / "a.txt").write_text("changed")
        with mock.patch.object(publish, "built", side_effect=AssertionError("built")):
            code, output, runner = self.main("--yes")
        self.assertEqual(code, 1)
        self.assertIn("refusing to publish", output)
        self.assertNotIn("git tag --annotate", runner.commands())

    def test_a_different_package_needs_allow_different(self):
        package = json.loads((self.fixture.build_dir / "package.json").read_text())
        package["package"]["identical_to_reference"] = False
        (self.fixture.build_dir / "package.json").write_text(json.dumps(package))
        code, output, _ = self.main()
        self.assertEqual(code, 1)
        self.assertIn("differs from the reference package", output)
        self.assertEqual(self.main("--allow-different")[0], 0)

    def test_an_expect_pin_replaces_allow_different(self):
        package = json.loads((self.fixture.build_dir / "package.json").read_text())
        expect = {k: package["package"][k] for k in ("bytes", "sha256")}
        package["package"].update(identical_to_reference=False, expect=expect, matches_expect=True)
        (self.fixture.build_dir / "package.json").write_text(json.dumps(package))
        code, output, _ = self.main()
        self.assertEqual(code, 0, output)
        notes = (Path(self.temporary.name) / "stage/poe2-international-9.9/release-notes.md").read_text()
        self.assertIn("Equal to the declaration's `expect` pin: yes", notes)
        package["package"]["matches_expect"] = False
        (self.fixture.build_dir / "package.json").write_text(json.dumps(package))
        code, output, _ = self.main("--allow-different")
        self.assertEqual(code, 1)
        self.assertIn("differs from the declaration's expect pin", output)

    def test_a_sequenced_declaration_gets_exactly_its_number(self):
        def run(name):
            with mock.patch.object(publish, "STAGE", Path(self.temporary.name) / "stage"):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    try:
                        publish.main(["--repo", str(self.repo), "--config", name], runner=Runner(self.repo))
                        return 0, stdout.getvalue()
                    except SystemExit as exit:
                        return exit.code, stdout.getvalue() + stderr.getvalue()

        self.assertEqual(run("9.9-1"), (0, mock.ANY))
        code, output = run("9.9-2")
        self.assertEqual(code, 1)
        self.assertIn("9.9-2 declares game/9.9-2, but HEAD would be published as game/9.9-1", output)
        # A bare release/<patch> is the patch's first package.
        self.assertIsNone(publish.sequence_problem(Path("9.9"), TARGET, 1))
        self.assertIn("declares game/9.9-1, but", publish.sequence_problem(Path("9.9"), TARGET, 4))
        self.assertIsNone(publish.sequence_problem(Path("unused"), TARGET, 4))
        self.assertIsNone(publish.sequence_problem(Path("9.9-4"), TARGET, None))

    def test_refuses_an_adapter_built_against_a_local_pobr_checkout(self):
        self.fixture.receipt["producer"]["contract"] = {**CONTRACT, "tag": None, "commit": None, "local": ["pobr-data"]}
        self.fixture.write_build()
        code, output, runner = self.main()
        self.assertEqual(code, 1)
        self.assertIn("staged: ", output)
        self.assertIn("local PoBR checkout", output)
        code, output, runner = self.main("--yes")
        self.assertEqual(code, 1)
        self.assertNotIn("git tag --annotate", runner.commands())

    def test_refuses_a_package_not_built_from_clean_head(self):
        self.fixture.receipt["producer"]["commit"] = "f" * 40
        self.fixture.write_build()
        code, output, _ = self.main()
        self.assertEqual(code, 1)
        self.assertIn("not built from a clean HEAD", output)
        self.fixture.receipt["producer"].update(commit=self.head, dirty=True)
        self.fixture.write_build()
        self.assertEqual(self.main()[0], 1)

    def test_a_failed_step_resumes_with_the_same_tag(self):
        runner = Runner(self.repo, {"create": (1, b"boom")})
        code, output, _ = self.main("--yes", runner=runner)
        self.assertEqual(code, 1)
        self.assertIn("step failed: gh release create game/9.9-1", output)
        self.assertIn("run by hand:\n  gh release create game/9.9-1", output)
        self.assertNotIn("Traceback", output)
        self.assertEqual(self.remote_tag("game/9.9-1"), self.head)
        # Rerun: the pushed tag is kept; only the Release is created.
        runner = Runner(self.repo, {"view": (1, b"release not found")})
        code, output, runner = self.main("--yes", runner=runner)
        self.assertEqual(code, 0, output)
        self.assertEqual(runner.commands(), ["gh auth status", "gh release view", "gh release create"])
        self.assertIn("game/9.9-1", runner.calls[-1])

    def test_a_missing_gh_fails_the_step_cleanly(self):
        def missing(command):
            raise FileNotFoundError("gh")

        runner = Runner(self.repo, {"create": missing})
        code, output, _ = self.main("--yes", runner=runner)
        self.assertEqual(code, 1)
        self.assertIn("step failed: gh release create", output)

    def test_an_unpushed_local_tag_resumes_from_the_push(self):
        git(self.repo, "tag", "-a", "-m", "earlier run", "game/9.9-1")
        code, output, runner = self.main("--yes")
        self.assertEqual(code, 0, output)
        self.assertEqual(runner.commands(), ["gh auth status", "git push origin", "gh release create"])
        self.assertEqual(self.remote_tag("game/9.9-1"), self.head)

    def test_an_existing_release_is_checked_not_republished(self):
        git(self.repo, "tag", "-a", "-m", "one", "game/9.9-1")
        git(self.repo, "push", "-q", "origin", "refs/tags/game/9.9-1")
        staged_assets = Path(self.temporary.name) / "stage/poe2-international-9.9/assets"

        def download(change=None):
            def run(command):
                out = Path(command[command.index("--dir") + 1])
                for path in staged_assets.iterdir():
                    shutil.copyfile(path, out / path.name)
                if change:
                    (out / "receipt.json").write_text("{}")
                return 0, b""

            return run

        code, output, runner = self.main("--yes", runner=Runner(self.repo, {"download": download()}))
        self.assertEqual(code, 0, output)
        self.assertIn("already published: game/9.9-1", output)
        self.assertNotIn("gh release create", runner.commands())
        code, output, _ = self.main(runner=Runner(self.repo, {"download": download(change=True)}))
        self.assertEqual(code, 1)
        self.assertIn("already released with other assets", output)

    def published_tag_with_draft(self, change=False):
        git(self.repo, "tag", "-a", "-m", "one", "game/9.9-1")
        git(self.repo, "push", "-q", "origin", "refs/tags/game/9.9-1")
        staged_assets = Path(self.temporary.name) / "stage/poe2-international-9.9/assets"

        def download(command):
            out = Path(command[command.index("--dir") + 1])
            for path in staged_assets.iterdir():
                if not (change and path.name == "receipt.json"):
                    shutil.copyfile(path, out / path.name)
            return 0, b""

        return Runner(self.repo, {"view": (0, b"", b'{"tagName":"game/9.9-1","isDraft":true}'), "download": download})

    def test_a_complete_draft_release_is_finished_not_reported_as_published(self):
        code, output, runner = self.main("--yes", runner=self.published_tag_with_draft())
        self.assertEqual(code, 0, output)
        self.assertNotIn("already published", output)
        self.assertEqual(runner.commands()[-1], "gh release edit")
        self.assertIn("--draft=false", runner.calls[-1])
        self.assertNotIn("gh release create", runner.commands())

    def test_an_incomplete_draft_release_asks_to_delete_it(self):
        code, output, runner = self.main("--yes", runner=self.published_tag_with_draft(change=True))
        self.assertEqual(code, 1)
        self.assertIn("unfinished draft Release", output)
        self.assertIn("gh release delete game/9.9-1", output)
        self.assertNotIn("gh release edit", runner.commands())

    def test_reuse_requires_the_build_of_this_checkout(self):
        cache = Path(self.temporary.name) / "cache"
        out = cache / "poe2-international-9.9"
        out.mkdir(parents=True)
        (out / "receipt.json").write_bytes(encoded({"producer": {"commit": "old"}}))
        lock = {"target": TARGET}
        args = mock.Mock(reuse=True, repo=self.repo, adapter="adapter")
        mock.patch.stopall()  # the real built()
        with (
            mock.patch.object(build, "load_config", return_value=(Path("c"), lock, {}, {}, {})),
            mock.patch.object(build, "producer_identity", return_value={"commit": "new"}),
        ):
            with self.assertRaisesRegex(ValueError, "not built from this checkout"):
                publish.built(args, "c", cache)
        with (
            mock.patch.object(build, "load_config", return_value=(Path("c"), lock, {}, {}, {})),
            mock.patch.object(build, "producer_identity", return_value={"commit": "old"}),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(publish.built(args, "c", cache), out)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
