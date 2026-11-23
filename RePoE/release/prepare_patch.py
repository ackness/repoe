"""Prepare pinned client inputs locally, stopping before publication or declaration review."""

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import os
from pathlib import Path
import stat
import sys

from RePoE.client import export_lock, export_receipt, source_io, sources
from RePoE.native import crafting_facts, descriptions, facts, item_inheritance, tables, validate
from RePoE.release import build, inputs, patch_recipe
from RePoE.release.pins import decode, encoded, pin, pinned, regular, relative, require, runtime_encoded, safe_path

SCHEMA = "repoe-prepare-patch-progress/v1"
REPORT = "repoe-prepare-patch-report/v1"
MAX_STEP_BYTES = 1024 * 1024 * 1024
MAX_STEP_FILES = 4096


def raise_error(error):
    raise error


def inventory(directory):
    """Pin regular files and directory names without following symlinks."""
    directory = safe_path(directory)
    require(directory.is_dir(), f"missing-output: {directory}")
    files, folders, total = {}, [], 0
    for current, children, names in os.walk(directory, followlinks=False, onerror=raise_error):
        base = Path(current)
        for name in sorted(children):
            path = safe_path(base / name)
            require(stat.S_ISDIR(path.stat().st_mode), f"invalid-output-directory: {path}")
            folders.append(path.relative_to(directory).as_posix())
        for name in sorted(names):
            path = regular(base / name)
            total += path.stat().st_size
            require(len(files) < MAX_STEP_FILES and total <= MAX_STEP_BYTES, "output-inventory-limit")
            files[path.relative_to(directory).as_posix()] = build.file_pin(path)
    return {"files": files, "directories": sorted(folders)}


def tool_pins():
    root = Path(__file__).resolve().parents[2]
    paths = {root / "RePoE/__init__.py", root / "pyproject.toml", root / "uv.lock", root / "mise.toml"}
    for directory in ("RePoE/client", "RePoE/native", "RePoE/release", "schema"):
        paths.update(
            path for path in (root / directory).rglob("*") if path.is_file() and "__pycache__" not in path.parts
        )
    return {path.relative_to(root).as_posix(): build.file_pin(regular(path)) for path in sorted(paths)}


def write_state(path, document):
    safe_path(path)
    temporary = safe_path(path.with_name(path.name + ".new"))
    source_io.write_new(temporary, encoded(document))
    temporary.replace(path)


@contextmanager
def claim(directory):
    path = safe_path(directory / ".running")
    with path.open("x") as stream:
        stream.write(f"{os.getpid()}\n")
        identity = os.fstat(stream.fileno())
    try:
        yield
    finally:
        if path.exists() and not path.is_symlink():
            current = path.stat()
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                path.unlink()


class Preparation:
    def __init__(self, out, intent, resume, check_inputs):
        self.out, self.intent, self.check_inputs = out, intent, check_inputs
        self.path = out / "progress.json"
        if resume:
            self.state = decode(regular(self.path).read_bytes())
            require(self.state.get("schema") == SCHEMA, "invalid-progress-schema")
            require(self.state.get("intent") == intent, "resume-inputs-changed: use a fresh output directory")
            require(isinstance(self.state.get("steps"), dict), "invalid-progress-steps")
            if expected := self.state.get("report"):
                require(build.file_pin(regular(out / "report.json")) == expected, "completed-report-changed")
        else:
            self.state = {"schema": SCHEMA, "intent": intent, "steps": {}}
            self.save()
        self.index = 0

    def save(self):
        write_state(self.path, self.state)

    def budget_used(self):
        return sum(
            attempt.get("network_reserved", 0) for attempts in self.state["steps"].values() for attempt in attempts
        )

    def verify_completed(self):
        for name, attempts in self.state["steps"].items():
            for attempt in attempts:
                if attempt["status"] != "complete":
                    continue
                directory = safe_path(self.out / relative(attempt["directory"]))
                require(directory.parent == self.out / "steps" / name, "invalid-progress-path")
                require(inventory(directory) == attempt["inventory"], f"completed-output-changed: {name}")

    def step(self, label, action, network_reserved=0):
        self.verify_completed()
        self.index += 1
        name = f"{self.index:02d}-{label}"
        attempts = self.state["steps"].setdefault(name, [])
        if attempts and attempts[-1]["status"] == "complete":
            previous = attempts[-1]
            directory = safe_path(self.out / relative(previous["directory"]))
            require(directory.parent == self.out / "steps" / name, "invalid-progress-path")
            require(inventory(directory) == previous["inventory"], f"completed-output-changed: {name}")
            return decode(regular(directory / "result.json").read_bytes())
        self.check_inputs()
        directory = self.out / "steps" / name / f"attempt-{len(attempts) + 1}"
        safe_path(directory).mkdir(parents=True)
        attempt = {"directory": directory.relative_to(self.out).as_posix(), "status": "running"}
        if network_reserved:
            attempt["network_reserved"] = network_reserved
        attempts.append(attempt)
        self.save()
        try:
            with (directory / "output.log").open("x") as stream, redirect_stdout(stream), redirect_stderr(stream):
                result = action(directory)
            self.check_inputs()
            source_io.write_new(directory / "result.json", encoded(result))
            attempt.update(status="complete", inventory=inventory(directory))
            if network_reserved:
                attempt["network_reserved"] = result["network"]["reserved_bytes"]
            self.save()
            return result
        except BaseException as error:
            attempt.update(status="failed", error=f"{type(error).__name__}: {error}"[:2000])
            self.save()
            raise


