"""Native facts: decode pinned raw client resources into offline facts candidates.

Every exporter here reads explicitly pinned bytes (a source lock and raw resources, a parent facts package or
the fixed schema in the repository's ``schema/``) and writes a new candidate under ``.cache/``. Each candidate's
``producer`` map pins the files that produced it by repository path. Facts produced before this package existed
name the earlier ``RePoE/native_*.py`` paths; re-validate those at their producer commit.
"""
