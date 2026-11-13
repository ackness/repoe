"""Export receipts: which checkout produced a candidate, written beside its directory.

Each native exporter writes ``<out>.export-receipt.json`` next to the finished
candidate directory. The receipt pins the candidate's ``manifest.json`` bytes
and records the producing commit, whether the exporters' code or environment
differed from it, and whether the run was a rehearsal. The manifest carries
only the constant ``producer_receipt`` field, so the same client data exports
to the same manifest bytes on every commit that leaves its ``producer`` files
alone, and a rehearsal writes the bytes of the real run.

The exporters, ``release:inputs`` and ``release:build`` import this module, so
it uses the standard library and ``source_io`` only.
"""

import io
import os
from pathlib import Path
import re
import subprocess
import zipfile

from .source_io import decode, encoded, sha256

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "repoe-export-receipt/v1"
FIELD = "producer_receipt"
SUFFIX = ".export-receipt.json"
REPOSITORY = "ackness/repoe"
TARGET = ("game", "game_patch", "realm")
FORMATS = frozenset(
    {
        *(f"repoe-native-facts/v{version}" for version in range(1, 5)),
        "repoe-native-tables/v1",
        "repoe-localized-tables/v1",
        "repoe-native-descriptions/v1",
        "repoe-item-inheritance/v1",
        "repoe-native-player-context/v1",
    }
)
# The frozen pre-receipt source envelope carried by the historical ordinary input package.
HISTORICAL_ARCHIVES = {"7e399fe98e62d4feab6518b454e255c47837ba04167d93b23c9a9e444e02f8b5"}
# The code and environment the exporters load, tracked or untracked. Shared client modules they import
# (source_io, limits, this module) are covered by the glob, not by each manifest's ``producer`` file
# hashes. Source locks, request files and declarations are left out: they change for every patch
# before the export, and a candidate carries its source lock's bytes.
DIRTY_PATHS = (
    "RePoE/native",
    "RePoE/client/*.py",
    "RePoE/__init__.py",
    "schema",
    "pyproject.toml",
    "uv.lock",
    "mise.toml",
    "mise.lock",
)
COMMIT = re.compile(r"[0-9a-f]{40}")
COVERAGE_ACTIONS = ("quarantined", "emitted-with-gap", "retained-legacy", "listed")
RELEASE_JOB_KINDS = frozenset(
    {"adapter", "special-derived", "historical-trees", "crafting-catalog", "gem-descriptions", "snapshot-manifest"}
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def git(repo, *args, check=True, online=False):
    """Run Git; unless ``online``, a partial clone must not lazily fetch missing objects."""
    env = os.environ if online else {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    command = ["git", "--no-replace-objects", "-C", str(repo), *args]
    result = subprocess.run(command, capture_output=True, check=False, env=env)
    _require(not check or result.returncode == 0, f"git {' '.join(args[:3])} failed: {result.stderr.decode().strip()}")
    return result


def changed_paths(repo, *pathspec, untracked="all"):
    """Paths of ``repo`` under ``pathspec`` (default: all) with a tracked change or, per ``untracked``, untracked."""
    # -z and --no-renames: one unquoted "XY path" entry per path.
    # --no-optional-locks: reading the state must not take the index lock of a checkout in use.
    options = ("--porcelain", "-z", "--no-renames", f"--untracked-files={untracked}")
    status = git(repo, "--no-optional-locks", "status", *options, "--", *pathspec)
    return {entry[3:] for entry in status.stdout.decode().split("\0") if entry}


def checkout_identity(repo=ROOT):
    """The commit of ``repo``; dirty on any change or untracked file under ``DIRTY_PATHS``."""
    commit = git(repo, "rev-parse", "--verify", "HEAD^{commit}").stdout.decode().strip()
    dirty = sorted(changed_paths(repo, *DIRTY_PATHS))
    return {"repository": REPOSITORY, "commit": commit, "dirty": bool(dirty), "dirty_paths": dirty}


def add_rehearsal_option(parser):
    parser.add_argument(
        "--rehearsal",
        action="store_true",
        help="allow a dirty checkout; the receipt says rehearsal and the export can never be published",
    )


def receipt_name(directory):
    """The receipt beside a candidate directory: a sibling file, so closed directory inventories stay closed."""
    return f"{directory}{SUFFIX}"


def receipt_bytes(manifest_raw, exporter, identity, rehearsal=False):
    """The receipt of one candidate manifest, checked as its readers check it."""
    manifest = decode(manifest_raw)
    raw = encoded(
        {
            "schema": SCHEMA,
            "exporter": exporter,
            "manifest": {"bytes": len(manifest_raw), "sha256": sha256(manifest_raw)},
            "target": {key: manifest["source_identity"][key] for key in TARGET},
            "producer": identity,
            "rehearsal": bool(rehearsal),
        }
    )
    verify(raw, manifest_raw)
    return raw


def begin(out, exporter, *, rehearsal=False):
    """Check that an export may start; return ``seal(manifest_raw)``, which writes the receipt beside ``out``.

    Call it before reading any input. A dirty checkout is refused unless this
    is a rehearsal, whose receipt says so and can never be published.
    """
    out = Path(out)
    path = out.with_name(receipt_name(out.name))
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Refusing to replace an existing export receipt: {path}")
    identity = checkout_identity()
    if identity["dirty"] and not rehearsal:
        paths = identity["dirty_paths"]
        listed = ", ".join(paths[:5]) + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")
        raise ValueError(
            f"Refusing to export from a dirty checkout ({listed}); commit the changes, "
            "or pass --rehearsal for an export that cannot be published"
        )

    def seal(manifest_raw):
        # Written last: a candidate directory without its receipt is incomplete and cannot be packaged.
        _require(checkout_identity() == identity, "Exporter checkout changed during export; export again")
        raw = receipt_bytes(manifest_raw, exporter, identity, rehearsal)
        with path.open("xb") as stream:
            stream.write(raw)

    return seal


def verify(receipt_raw, manifest_raw):
    """The receipt, checked against the bytes of the candidate manifest it sits beside."""
    manifest, receipt = decode(manifest_raw), decode(receipt_raw)
    _require(
        isinstance(manifest, dict) and manifest.get(FIELD) == SCHEMA, f"candidate manifest lacks {FIELD}: {SCHEMA}"
    )
    _require(
        isinstance(receipt, dict)
        and set(receipt) == {"schema", "exporter", "manifest", "target", "producer", "rehearsal"}
        and receipt["schema"] == SCHEMA,
        f"not a {SCHEMA} receipt",
    )
    _require(isinstance(receipt["exporter"], str) and receipt["exporter"], "receipt names no exporter")
    _require(
        receipt["manifest"] == {"bytes": len(manifest_raw), "sha256": sha256(manifest_raw)},
        "receipt pins another manifest",
    )
    identity = manifest.get("source_identity")
    _require(
        isinstance(identity, dict) and receipt["target"] == {key: identity.get(key) for key in TARGET},
        "receipt target differs from the manifest's source identity",
    )
    producer = receipt["producer"]
    _require(
        isinstance(producer, dict)
        and set(producer) == {"repository", "commit", "dirty", "dirty_paths"}
        and producer["repository"] == REPOSITORY
        and isinstance(producer["commit"], str)
        and COMMIT.fullmatch(producer["commit"]) is not None
        and type(producer["dirty"]) is bool
        and isinstance(producer["dirty_paths"], list)
        and all(isinstance(path, str) and path for path in producer["dirty_paths"])
        and producer["dirty"] == bool(producer["dirty_paths"]),
        "invalid receipt producer",
    )
    _require(type(receipt["rehearsal"]) is bool, "invalid receipt rehearsal flag")
    _require(receipt["rehearsal"] or not producer["dirty"], "a dirty export must be a rehearsal")
    return receipt


def open_tree_issues(jobs):
    """D40's open records, shared by build aggregation, reporting and publication."""
    return (
        issue
        for job in jobs.values()
        for issue in job["issues"]
        if issue["domain"] == "passive-tree" and issue["action"] in ("quarantined", "emitted-with-gap")
    )


def forward_refusal(receipt):
    """D40 refusal from forward evidence; historical strict and native receipts have none."""
    if not isinstance(receipt, dict):
        return "is not a receipt"
    jobs = receipt.get("jobs")
    forward = "coverage" in receipt or (
        isinstance(jobs, dict)
        and any(isinstance(job, dict) and ("status" in job or "domain" in job) for job in jobs.values())
    )
    if not forward:
        return None
    try:
        coverage = receipt.get("coverage")
        _require(
            isinstance(coverage, dict) and coverage.get("format") == "pobr-build-coverage/v1",
            "missing or invalid forward coverage",
        )
        _require(isinstance(jobs, dict) and jobs, "missing or invalid forward jobs")
        covered = coverage.get("jobs")
        _require(isinstance(covered, dict), "missing or invalid coverage jobs")
        for name, job in jobs.items():
            _require(
                isinstance(job, dict) and isinstance(job.get("kind"), str) and job["kind"] in RELEASE_JOB_KINDS,
                f"{name}: invalid job kind",
            )
            _require(job.get("status") in ("succeeded", "failed", "skipped"), f"{name}: missing or invalid status")
            if job["kind"] == "adapter":
                _require(
                    isinstance(job.get("domain"), str) and job["domain"].strip(), f"{name}: missing adapter domain"
                )
                if job["status"] == "succeeded":
                    _require(name in covered, f"{name}: missing adapter coverage")
        for name, job in covered.items():
            _require(name in jobs and jobs[name]["kind"] == "adapter", f"{name}: coverage has no adapter job")
            _require(isinstance(job, dict) and isinstance(job.get("issues"), list), f"{name}: invalid issues")
            for issue in job["issues"]:
                _require(isinstance(issue, dict), f"{name}: invalid issue")
                _require(
                    all(
                        isinstance(issue.get(key), str) and issue[key].strip()
                        for key in ("domain", "kind", "entity", "message")
                    )
                    and issue.get("action") in COVERAGE_ACTIONS
                    and ("observed" not in issue or isinstance(issue["observed"], dict)),
                    f"{name}: invalid issue fields",
                )
                _require(issue["domain"] == jobs[name]["domain"], f"{name}: issue domain differs from job domain")
            counts = job.get("counts")
            _require(
                isinstance(counts, dict)
                and set(counts) == set(COVERAGE_ACTIONS)
                and all(type(value) is int and value >= 0 for value in counts.values())
                and all(
                    counts[action] == sum(issue["action"] == action for issue in job["issues"]) for action in counts
                ),
                f"{name}: invalid issue counts",
            )
        totals = coverage.get("totals")
        _require(
            isinstance(totals, dict)
            and set(totals) == set(COVERAGE_ACTIONS)
            and all(type(value) is int and value >= 0 for value in totals.values())
            and all(totals[action] == sum(job["counts"][action] for job in covered.values()) for action in totals),
            "invalid coverage totals",
        )
        _require(
            type(coverage.get("open_tree_issues")) is int and coverage["open_tree_issues"] >= 0,
            "invalid open tree summary",
        )
    except ValueError as error:
        return f"has invalid D40 evidence: {error}"
    issues = list(open_tree_issues(covered))
    if issues:
        return f"has {len(issues)} open tree issues ({len({issue['entity'] for issue in issues})} issue entities); D40 blocks publication"
    blocked = [
        f"{name} ({job['kind']}, {job['status']})"
        for name, job in jobs.items()
        if (job["kind"] == "special-derived" or (job["kind"] == "adapter" and job["domain"] == "passive-tree"))
        and job["status"] != "succeeded"
    ]
    if blocked:
        return f"has failed or skipped tree producers: {', '.join(blocked)}; D40 blocks publication"
    return None


def refusal(receipt):
    """Why a receipt (an export's, or a release build's) must not be published, or None.

    ``rehearsal`` absent means false, as in receipts published before the field existed.
    """
    if not isinstance(receipt, dict) or not isinstance(receipt.get("producer"), dict):
        return "is not a receipt"
    if receipt.get("rehearsal", False) is not False:
        return "is a rehearsal"
    if receipt["producer"].get("dirty") is not False:
        return "was produced from a dirty checkout"
    return forward_refusal(receipt)


def package_receipts(names, read, formats=()):
    """Verified ``{receipt member: receipt}`` of one package's members; ``read(name)`` returns bytes.

    A candidate manifest is a member named exactly ``manifest.json`` inside a
    directory. Embedded copies (``input-manifest.json``, ``parent-manifest.json``)
    are payloads and a root ``manifest.json`` is the package's own. A candidate
    that carries ``producer_receipt``, or whose ``format`` is in ``formats``,
    must carry the field and have ``<directory>.export-receipt.json`` pinning it.
    Nested ZIPs follow the same rule; receipt keys include the archive member.
    """
    names = set(names)
    receipts = {}
    for name in sorted(names):
        directory, _, base = name.rpartition("/")
        if base != "manifest.json":
            continue
        raw = read(name)
        try:
            manifest = decode(raw)
            if not directory:
                _require(
                    not isinstance(manifest, dict) or manifest.get("format") not in formats,
                    "candidate manifest must be inside a directory beside its export receipt",
                )
                continue
            if not isinstance(manifest, dict) or (FIELD not in manifest and manifest.get("format") not in formats):
                continue
            member = receipt_name(directory)
            _require(member in names, f"no export receipt {member}")
            receipts[member] = verify(read(member), raw)
        except ValueError as error:
            raise ValueError(f"{name}: {error}") from error
    for name in sorted(names):
        _require(
            not name.endswith(SUFFIX) or name in receipts,
            f"{name}: export receipt without a candidate manifest that carries {FIELD}",
        )
        if name.lower().endswith(".zip"):
            raw = read(name)
            nested_formats = () if sha256(raw) in HISTORICAL_ARCHIVES else formats
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                try:
                    nested = package_receipts(archive.namelist(), archive.read, nested_formats)
                except ValueError as error:
                    raise ValueError(f"{name}!{error}") from error
                receipts.update({f"{name}!{member}": receipt for member, receipt in nested.items()})
    return receipts
