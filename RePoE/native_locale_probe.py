"""Nine-table, standard-library-only memory decoding and bounded transfer.

Execute this source in an existing process, then call decode_table on already
extracted bytes. No file, network, installation or patch/realm discovery occurs.
"""

import base64
import hashlib
import json
import math
import struct
import zlib


SCHEMA_REVISION = "6034b071846ef61b39046ebdb59e6d5717179509"
SCHEMA_SHA256 = "50e098543345cf8323aeb294e2cfef1b6b44842faccf560ada935cebe22727df"
COLUMN_PINS = {
    "Words": "f2fc1a18d3cff4b6010be454fb66dc473b90a3ddf30e9d3cd069bfb91fee2660",
    "Ascendancy": "ac06ba05b8e7fc3006c91310fc0a697d824fa8a74d209070e7760c9dbf09360a",
    "BaseItemTypes": "8848dfab2450d414260046898250394bd2f032992dad5ddc40f89e7e1ec3c3ff",
    "ActiveSkills": "c6391ce8fddc0da2dabd335ec9d99ae8181f365ae1f42cf4fda9b937bb1b72b2",
    "Mods": "9dac3544252910eb9a709c4327e1e3c35293b269ff10db3ee6da406f265c46d8",
    "Characters": "e26ddc7223f94599aee76bb1c8ac2299a4ea8e3096e132ae4ae3cec30513720e",
    "PassiveSkills": "fff0864b870a60b2c457a83b732820bfd9d74f128efd5f153693950578f1995f",
    "ItemClasses": "420a344248fac49590ae2182be08c3d0b04efdf9336d0312c3c3396b1f5f8f31",
    "AlternateQualityTypes": "53051c491eebe68824826c6f071b6386032bdd9b570196514b5c9cf3e910bfda",
}
LAYOUTS = {
    "Words": [
        ("Wordlist", "int"),
        ("Text", "ref|string"),
        ("SpawnWeight_Tags", "ref|list|ref|out"),
        ("SpawnWeight_Values", "ref|list|int"),
        ("HASH32", "uint"),
        ("Text2", "ref|string"),
        ("Inflection", "ref|string"),
    ],
    "Ascendancy": [
        ("Id", "ref|string"),
        ("ClassNo", "int"),
        ("Character", "ref|out"),
        ("CoordinateRect", "ref|string"),
        ("RGBFlavourTextColour", "ref|string"),
        ("Name", "ref|string"),
        ("FlavourText", "ref|string"),
        ("OGGFile", "ref|string"),
        ("PassiveTreeImage", "ref|string"),
        ("TreeRegionVector", "int"),
        ("TreeRegionAngle", "int"),
        ("BackgroundImage", "int"),
        ("Unknown0", "int"),
        ("Disabled", "bool"),
        ("BaseAscendancy", "ref|generic"),
        ("UIArt", "ref|out"),
        ("SelectSound", "ref|out"),
        ("ConfirmDownSound", "ref|out"),
        ("ConfirmUpSound", "ref|out"),
    ],
    "BaseItemTypes": [
        ("Id", "ref|string"),
        ("ItemClass", "ref|out"),
        ("Width", "int"),
        ("Height", "int"),
        ("Name", "ref|string"),
        ("InheritsFrom", "ref|string"),
        ("DropLevel", "int"),
        ("FlavourText", "ref|out"),
        ("Implicit_Mods", "ref|list|ref|out"),
        ("SizeOnGround", "int"),
        ("SoundEffect", "ref|out"),
        ("Tags", "ref|list|ref|out"),
        ("ModDomain", "int"),
        ("ItemVisualIdentity", "ref|out"),
        ("HASH32", "uint"),
        ("VendorRecipe_AchievementItems", "ref|list|ref|out"),
        ("Inflection", "ref|string"),
        ("Equip_AchievementItem", "ref|out"),
        ("IsCorrupted", "bool"),
        ("Identify_AchievementItems", "ref|list|ref|out"),
        ("IdentifyMagic_AchievementItems", "ref|list|ref|out"),
        ("FragmentBaseItemType", "ref|generic"),
        ("Flag0", "bool"),
        ("UncutGemSoundEffect", "ref|out"),
        ("ItemStance", "ref|out"),
        ("Flag1", "bool"),
        ("Unmodifiable", "bool"),
        ("Achievement", "ref|list|ref|out"),
        ("ShopTag", "ref|out"),
        ("Key0", "ref|out"),
        ("Unknown0", "int"),
        ("Data0", "ref|list|byte"),
        ("Data1", "ref|list|byte"),
        ("Data2", "ref|list|byte"),
    ],
    "ActiveSkills": [
        ("Id", "ref|string"),
        ("DisplayedName", "ref|string"),
        ("Description", "ref|string"),
        ("ActionType", "ref|out"),
        ("Icon_DDSFile", "ref|string"),
        ("ActiveSkillTargetTypes", "ref|list|int"),
        ("ActiveSkillTypes", "ref|list|ref|out"),
        ("WebsiteDescription", "ref|string"),
        ("WebsiteImage", "ref|string"),
        ("HideOnWebsite", "bool"),
        ("GrantedEffect", "ref|string"),
        ("Flag0", "bool"),
        ("SkillTotemId", "int"),
        ("IsManuallyCasted", "bool"),
        ("Input_Stats", "ref|list|ref|out"),
        ("Output_Stats", "ref|list|ref|out"),
        ("MinionActiveSkillTypes", "ref|list|ref|out"),
        ("Flag1", "bool"),
        ("IsGem", "bool"),
        ("SecondarySkillSpecificStats", "ref|list|ref|out"),
        ("SkillMine", "int"),
        ("AlternateSkillTargetingBehaviour", "ref|out"),
        ("Flag2", "bool"),
        ("AIFile", "ref|string"),
        ("StatContextFlags", "ref|list|ref|out"),
        ("Flag3", "bool"),
        ("Flag4", "bool"),
        ("Flag5", "bool"),
        ("ShapeShiftForm", "ref|out"),
        ("VideoClip", "ref|string"),
        ("CharacterAudioEvent", "ref|out"),
        ("AiScript", "ref|string"),
        ("AudioEvent", "ref|out"),
        ("Flag6", "bool"),
        ("ShortDescription", "ref|string"),
        ("StatDescriptionType", "int"),
        ("StatDescription", "ref|string"),
        ("WeaponRequirements", "ref|out"),
        ("Unknown0", "int"),
        ("Unknown1", "ref|string"),
    ],
    "Mods": [
        ("Id", "ref|string"),
        ("HASH16", "ushort"),
        ("ModType", "ref|out"),
        ("Level", "int"),
        ("Stat1", "ref|out"),
        ("Stat2", "ref|out"),
        ("Stat3", "ref|out"),
        ("Stat4", "ref|out"),
        ("Domain", "int"),
        ("Name", "ref|string"),
        ("GenerationType", "int"),
        ("Families", "ref|list|ref|out"),
        ("Stat1Min", "int"),
        ("Stat1Max", "int"),
        ("Stat2Min", "int"),
        ("Stat2Max", "int"),
        ("Stat3Min", "int"),
        ("Stat3Max", "int"),
        ("Stat4Min", "int"),
        ("Stat4Max", "int"),
        ("SpawnWeight_Tags", "ref|list|ref|out"),
        ("Data0", "ref|list|int"),
        ("Tags", "ref|list|ref|out"),
        ("GrantedEffectsPerLevel", "ref|list|ref|out"),
        ("AuraFlags", "ref|list|int"),
        ("Data1", "ref|list|int"),
        ("MonsterMetadata", "ref|string"),
        ("MonsterKillAchievements", "ref|list|ref|out"),
        ("ChestModType", "ref|list|ref|out"),
        ("Stat5Min", "int"),
        ("Stat5Max", "int"),
        ("Stat5", "ref|out"),
        ("FullAreaClear_AchievementItems", "ref|list|ref|out"),
        ("AchievementItems", "ref|list|ref|out"),
        ("GenerationWeight_Tags", "ref|list|ref|out"),
        ("GenerationWeight_Values", "ref|list|int"),
        ("ModifyMapsAchievements", "ref|list|ref|out"),
        ("Stat6Min", "int"),
        ("Stat6Max", "int"),
        ("Stat6", "ref|out"),
        ("MaxLevel", "int"),
        ("Flag0", "bool"),
        ("CraftingItemClassRestrictions", "ref|list|ref|out"),
        ("MonsterOnDeath", "ref|string"),
        ("Unknown0", "int"),
        ("HeistAchievements", "ref|list|ref|out"),
        ("Stat7Min", "int"),
        ("Stat7Max", "int"),
        ("Stat7", "ref|out"),
        ("Stat8", "ref|out"),
        ("Stat8Min", "int"),
        ("Stat8Max", "int"),
        ("InfluenceType", "int"),
        ("ImplicitTags", "ref|list|ref|out"),
        ("HasHardmodeStatValues", "bool"),
        ("Stat1MinHardmode", "int"),
        ("Stat1MaxHardmode", "int"),
        ("Stat2MinHardmode", "int"),
        ("Stat2MaxHardmode", "int"),
        ("Stat3MinHardmode", "int"),
        ("Stat3MaxHardmode", "int"),
        ("Stat4MinHardmode", "int"),
        ("Stat4MaxHardmode", "int"),
        ("Stat5MinHardmode", "int"),
        ("Stat5MaxHardmode", "int"),
        ("Stat6MinHardmode", "int"),
        ("Stat6MaxHardmode", "int"),
        ("Stat7MinHardmode", "int"),
        ("Stat7MaxHardmode", "int"),
        ("Stat8MinHardmode", "int"),
        ("Stat8MaxHardmode", "int"),
        ("BuffTemplate", "ref|out"),
        ("ArchnemesisMinionMod", "ref|generic"),
        ("HASH32", "uint"),
        ("BuffTemplate2", "ref|list|ref|out"),
        ("Unknown1", "int"),
        ("Keys0", "ref|list|ref|out"),
        ("RadiusJewelType", "int"),
        ("IsEssenceOnlyModifier", "bool"),
        ("SpawnLevel_Override", "int"),
        ("SpawnWeight_Values", "ref|list|int"),
    ],
    "Characters": [
        ("Id", "ref|string"),
        ("Name", "ref|string"),
        ("AOFile", "ref|string"),
        ("ACTFile", "ref|string"),
        ("BaseMaxLife", "int"),
        ("BaseMaxMana", "int"),
        ("WeaponSpeed", "int"),
        ("MinDamage", "int"),
        ("MaxDamage", "int"),
        ("MaxAttackDistance", "int"),
        ("Icon", "ref|string"),
        ("IntegerId", "int"),
        ("BaseStrength", "int"),
        ("BaseDexterity", "int"),
        ("BaseIntelligence", "int"),
        ("StartingSkill", "ref|list|ref|out"),
        ("Description", "ref|string"),
        ("StartSkillGem", "ref|out"),
        ("Key0", "ref|out"),
        ("WeaponSoundType", "ref|out"),
        ("Unknown0", "int"),
        ("CharacterSize", "int"),
        ("IntroSoundFile", "ref|string"),
        ("StartWeapons", "ref|list|ref|out"),
        ("Gender", "ref|string"),
        ("TraitDescription", "ref|string"),
        ("Key1", "ref|out"),
        ("Key2", "ref|out"),
        ("Keys0", "ref|list|ref|out"),
        ("LevelUpEffect", "ref|out"),
        ("Unknown1", "int"),
        ("PassiveTreeImage", "ref|string"),
        ("Unknown2", "ref|string"),
        ("AttrsAsId", "ref|string"),
        ("LoginScreen", "ref|string"),
        ("PlayerCritter", "ref|string"),
        ("PlayerEffect", "ref|string"),
        ("AfterImage", "ref|string"),
        ("Mirage", "ref|out"),
        ("CloneImmobile", "ref|out"),
        ("ReplicateClone", "ref|out"),
        ("LightningClone", "ref|out"),
        ("Unknown3", "float"),
        ("Unknown4", "float"),
        ("SkillTreeBackground", "ref|string"),
        ("Clone", "ref|out"),
        ("Data0", "ref|list|byte"),
        ("MirageWarrior", "ref|out"),
        ("DoubleTwo", "ref|out"),
        ("DarkExile", "ref|out"),
        ("Attr", "ref|string"),
        ("AttrLowercase", "ref|string"),
        ("Script", "ref|string"),
        ("GhostArmMtx", "ref|out"),
        ("Unknown5", "int"),
        ("Unknown6", "float"),
        ("Unknown7", "float"),
        ("Unknown8", "float"),
        ("BaseClass", "ref|string"),
        ("StartingPassive", "ref|out"),
        ("StartingWeapon", "ref|out"),
        ("CreationIcons", "ref|list|ref|out"),
        ("Unknown9", "float"),
        ("GemCuttingIcon", "ref|string"),
        ("Portrait", "ref|out"),
        ("Key3", "ref|out"),
    ],
    "PassiveSkills": [
        ("Id", "ref|string"),
        ("Icon_DDSFile", "ref|string"),
        ("Stats", "ref|list|ref|out"),
        ("Stat1Value", "int"),
        ("Stat2Value", "int"),
        ("Stat3Value", "int"),
        ("Stat4Value", "int"),
        ("PassiveSkillGraphId", "ushort"),
        ("Name", "ref|string"),
        ("Characters", "ref|list|ref|out"),
        ("IsKeystone", "bool"),
        ("IsNotable", "bool"),
        ("FlavourText", "ref|string"),
        ("IsJustIcon", "bool"),
        ("AchievementItem", "ref|out"),
        ("IsJewelSocket", "bool"),
        ("Ascendancy", "ref|out"),
        ("IsAscendancyStartingNode", "bool"),
        ("ReminderStrings", "ref|list|ref|out"),
        ("SkillPointsGranted", "int"),
        ("IsMultipleChoice", "bool"),
        ("IsMultipleChoiceOption", "bool"),
        ("Stat5Value", "int"),
        ("PassiveSkillBuffs", "ref|list|ref|out"),
        ("IsAnointmentOnly", "bool"),
        ("Unknown0", "int"),
        ("IsExpansion", "bool"),
        ("IsProxyPassive", "bool"),
        ("SkillType", "int"),
        ("MasteryGroup", "ref|out"),
        ("Group", "ref|out"),
        ("SoundEffect", "ref|out"),
        ("AtlasNodeGroup", "ref|string"),
        ("Unknown1", "int"),
        ("Unknown2", "int"),
        ("Unknown3", "int"),
        ("Unknown4", "int"),
        ("Unknown5", "int"),
        ("Flag0", "bool"),
        ("Keys0", "ref|list|ref|out"),
        ("Unknown6", "int"),
        ("Keys1", "ref|list|ref|out"),
        ("Flag1", "bool"),
        ("AudioEvent", "ref|out"),
        ("Flag2", "bool"),
        ("IsAttribute", "bool"),
        ("AtlasSubTree", "ref|out"),
        ("IsRootOfAtlasTree", "bool"),
        ("GrantedSkill", "ref|out"),
        ("WeaponPointsGranted", "int"),
        ("IsFree", "bool"),
        ("Flag3", "bool"),
        ("UnlockedBy", "ref|list|ref|generic"),
        ("VisibleForAscendancy", "ref|out"),
        ("Flag4", "bool"),
        ("NodeFrameArt", "ref|out"),
        ("Flag5", "bool"),
        ("Unknown7", "int"),
        ("Flag6", "bool"),
        ("BrequelTree", "ref|out"),
        ("Unknown8", "int"),
        ("Flag7", "bool"),
        ("Stat6Value", "int"),
        ("Stat7Value", "int"),
        ("Unknown9", "int"),
        ("Unknown10", "int"),
        ("VariantType", "ref|out"),
        ("Unknown11", "int"),
        ("QuestFlag", "ref|out"),
        ("Requirement", "ref|out"),
    ],
    "ItemClasses": [
        ("Id", "ref|string"),
        ("Name", "ref|string"),
        ("ItemClassCategory", "ref|out"),
        ("RemovedIfLeavesArea", "bool"),
        ("Data0", "ref|list|byte"),
        ("IdentifyAchievements", "ref|list|ref|out"),
        ("AllocateToMapOwner", "bool"),
        ("AlwaysAllocate", "bool"),
        ("CanHaveVeiledMods", "bool"),
        ("PickedUpQuest", "ref|out"),
        ("Unknown0", "int"),
        ("AlwaysShow", "bool"),
        ("CanBeCorrupted", "bool"),
        ("CanHaveIncubators", "bool"),
        ("CanHaveInfluence", "bool"),
        ("CanBeDoubleCorrupted", "bool"),
        ("CanHaveAspects", "bool"),
        ("ItemStance", "ref|out"),
        ("CanScourge", "bool"),
        ("CanUpgradeRarity", "bool"),
        ("Flag0", "bool"),
        ("ItemClassFlags", "ref|list|int"),
        ("Unmodfiable", "bool"),
        ("CanBeFractured", "bool"),
        ("EquipAchievement", "ref|out"),
        ("UsableInMapDevice", "bool"),
        ("Flag1", "bool"),
        ("Flag2", "bool"),
    ],
    "AlternateQualityTypes": [
        ("Id", "ref|string"),
        ("Description", "ref|string"),
        ("Item", "ref|out"),
        ("ModEffectStat", "ref|out"),
        ("HASH16", "ushort"),
        ("ItemClass", "ref|list|ref|out"),
    ],
}
WIDTHS = {
    "int": 4,
    "uint": 4,
    "ushort": 2,
    "byte": 1,
    "float": 4,
    "bool": 1,
    "ref|string": 8,
    "ref|out": 16,
    "ref|generic": 8,
}
NULLS = {-0x1010102, 0xFEFEFEFE, -0x101010101010102, 0xFEFEFEFEFEFEFEFE, 0xFFFFFFFF}
METHOD = "stdlib-memory-schema-decoder/v2"
# Explicit text fields; schema localized flags are incomplete in this fixed input.
TEXT_FIELDS = {
    "Words": ["Text2", "Inflection"],
    "Ascendancy": ["Name", "FlavourText"],
    "BaseItemTypes": ["Name", "Inflection"],
    "ActiveSkills": ["DisplayedName", "Description", "ShortDescription", "WebsiteDescription"],
    "Mods": ["Name"],
    "Characters": ["Name", "Description", "TraitDescription"],
    "PassiveSkills": ["Name", "FlavourText"],
    "ItemClasses": ["Name"],
    "AlternateQualityTypes": ["Description"],
}
NAME_FIELDS = {
    "Words": "Text2",
    "Ascendancy": "Name",
    "BaseItemTypes": "Name",
    "ActiveSkills": "DisplayedName",
    "Mods": "Name",
    "Characters": "Name",
    "PassiveSkills": "Name",
    "ItemClasses": "Name",
    "AlternateQualityTypes": "Description",
}


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def width(kind):
    return 16 if kind.startswith("ref|list|") else WIDTHS[kind]


