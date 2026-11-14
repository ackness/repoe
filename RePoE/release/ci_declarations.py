"""Select full-package CI rebuilds; this does not select declarations for build or publication."""

import argparse
from pathlib import Path

from RePoE.release import build
from RePoE.release.pins import decode, require


def selected(releases):
    releases = Path(releases)
    policy = decode((releases / "ci.json").read_bytes())
    require(
        isinstance(policy, dict)
        and set(policy) == {"schema", "current", "retired"}
        and policy["schema"] == "repoe-release-ci/v1",
        "ci.json: expected repoe-release-ci/v1 with schema, current and retired",
    )
    current, retired = policy["current"], policy["retired"]
    require(isinstance(current, str), "ci.json: current must be a declaration name")
    require(
        isinstance(retired, list) and all(isinstance(name, str) for name in retired), "ci.json: invalid retired list"
    )
    require(current not in retired, "ci.json: current cannot be retired")
    require(len(set(retired)) == len(retired), "ci.json: duplicate retired declaration")
    for name in [current, *retired]:
        require(build.config_key(name) is not None, f"ci.json: invalid declaration name: {name!r}")
    configs = sorted(
        (path for path in releases.iterdir() if path.is_symlink() or path.is_dir()), key=lambda path: path.name
    )
    for config in configs:
        require(build.config_key(config.name) is not None, f"Invalid release declaration directory: {config.name}")
        require(not config.is_symlink(), f"Symlink release declaration: {config.name}")
        for filename in build.SCHEMAS:
            require((config / filename).is_file(), f"Incomplete release declaration: {config.name}/{filename}")
    names = {path.name for path in configs}
    require(current in names, f"ci.json: unknown current declaration: {current}")
    require(not (unknown := set(retired) - names), f"ci.json: unknown retired declarations: {sorted(unknown)}")
    return [path for path in configs if path.name not in retired]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--releases", type=Path, default=Path("release"), help="Declaration root containing ci.json")
    args = parser.parse_args(argv)
    try:
        configs = selected(args.releases)
    except (ValueError, OSError) as error:
        parser.exit(1, f"release:ci-configs: {error}\n")
    # Validate the entire selection before emitting any path; a failure cannot become a partial build list.
    print("\n".join(path.as_posix() for path in configs))


if __name__ == "__main__":
    main()
