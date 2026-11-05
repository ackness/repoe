"""English gem descriptions for PoBR (``overlay/gem_descriptions.json``, data contract 1.3).

PoBR's English web loads no language package, so the English text of a gem's
description comes from the game package. The member holds two scopes, keyed by
the ids the translation repository's ``display_texts`` scopes of the same name
use:

* ``GemEffects.SupportText``: ``GemEffects.SupportText`` keyed by
  ``GemEffects.Id``, for every ``variant_id`` in the package's
  ``overlay/gem_effects.json``;
* ``ActiveSkills.Description``: ``ActiveSkills.Description`` keyed by
  ``ActiveSkills.Id``, for the ``active_skill`` of every granted effect those
  gem effects grant (``base/granted_effects.json``).

Text is the client's raw string: ``[A]`` / ``[A|B]`` markup, trailing spaces
and ``\\r\\n`` are kept, so the translation repository can compare English byte
for byte. Rows with empty text are left out. Any other markup form refuses the
build, because PoBR's display rule only knows these two. `release:build` runs
this as the ``gem-descriptions`` job, only in declarations that list it.
"""

import json
import re

from RePoE.release.pins import require

SCHEMA = "repoe-gem-descriptions/v1"
GENERATOR = "RePoE.release.gem_descriptions"
SUPPORT = "GemEffects.SupportText"
ACTIVE = "ActiveSkills.Description"
# Plain text and [A] / [A|B] tags, no nesting; no <...> or {...} markup.
MARKUP = re.compile(r"(?:[^\[\]|<>{}]|\[[^\[\]|<>{}]+(?:\|[^\[\]|<>{}]+)?\])*")


def runtime_encoded(value):
    """PoBR runtime JSON layout; the snapshot manifest pins these exact bytes."""
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def checked(text, where):
    require(isinstance(text, str), f"{where}: text is not a string")
    require(MARKUP.fullmatch(text) is not None, f"{where}: unsupported markup in {text!r}")
    return text


def table_rows(table, name):
    """``Id`` -> row values of a decoded facts table; ids must be unique."""
    require(isinstance(table, dict) and table.get("table") == name, f"Not the {name} table")
    rows = {}
    for row in table["rows"]:
        values = row["values"]
        require(values["Id"] not in rows, f"{name}: duplicate Id {values['Id']}")
        rows[values["Id"]] = values
    return rows


def project(*, gems, active_skills, gem_effects, granted_effects, facts_manifest_sha256, game_patch):
    """Select the descriptions PoBR's player gems reach; return the document and a summary.

    ``gems`` is the facts ``gems.json``, ``active_skills`` its
    ``tables/ActiveSkills.json``; ``gem_effects`` and ``granted_effects`` are
    the package's own ``overlay/gem_effects.json`` and
    ``base/granted_effects.json``, so every id is one PoBR can look up.
    """
    effects = {}
    for effect in gems["effects"]:
        key = effect["gem_effect"]["id"]
        require(key not in effects, f"GemEffects: duplicate Id {key}")
        effects[key] = effect
    skills = table_rows(active_skills, "ActiveSkills")
    granted = {}
    for entry in granted_effects:
        require(entry["id"] not in granted, f"granted_effects: duplicate id {entry['id']}")
        granted[entry["id"]] = entry
    support, active = {}, {}
    for gem in gem_effects["gems"]:
        variant = gem["variant_id"]
        require(variant in effects, f"gem_effects: variant {variant} is not a GemEffects row")
        text = checked(effects[variant]["support_text"], f"{SUPPORT} {variant}")
        if text.strip():
            support[variant] = text
        effect_id = gem["granted_effect_id"]
        require(effect_id in granted, f"gem_effects: granted effect {effect_id} is not in granted_effects")
        skill = granted[effect_id].get("active_skill")
        if skill is None:
            continue
        require(skill in skills, f"granted_effects: active skill {skill} is not an ActiveSkills row")
        text = checked(skills[skill]["Description"], f"{ACTIVE} {skill}")
        if text.strip():
            active[skill] = text
    document = {
        "_meta": {
            "schema": SCHEMA,
            "generator": GENERATOR,
            "facts_manifest_sha256": facts_manifest_sha256,
            "game_patch": game_patch,
        },
        "scopes": {
            ACTIVE: dict(sorted(active.items())),
            SUPPORT: dict(sorted(support.items())),
        },
    }
    summary = {"gem_effects": len(gem_effects["gems"]), ACTIVE: len(active), SUPPORT: len(support)}
    return document, summary