def decode_table(name, raw, *, expected_bytes, expected_sha256):
    """Verify externally supplied raw observation before parsing all physical rows.

    Pins may be acquisition observations. They do not authenticate source/build.
    Scalar null handling matches the fixed native reader, including numeric null
    sentinels. Foreign-reference second words remain separate wire observations.
    """
    if name not in LAYOUTS or type(raw) is not bytes or not 12 <= len(raw) <= 32 * 1024 * 1024:
        raise ValueError("Expected bounded selected nine-table DAT64 byte buffer")
    digest = hashlib.sha256(raw).hexdigest()
    if type(expected_bytes) is not int or len(raw) != expected_bytes or digest != expected_sha256:
        raise ValueError("Raw buffer differs from external byte pin")
    layout = LAYOUTS[name]
    row_bytes = sum(width(kind) for _, kind in layout)
    count = struct.unpack_from("<I", raw)[0]
    boundary = 4 + count * row_bytes
    if count > 100000 or raw[boundary : boundary + 8] != b"\xbb" * 8:
        raise ValueError("Exact schema row width/framing mismatch")
    marker = raw.find(b"\xbb" * 8, 4)
    while marker < boundary:
        if not count or (marker - 4) % count == 0:
            raise ValueError("Ambiguous physical framing")
        marker = raw.find(b"\xbb" * 8, marker + 1)
    strings, foreign_tails, rows = {}, [], []
    work = 0

    def variable(start, length):
        if start < boundary + 8 or start > len(raw) or length < 0 or length > len(raw) - start:
            raise ValueError("Variable-data pointer/span outside raw buffer")

    def value(kind, at, context):
        nonlocal work
        work += 1
        if work > 16000000:
            raise ValueError("Decoded value count exceeds memory probe bound")
        if kind.startswith("ref|list|"):
            length, pointer = struct.unpack_from("<QQ", raw, at)
            if not length:
                return []
            if length > 100000:
                raise ValueError("Array count exceeds probe bound")
            element = kind[9:]
            start = boundary + pointer
            variable(start, length * width(element))
            return [value(element, start + i * width(element), context + [i]) for i in range(length)]
        if kind == "ref|string":
            start = boundary + struct.unpack_from("<Q", raw, at)[0]
            variable(start, 4)
            if start not in strings:
                end = raw.find(b"\0" * 4, start)
                while end != -1 and (end - start) % 2:
                    end = raw.find(b"\0" * 4, end + 1)
                if end == -1:
                    raise ValueError("Unterminated UTF-16 string")
                strings[start] = raw[start:end].decode("utf-16-le")
            return strings[start]
        if kind == "bool":
            number = raw[at]
            if number not in {0, 1}:
                raise ValueError("Noncanonical boolean")
            return bool(number)
        number = struct.unpack_from(
            "<" + {"int": "i", "uint": "I", "ushort": "H", "byte": "b", "float": "f"}.get(kind, "Q"), raw, at
        )[0]
        if isinstance(number, float) and not math.isfinite(number):
            raise ValueError("Nonfinite physical float cannot enter JSON transfer")
        if kind == "ref|out":
            tail = struct.unpack_from("<Q", raw, at + 8)[0]
            if tail:
                foreign_tails.append({"context": context, "raw_second_word": tail})
        return None if number in NULLS else number

    for ordinal in range(count):
        at, fields = 4 + ordinal * row_bytes, {}
        for field, kind in layout:
            fields[field] = value(kind, at, [ordinal, field])
            at += width(kind)
        rows.append({"_row": ordinal, "values": fields})
    return {
        "table": name,
        "physical_fields": [field for field, _ in layout],
        "wire_layout": layout,
        "rows": rows,
        "validation": {"rows": count, "schema_row_bytes": row_bytes, "actual_row_bytes": row_bytes},
        "raw_identity": {"bytes": len(raw), "sha256": digest},
        "schema": {"revision": SCHEMA_REVISION, "sha256": SCHEMA_SHA256, "columns_sha256": COLUMN_PINS[name]},
        "foreign_tail_observations": foreign_tails,
        "status": "memory-decode-probe-only",
        "decoder_method": METHOD,
        "patch_certified": False,
        "realm_certified": False,
    }


