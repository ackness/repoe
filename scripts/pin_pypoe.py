"""Reproduce the native tool pin from a separately verified, local Git object tree."""

import argparse
import hashlib
import json
import subprocess


REVISION = "66d1d7442c5718260e1a8efd24989d22987e91af"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-dir", required=True, help="Read-only local PyPoE repository")
    args = parser.parse_args()

    def git(*arguments):
        return subprocess.check_output(["git", "-C", args.git_dir, *arguments])

    if git("show", f"{REVISION}:.gitattributes").splitlines()[0] != b"*.py ident":
        raise ValueError("Unexpected upstream Python checkout attributes")
    sources = {}
    for path in git("ls-tree", "-r", "--name-only", REVISION, "PyPoE").decode().splitlines():
        if not path.endswith(".py"):
            continue
        raw = git("show", f"{REVISION}:{path}")
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        expanded = raw.replace(b"$Id$", b"$Id: " + blob.encode() + b" $")
        sources[path.removeprefix("PyPoE/")] = sorted(
            {hashlib.sha256(raw).hexdigest(), hashlib.sha256(expanded).hexdigest()}
        )
    print(json.dumps({"revision": REVISION, "sources": sources}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