def decoder_identities(recipe):
    return {
        name: sources.ExternalDecoder(recipe["decoder"]["python"], recipe["decoder"]["lock"]["path"], source).receipt[
            "identity_sha256"
        ]
        for name, source in recipe["sources"].items()
    }


def verify_files(recipe_path, recipe, identity, code, decoder_pin, decoders, repo):
    require(build.file_pin(regular(recipe_path)) == recipe["pin"], "recipe-changed")
    for spec in (recipe["source_lock"], recipe["decoder"]["lock"], *recipe["retained"]):
        require(
            build.file_pin(regular(spec["path"])) == {key: spec[key] for key in ("bytes", "sha256")},
            f"input-changed: {spec['path']}",
        )
    require(export_receipt.checkout_identity(repo) == identity, "producer-changed: use a fresh output directory")
    require(tool_pins() == code, "preparation-code-changed: use a fresh output directory")
    require(build.file_pin(recipe["decoder"]["python"]) == decoder_pin, "decoder-executable-changed")
    require(decoder_identities(recipe) == decoders, "decoder-identity-changed: use a fresh output directory")


def export_candidate(spec, directory, recipe, raws, export_path, candidates, identity, rehearsal):
    output = directory / "candidate"
    kind = spec["kind"]
    if kind == "crafting":
        manifest = crafting_facts.create_candidate(
            facts=Path(candidates[spec["facts"]]["directory"]),
            expected_manifest_sha256=candidates[spec["facts"]]["manifest"]["sha256"],
            out=output,
            rehearsal=rehearsal,
        )
    else:
        arguments = {
            "source_lock": recipe["source_lock"]["path"] if kind == "facts" else export_path,
            "source": spec["source"],
            "raw": Path(raws[spec["source"]]["directory"]),
            "out": output,
            "rehearsal": rehearsal,
        }
        if kind == "facts":
            arguments["profile"] = spec["profile"]
            producer = facts.create_candidate
        else:
            arguments["expected_source_lock_sha256"] = build.file_pin(regular(export_path))["sha256"]
            if kind == "tables":
                producer = tables.create_candidate
                arguments["language"] = spec["language"]
            elif kind == "descriptions":
                producer = descriptions.create_candidate
            else:
                producer = item_inheritance.create_candidate
        manifest = producer(**arguments)
    manifest_raw = regular(output / "manifest.json").read_bytes()
    receipt_path = output.with_name(export_receipt.receipt_name(output.name))
    receipt = export_receipt.verify(regular(receipt_path).read_bytes(), manifest_raw)
    require(receipt["producer"] == identity and receipt["rehearsal"] == rehearsal, "export-receipt-identity-mismatch")
    require(receipt["target"] == recipe["target"], "export-target-mismatch")
    require(decode(manifest_raw) == manifest, "export-manifest-mismatch")
    return {"directory": str(output), "manifest": pin(manifest_raw), "receipt": build.file_pin(receipt_path)}