def compare_pair(default, localized):
    """Report structural correspondence without claiming same patch or realm."""
    name = default["table"]
    if localized["table"] != name:
        raise ValueError("Cannot compare different tables")
    key = "HASH32" if name == "Words" else "Id"
    ignored = set(TEXT_FIELDS[name])
    maps, duplicates = [], []
    for table in [default, localized]:
        mapping, repeated = {}, []
        for row in table["rows"]:
            identity = row["values"][key]
            if identity is None or identity in mapping:
                repeated.append({"row": row["_row"], "key": identity})
            mapping[identity] = row
        maps.append(mapping)
        duplicates.append(repeated)
    left, right = maps
    differences = []

    def order(identity):
        return type(identity).__name__, str(identity)

    for identity in sorted(left.keys() & right.keys(), key=order):
        for field in default["physical_fields"]:
            if field not in ignored and left[identity]["values"][field] != right[identity]["values"][field]:
                differences.append(
                    {
                        "key": identity,
                        "field": field,
                        "default": left[identity]["values"][field],
                        "localized": right[identity]["values"][field],
                    }
                )
    return {
        "key": key,
        "duplicate_or_null_keys": duplicates,
        "default_only": sorted(left.keys() - right.keys(), key=order),
        "localized_only": sorted(right.keys() - left.keys(), key=order),
        "nontext_differences": differences,
        "default_rows": len(default["rows"]),
        "localized_rows": len(localized["rows"]),
        "patch_certified": False,
        "realm_certified": False,
    }


def digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def validate_table(table):
    """Validate typed decoded observations without claiming raw-byte redecoding."""
    name = table["table"]
    if name not in LAYOUTS:
        raise ValueError("Table outside fixed nine-table selection")
    layout = [list(pair) for pair in LAYOUTS[name]]
    if [list(pair) for pair in table["wire_layout"]] != layout:
        raise ValueError("Decoded physical layout differs from fixed schema")
    fields = [field for field, _ in LAYOUTS[name]]
    if table["physical_fields"] != fields:
        raise ValueError("Decoded physical fields differ from fixed schema")
    if table["schema"] != {"revision": SCHEMA_REVISION, "sha256": SCHEMA_SHA256, "columns_sha256": COLUMN_PINS[name]}:
        raise ValueError("Decoded column/schema pin mismatch")
    pin = table["raw_identity"]
    if type(pin.get("bytes")) is not int or not 12 <= pin["bytes"] <= 32 * 1024 * 1024 or not digest(pin.get("sha256")):
        raise ValueError("Invalid decoded raw observation pin")
    rows = table["rows"]
    row_bytes = sum(width(kind) for _, kind in LAYOUTS[name])
    if (
        not isinstance(rows, list)
        or len(rows) > 100000
        or any(type(number) is not int for number in table["validation"].values())
        or table["validation"]
        != {
            "rows": len(rows),
            "schema_row_bytes": row_bytes,
            "actual_row_bytes": row_bytes,
        }
    ):
        raise ValueError("Invalid decoded row count/framing declaration")
    if table.get("decoder_method") != METHOD:
        raise ValueError("Wrong decoded observation method")

    def check(kind, value):
        if kind.startswith("ref|list|"):
            if not isinstance(value, list) or len(value) > 100000:
                raise ValueError("Invalid decoded array")
            for entry in value:
                check(kind[9:], entry)
        elif kind == "ref|string":
            if not isinstance(value, str):
                raise ValueError("Invalid decoded string")
        elif kind == "bool":
            if type(value) is not bool:
                raise ValueError("Invalid decoded boolean")
        elif value is None:
            if kind in {"byte", "ushort"}:
                raise ValueError("Invalid null in nonnullable wire scalar")
        elif kind == "float":
            if type(value) is not float or not math.isfinite(value):
                raise ValueError("Invalid decoded float")
        else:
            lo, hi = {
                "int": (-(2**31), 2**31 - 1),
                "uint": (0, 2**32 - 1),
                "byte": (-128, 127),
                "ushort": (0, 65535),
            }.get(kind, (0, 2**64 - 1))
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError("Invalid decoded integer")

    for ordinal, row in enumerate(rows):
        if (
            set(row) != {"_row", "values"}
            or type(row["_row"]) is not int
            or row["_row"] != ordinal
            or set(row["values"]) != set(fields)
        ):
            raise ValueError("Noncontiguous decoded rows or missing/extra columns")
        for field, kind in LAYOUTS[name]:
            check(kind, row["values"][field])
    for tail in table["foreign_tail_observations"]:
        if (
            set(tail) != {"context", "raw_second_word"}
            or type(tail["raw_second_word"]) is not int
            or not 0 <= tail["raw_second_word"] < 2**64
        ):
            raise ValueError("Invalid foreign-reference wire observation")
        context = tail["context"]
        if (
            not isinstance(context, list)
            or not 2 <= len(context) <= 3
            or type(context[0]) is not int
            or not 0 <= context[0] < len(rows)
            or context[1] not in fields
        ):
            raise ValueError("Invalid foreign-reference observation context")
        kind = dict(LAYOUTS[name])[context[1]]
        if len(context) == 3:
            if (
                kind != "ref|list|ref|out"
                or type(context[2]) is not int
                or not 0 <= context[2] < len(rows[context[0]]["values"][context[1]])
            ):
                raise ValueError("Invalid foreign-array observation context")
        elif kind != "ref|out":
            raise ValueError("Foreign-tail observation points to non-reference")
    return name


