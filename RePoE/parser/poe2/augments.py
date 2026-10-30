from PyPoE.poe.file.translations import TranslationFileCache

from RePoE.parser import Parser_Module
from RePoE.parser.util import call_with_default_args, write_any_json


class augments(Parser_Module):
    def write(self) -> None:
        root = {}
        relational_reader = self.relational_reader
        translation_cache = self.get_cache(TranslationFileCache)
        trans_file = translation_cache["stat_descriptions.txt"]

        soul_cores = relational_reader["SoulCores.dat64"]
        soul_core_stats = relational_reader["SoulCoreStats.dat64"]
        if "SoulCore" not in soul_core_stats.index:
            soul_core_stats.build_index("SoulCore")

        for soul_core in soul_cores:
            base_item_type = soul_core["BaseItemType"]
            if base_item_type is None:
                continue
            base_id = base_item_type["Id"]
            if base_id in root:
                raise ValueError(f"Duplicate augment base item: {base_id}")

            obj = {}

            if soul_core["RequiredLevel"]:
                obj["required_level"] = soul_core["RequiredLevel"]
            if soul_core["Type"]:
                obj["type_id"] = soul_core["Type"]["Id"]
                obj["type_name"] = soul_core["Type"]["Name"]
            if soul_core["Limit"]:
                limit_text = soul_core["Limit"]["Text"]
                limit_val = soul_core["Limit"]["Limit"]
                if limit_text:
                    obj["limit"] = limit_text.format(limit_val)
                else:
                    obj["limit"] = str(limit_val)

            categories = {}
            obj["categories"] = categories

            for sc_stat in soul_core_stats.index["SoulCore"].get(soul_core, []):
                category = sc_stat["StatCategory"]
                category_id = category["Id"]
                if category_id in categories:
                    raise ValueError(f"Duplicate augment category: {base_id}/{category_id}")
                results = {}
                categories[category_id] = results
                results["target_item_classes"] = [c["Id"] for c in category["TargetItemClasses"]]
                if category["Display"]:
                    results["target"] = category["Display"]
                else:
                    results["target"] = [c["Name"] for c in category["TargetItemClasses"]]

                for stat_col, value_col, stat_key, text_key in [
                    ("Stats", "StatsValues", "stats", "stat_text"),
                    ("BondedStats", "BondedStatsValues", "bonded_stats", "bonded_stat_text"),
                ]:
                    source_stats = sc_stat[stat_col]
                    values = sc_stat[value_col]
                    if len(source_stats) != len(values):
                        raise ValueError(
                            f"Mismatched augment stat/value lengths: {base_id}/{category_id}/{stat_col}: "
                            f"{len(source_stats)} stats, {len(values)} values"
                        )
                    if not source_stats:
                        continue
                    results[stat_key] = [
                        {"id": stat["Id"], "local": stat["IsLocal"], "value": value}
                        for stat, value in zip(source_stats, values, strict=True)
                    ]
                    stat_ids = [stat["Id"] for stat in source_stats]
                    result = trans_file.get_translation(stat_ids, values, lang=self.language)
                    if hasattr(result, "lines"):
                        lines = result.lines
                    else:
                        lines = result
                    if lines:
                        results[text_key] = lines

            root[base_id] = obj

        write_any_json(root, self.data_path, "augments")


if __name__ == "__main__":
    call_with_default_args(augments)