def assemble(directory, recipe, candidates):
    root = directory / "packages"
    root.mkdir()
    for name in recipe["packages"]:
        (root / name).mkdir()
    for spec in recipe["exports"]:
        source = Path(candidates[spec["id"]]["directory"])
        inventory(source)
        destination = root / spec["package"]
        if spec["destination"] != ".":
            destination = destination / relative(spec["destination"])
        for current, children, names in os.walk(source, followlinks=False, onerror=raise_error):
            base = Path(current)
            target = destination / base.relative_to(source)
            target.mkdir(parents=True, exist_ok=True)
            for name in children:
                safe_path(base / name)
            for name in names:
                path = regular(base / name)
                source_io.write_new(target / name, path.read_bytes())
        receipt = source.with_name(export_receipt.receipt_name(source.name))
        receipt_out = destination.with_name(export_receipt.receipt_name(destination.name))
        source_io.write_new(receipt_out, pinned(regular(receipt).read_bytes(), candidates[spec["id"]]["receipt"]))
    for spec in recipe["retained"]:
        raw = pinned(regular(spec["path"]).read_bytes(), spec)
        source_io.write_new(root / spec["package"] / relative(spec["destination"]), raw)
    return {"packages": {name: str(root / name) for name in recipe["packages"]}}


def prepare(
    *,
    recipe,
    expected_recipe_sha256,
    out,
    mode="offline",
    network_budget_bytes=0,
    range_cache=None,
    rehearsal=False,
    resume=False,
    repo=build.ROOT,
):
    recipe_path, out, repo = map(safe_path, (recipe, out, repo))
    require(mode in ("offline", "online"), "invalid-acquisition-mode")
    require(type(network_budget_bytes) is int, "invalid-network-budget")
    require(
        network_budget_bytes == 0 if mode == "offline" else 0 < network_budget_bytes <= sources.MAX_NETWORK,
        "offline requires zero budget; online requires an explicit bounded network budget",
    )
    cache_root = safe_path(repo / ".cache")
    require(out != cache_root and out.is_relative_to(cache_root), "output-must-be-beneath-checkout-cache")
    data = patch_recipe.load_recipe(recipe_path, expected_recipe_sha256)
    for name, source in data["sources"].items():
        require(rehearsal or source["acquisition"]["status"] == "reviewed-source-input", f"source-not-reviewed: {name}")
    protected = [recipe_path, data["source_lock"]["path"], data["decoder"]["lock"]["path"], data["decoder"]["python"]]
    protected += [entry["path"] for entry in data["retained"]]
    for path in protected:
        require(not (path.is_relative_to(out) or out.is_relative_to(path)), f"output-overlaps-input: {path}")
    if range_cache is not None:
        range_cache = safe_path(range_cache)
        require(
            range_cache != cache_root and range_cache.is_relative_to(cache_root),
            "range-cache-must-be-beneath-checkout-cache",
        )
        require(not range_cache.exists() or range_cache.is_dir(), "range-cache-must-be-directory")
        require(not (range_cache.is_relative_to(out) or out.is_relative_to(range_cache)), "range-cache-overlaps-output")
        for path in protected:
            require(
                not (path.is_relative_to(range_cache) or range_cache.is_relative_to(path)),
                f"range-cache-overlaps-input: {path}",
            )
    else:
        range_cache = out / "ranges"
    identity = export_receipt.checkout_identity(repo)
    require(rehearsal or not identity["dirty"], "dirty-producer: export from clean code or explicitly use --rehearsal")
    code = tool_pins()
    decoder_pin = build.file_pin(data["decoder"]["python"])
    decoders = decoder_identities(data)
    intent = {
        "recipe": {"path": str(recipe_path), **data["pin"]},
        "source_lock": {
            "path": str(data["source_lock"]["path"]),
            **{key: data["source_lock"][key] for key in ("bytes", "sha256")},
        },
        "decoder": {
            "python": str(data["decoder"]["python"]),
            "executable": decoder_pin,
            "lock": str(data["decoder"]["lock"]["path"]),
            "identities": decoders,
        },
        "producer": identity,
        "code": code,
        "python": sys.version,
        "mode": mode,
        "network_budget_bytes": network_budget_bytes,
        "range_cache": str(range_cache),
        "rehearsal": rehearsal,
    }
    if resume:
        require(out.is_dir(), "resume-requires-existing-run")
    else:
        require(not out.exists(), "existing-output: use --resume to verify and continue this run")
        out.mkdir(parents=True)
    with claim(out):

        def check_inputs():
            verify_files(recipe_path, data, identity, code, decoder_pin, decoders, repo)

        run = Preparation(out, intent, resume, check_inputs)
        check_inputs()

        def derive_lock(directory):
            destination = directory / "export-lock.json"
            try:
                digest = export_lock.create(
                    source_lock=data["source_lock"]["path"],
                    expected_source_lock_sha256=data["source_lock"]["sha256"],
                    out=destination,
                    sources=data["source_names"],
                )
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(
                    f"invalid-acquisition-lock: export conversion requires every entry to be a valid acquisition record: {error}"
                ) from error
            return {"path": str(destination), "sha256": digest}

        exported = run.step("export-lock", derive_lock)
        export_path = Path(exported["path"])
        raws, candidates = {}, {}
        for index, name in enumerate(data["source_names"], 1):
            remaining = network_budget_bytes - run.budget_used()

            def acquire(directory, source=name, budget=remaining):
                require(mode == "offline" or budget > 0, "network-budget-exhausted: use a fresh run after review")
                output = directory / "raw"
                receipt = sources.acquire(
                    data["source_lock"]["path"],
                    source,
                    range_cache,
                    output,
                    data["decoder"]["python"],
                    data["decoder"]["lock"]["path"],
                    mode,
                    budget,
                )
                require(receipt["source_lock_sha256"] == data["source_lock"]["sha256"], "acquisition-lock-mismatch")
                require(receipt["decoder"]["identity_sha256"] == decoders[source], "acquisition-decoder-mismatch")
                return {"directory": str(output), "network": receipt["network"], "receipt": receipt}

            raws[name] = run.step(f"acquire-{index}", acquire, max(0, remaining))

        for spec in data["exports"]:
            candidates[spec["id"]] = run.step(
                f"export-{spec['id']}",
                lambda directory, item=spec: export_candidate(
                    item, directory, data, raws, export_path, candidates, identity, rehearsal
                ),
            )
            if spec["kind"] == "facts":

                def validate_facts(directory, item=spec):
                    return validate.validate_candidate(
                        source_lock=data["source_lock"]["path"],
                        source=item["source"],
                        raw=Path(raws[item["source"]]["directory"]),
                        candidate=Path(candidates[item["id"]]["directory"]),
                        manifest_sha256=candidates[item["id"]]["manifest"]["sha256"],
                        profile=item["profile"],
                    )

                run.step(f"validate-{spec['id']}", validate_facts)
        assembled = run.step("assemble", lambda directory: assemble(directory, data, candidates))

        def stage_inputs(directory):
            staged = inputs.stage(
                {name: Path(path) for name, path in assembled["packages"].items()}, data["target"], directory / "stage"
            )
            return {
                "stage": str(staged["directory"]),
                "packages": staged["packages"],
                "assets": staged["assets"],
                "receipts": staged["receipts"],
            }

        staged = run.step("stage", stage_inputs)
        run.verify_completed()
        problems = inputs.receipt_problems(repo, staged["receipts"])
        report = {
            "schema": REPORT,
            "status": "blocked-input-publication" if problems else "awaiting-input-publication",
            "production_ready": False,
            "published": False,
            "target": data["target"],
            "recipe": data["pin"],
            "producer": identity,
            "rehearsal": rehearsal,
            "stage": staged["stage"],
            "packages": staged["packages"],
            "assets": staged["assets"],
            "package_directories": assembled["packages"],
            "publication_problems": problems,
            "source_review": {name: source.get("acquisition") for name, source in data["sources"].items()},
            "network_reserved_bytes": run.budget_used(),
            "steps": [
                {"name": name, "directory": attempts[-1]["directory"], "status": attempts[-1]["status"]}
                for name, attempts in run.state["steps"].items()
            ],
            "next_steps": [
                "Review source evidence and export receipts; re-export any rehearsal or ineligible producer.",
                "Publish inputs only with the existing release:inputs command and explicit authorization.",
                "After verifying the real Release, run policy:rebind and release:declare; review every policy and H line.",
                "Run forward/content-diff review separately; this report does not approve policies or a game release.",
            ],
        }
        check_inputs()
        write_state(out / "report.json", report)
        run.state["report"] = build.file_pin(out / "report.json")
        run.save()
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="release:prepare-patch", description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--expected-recipe-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("offline", "online"), default="offline")
    parser.add_argument("--network-budget-bytes", type=int, default=0)
    parser.add_argument("--range-cache", type=Path)
    parser.add_argument("--rehearsal", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = prepare(**vars(args))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"release:prepare-patch: {error}\n")
    print(runtime_encoded(report).decode(), end="")


if __name__ == "__main__":
    main()