class MemoryTransfer:
    """Keep compressed per-table pairs in memory; explicitly fetch bounded parts.

    The receipt contains only safe small integers and string hashes. Complete
    physical values (including 64-bit foreign tails) remain inside base64, never
    through a JavaScript JSON-number roundtrip. Raw bytes are not transmitted.
    """

    def __init__(self, *, observed_client, decoder_source_sha256, python_version, evidence):
        if (
            set(observed_client) != {"game", "game_patch", "realm", "index_sha256"}
            or observed_client["game"] != "poe2"
            or observed_client["game_patch"] is not None
            or observed_client["realm"] is not None
            or not digest(observed_client["index_sha256"])
        ):
            raise ValueError("Explicit unknown-patch/realm observed client with index pin required")
        if (
            not digest(decoder_source_sha256)
            or not isinstance(python_version, str)
            or not 0 < len(python_version) <= 512
        ):
            raise ValueError("Explicit decoder source/runtime observation required")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 16:
            raise ValueError("Bounded acquisition evidence required")
        for entry in evidence:
            if (
                set(entry) != {"kind", "sha256"}
                or not isinstance(entry["kind"], str)
                or not 0 < len(entry["kind"]) <= 128
                or not digest(entry["sha256"])
            ):
                raise ValueError("Invalid acquisition evidence pin")
        self.observed_client = dict(observed_client)
        self.decoder = {
            "method": METHOD,
            "source_sha256": decoder_source_sha256,
            "python": python_version,
            "zlib": zlib.ZLIB_VERSION,
        }
        self.evidence = evidence
        self.tables, self.bodies = {}, {}

    def add_pair(self, default, localized, *, default_resource, localized_resource):
        name = validate_table(default)
        if validate_table(localized) != name or name in self.tables:
            raise ValueError("Duplicate/different transfer table")
        expected = "data/balance/" + name.lower() + ".datc64"
        if (
            not isinstance(default_resource, str)
            or default_resource.casefold() != expected
            or not isinstance(localized_resource, str)
            or localized_resource.casefold() != expected.replace("data/balance/", "data/balance/simplified chinese/")
        ):
            raise ValueError("Wrong exact indexed locale resource")
        raw = encoded({"default": default, "localized": localized})
        if len(raw) > 128 * 1024 * 1024:
            raise ValueError("Decoded table pair exceeds transfer bound")
        compressed = zlib.compress(raw, 9)
        if (
            len(compressed) > 16 * 1024 * 1024
            or sum(len(x) for x in self.bodies.values()) + len(compressed) > 32 * 1024 * 1024
        ):
            raise ValueError("Compressed transfer exceeds bound")
        ascii_body = base64.b64encode(compressed).decode("ascii")
        parts = [ascii_body[i : i + 24576] for i in range(0, len(ascii_body), 24576)]

        def meta(table, resource):
            return {
                "raw_resource": resource,
                "raw_identity": table["raw_identity"],
                "rows": len(table["rows"]),
                "columns_sha256": COLUMN_PINS[name],
            }

        entry = {
            "default": meta(default, default_resource),
            "localized": meta(localized, localized_resource),
            "decoded": {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
            "compressed": {"bytes": len(compressed), "sha256": hashlib.sha256(compressed).hexdigest()},
            "parts": [
                {"index": i, "bytes": len(part), "sha256": hashlib.sha256(part.encode("ascii")).hexdigest()}
                for i, part in enumerate(parts)
            ],
        }
        if sum(t["decoded"]["bytes"] for t in self.tables.values()) + len(raw) > 256 * 1024 * 1024:
            raise ValueError("Total decoded transfer exceeds bound")
        self.tables[name], self.bodies[name] = entry, compressed
        return {"table": name, "parts": len(parts), "decoded_bytes": len(raw), "compressed_bytes": len(compressed)}

    def receipt(self):
        if not self.tables:
            raise ValueError("Empty transfer")
        return {
            "format": "repoe-decoded-table-transfer/v1",
            "status": "unreviewed-decoded-observation",
            "observed_client": self.observed_client,
            "language": "Simplified Chinese",
            "decoder": self.decoder,
            "schema": {"revision": SCHEMA_REVISION, "sha256": SCHEMA_SHA256},
            "acquisition_evidence": self.evidence,
            "tables": dict(sorted(self.tables.items())),
            "raw_bytes_transferred": False,
            "patch_certified": False,
            "realm_certified": False,
        }

    def part(self, name, index):
        entry = self.tables[name]
        if type(index) is not int or not 0 <= index < len(entry["parts"]):
            raise ValueError("Invalid requested transfer part")
        data = base64.b64encode(self.bodies[name]).decode("ascii")[index * 24576 : (index + 1) * 24576]
        return {"table": name, "index": index, "data": data}
