//! Normalize stable identities and relationships, checking projected facts against sealed tables.

use std::collections::{BTreeMap, BTreeSet};

use serde_json::Value;

use super::model::{
    Candidate, ChannelInput, ClassRelation, Effect, GraphInput, InputRef, Instance, LinkInput,
    Passive, PassiveInput, PassiveStat, Quality, QualityChannel, QualityStat, SkillsInput, StatSet,
    StatSetLink, Summary,
};
use super::trust::{VerifiedInput, require};
use super::{Profile, core_skills, gems, items_actors};
use crate::facts::physical::{Tables, array, decode, normalize_graph, text};

pub(super) fn normalize(input: &VerifiedInput) -> Result<Candidate, String> {
    let tables = Tables::new(input)?;
    let passives: PassiveInput = decode(&input.documents["passives.json"])?;
    let skills: SkillsInput = decode(&input.documents["skills.json"])?;
    let graph: GraphInput = decode(&input.documents["graph.json"])?;
    let mut candidate = Candidate {
        format: "pobr-native-domain-candidate/v1".into(),
        input_manifest_sha256: crate::raw_source::sha256_hex(&input.manifest_bytes),
        summary: Summary {
            passive_definitions: 0,
            graph_instances: 0,
            graph_stat_entries: 0,
            class_overrides: 0,
            effects: 0,
            qualities: 0,
        },
        passive_order: Vec::new(),
        passives: BTreeMap::new(),
        graph: normalize_graph(graph, &passives, &tables, input)?,
        instances: Vec::new(),
        class_relations: Vec::new(),
        effect_order: Vec::new(),
        effects: BTreeMap::new(),
        stat_set_order: Vec::new(),
        stat_sets: BTreeMap::new(),
        qualities: Vec::new(),
        source_diagnostics: "source-diagnostics.json".into(),
        core_skills: None,
        core_summary: None,
        gems: None,
        constraints: None,
        gem_summary: None,
        items: None,
        actors: None,
        items_actors_summary: None,
    };
    require(
        passives.definitions.len() == tables.len("PassiveSkills"),
        "incomplete passive definitions",
    )?;
    let instance_ids: BTreeSet<_> = passives
        .default_graph_instances
        .iter()
        .map(|i| i.graph_id)
        .collect();
    for (row, definition) in passives.definitions.into_iter().enumerate() {
        require(
            definition.definition.row == row,
            "passive definition order mismatch",
        )?;
        let raw = tables.identity("PassiveSkills", &definition.definition)?;
        require(
            raw["PassiveSkillGraphId"] == definition.graph_id,
            "passive graph id mismatch",
        )?;
        require(
            definition.in_default_graph == instance_ids.contains(&definition.graph_id),
            "passive graph membership mismatch",
        )?;
        let raw_stats = array(&raw["Stats"])?;
        require(
            raw_stats.len() == definition.stats.len(),
            "passive stats truncated",
        )?;
        let mut stats = Vec::new();
        for (index, stat) in definition.stats.into_iter().enumerate() {
            tables.identity("Stats", &stat.stat)?;
            require(
                stat.slot == index + 1 && stat.value_field == format!("Stat{}Value", stat.slot),
                "passive slot mismatch",
            )?;
            require(
                raw_stats[index] == stat.stat.row && raw[&stat.value_field] == stat.value,
                "passive stat/value mismatch",
            )?;
            stats.push(PassiveStat {
                stat_id: stat.stat.id,
                raw_stat: InputRef::row("Stats", stat.stat.row),
                slot: stat.slot,
                value_field: stat.value_field,
                value: stat.value,
            });
        }
        candidate
            .passive_order
            .push(definition.definition.id.clone());
        candidate.passives.insert(
            definition.definition.id,
            Passive {
                raw: InputRef::row("PassiveSkills", row),
                graph_id_raw: definition.graph_id,
                in_default_graph: definition.in_default_graph,
                stats,
            },
        );
    }
    for instance in passives.default_graph_instances {
        tables.identity("PassiveSkills", &instance.definition)?;
        let definition = candidate
            .passives
            .get(&instance.definition.id)
            .ok_or("unknown instance definition")?;
        require(
            definition.graph_id_raw == instance.graph_id && definition.in_default_graph,
            "instance definition mismatch",
        )?;
        candidate.summary.graph_stat_entries += definition.stats.len();
        candidate.instances.push(Instance {
            graph_id: instance.graph_id,
            definition_id: instance.definition.id,
            group: instance.group,
            radius_raw: instance.radius,
            position_raw: instance.position,
            connections: instance.connections,
            splines: instance.splines,
        });
    }
    require(
        passives.class_overrides.len() == tables.len("ClassPassiveSkillOverrides"),
        "class rows truncated",
    )?;
    for (row, relation) in passives.class_overrides.into_iter().enumerate() {
        require(row == relation.row, "class relation order mismatch")?;
        let raw = tables.row("ClassPassiveSkillOverrides", row)?;
        tables.identity("Characters", &relation.character)?;
        tables.identity("PassiveSkills", &relation.base)?;
        tables.identity("PassiveSkills", &relation.replacement)?;
        require(
            raw["CharacterToOverrideFor"] == relation.character.row
                && raw["SkillToOverride"] == relation.base.row
                && raw["Override"] == relation.replacement.row,
            "class foreign-key mismatch",
        )?;
        for (id, graph_id, member) in [
            (
                &relation.base.id,
                relation.base_graph_id,
                relation.base_in_default_graph,
            ),
            (
                &relation.replacement.id,
                relation.replacement_graph_id,
                relation.replacement_in_default_graph,
            ),
        ] {
            let definition = candidate
                .passives
                .get(id)
                .ok_or("unknown class definition")?;
            require(
                definition.graph_id_raw == graph_id && definition.in_default_graph == member,
                "class graph membership mismatch",
            )?;
        }
        candidate.class_relations.push(ClassRelation {
            raw: InputRef::row("ClassPassiveSkillOverrides", row),
            character_id: relation.character.id,
            raw_character: InputRef::row("Characters", relation.character.row),
            base_definition_id: relation.base.id,
            replacement_definition_id: relation.replacement.id,
            base_graph_id: relation.base_graph_id,
            replacement_graph_id: relation.replacement_graph_id,
            base_in_default_graph: relation.base_in_default_graph,
            replacement_in_default_graph: relation.replacement_in_default_graph,
        });
    }
    for row in 0..tables.len("GrantedEffectStatSets") {
        let id = text(&tables.row("GrantedEffectStatSets", row)?["Id"])?;
        candidate.stat_set_order.push(id.into());
        candidate.stat_sets.insert(
            id.into(),
            StatSet {
                raw: InputRef::row("GrantedEffectStatSets", row),
            },
        );
    }
    require(
        skills.effects.len() == tables.len("GrantedEffects"),
        "effects truncated",
    )?;
    for (row, effect) in skills.effects.into_iter().enumerate() {
        require(effect.effect.row == row, "effect order mismatch")?;
        let raw = tables.identity("GrantedEffects", &effect.effect)?;
        let links = normalize_links(&effect.ordered_stat_sets, raw, &tables)?;
        candidate.effect_order.push(effect.effect.id.clone());
        candidate.effects.insert(
            effect.effect.id,
            Effect {
                raw: InputRef::row("GrantedEffects", row),
                ordered_stat_sets: links,
            },
        );
    }
    require(
        skills.qualities.len() == tables.len("GrantedEffectQualityStats"),
        "quality rows truncated",
    )?;
    for (row, quality) in skills.qualities.into_iter().enumerate() {
        require(quality.row == row, "quality order mismatch")?;
        let raw = tables.row("GrantedEffectQualityStats", row)?;
        let effect_raw = tables.identity("GrantedEffects", &quality.effect)?;
        require(
            raw["GrantedEffect"] == quality.effect.row,
            "quality effect mismatch",
        )?;
        let links = normalize_links(&quality.ordered_stat_sets, effect_raw, &tables)?;
        require(
            candidate
                .effects
                .get(&quality.effect.id)
                .is_some_and(|e| e.ordered_stat_sets == links),
            "quality ordered stat sets mismatch",
        )?;
        candidate.qualities.push(Quality {
            raw: InputRef::row("GrantedEffectQualityStats", row),
            effect_id: quality.effect.id,
            main: normalize_channel(
                quality.main,
                raw,
                ["ApplyToStatSets", "Stats", "StatsValuesPermille"],
                &tables,
            )?,
            alternate: normalize_channel(
                quality.alternate,
                raw,
                ["AltApplyToStatSets", "AltStats", "AltStatValuesPermille"],
                &tables,
            )?,
        });
    }
    // Preserve the entire diagnostics document byte-for-byte, including unknown diagnostic shapes.
    require(
        input.documents["diagnostics.json"]["diagnostics"].is_array()
            && input.documents["diagnostics.json"]["scope"] == input.manifest["scope"],
        "source diagnostics/scope mismatch",
    )?;
    candidate.summary.passive_definitions = candidate.passives.len();
    candidate.summary.graph_instances = candidate.instances.len();
    candidate.summary.class_overrides = candidate.class_relations.len();
    candidate.summary.effects = candidate.effects.len();
    candidate.summary.qualities = candidate.qualities.len();
    let mut source_summary = input.manifest["summary"].clone();
    if input.profile != Profile::BaseV1 {
        let (core, summary) = core_skills::normalize(input, &tables)?;
        let counts = serde_json::to_value(&summary).map_err(|e| e.to_string())?;
        for (key, value) in counts.as_object().ok_or("invalid core summary")? {
            require(
                source_summary[key] == *value,
                "core counts differ from source summary",
            )?;
            source_summary
                .as_object_mut()
                .ok_or("invalid source summary")?
                .remove(key);
        }
        candidate.format = "pobr-native-domain-candidate/v2".into();
        candidate.core_skills = Some(core);
        candidate.core_summary = Some(summary);
    }
    if matches!(
        input.profile,
        Profile::GemsConstraintsA1 | Profile::ItemsActorsBc
    ) {
        let (projection, summary) = gems::normalize(input, &tables)?;
        let counts = serde_json::to_value(&summary).map_err(|e| e.to_string())?;
        for (key, value) in counts.as_object().ok_or("invalid gem summary")? {
            require(
                source_summary[key] == *value,
                "gem counts differ from source summary",
            )?;
            source_summary
                .as_object_mut()
                .ok_or("invalid source summary")?
                .remove(key);
        }
        candidate.format = "pobr-native-domain-candidate/v3".into();
        candidate.gems = Some(projection.gems);
        candidate.constraints = Some(projection.constraints);
        candidate.gem_summary = Some(summary);
    }
    if input.profile == Profile::ItemsActorsBc {
        let (projection, summary) = items_actors::normalize(input, &tables)?;
        let counts = serde_json::to_value(&summary).map_err(|e| e.to_string())?;
        for (key, value) in counts.as_object().ok_or("invalid items/actors summary")? {
            require(
                source_summary[key] == *value,
                "items/actors counts differ from source summary",
            )?;
            source_summary
                .as_object_mut()
                .ok_or("invalid source summary")?
                .remove(key);
        }
        candidate.format = "pobr-native-domain-candidate/v4".into();
        candidate.items = Some(projection.items);
        candidate.actors = Some(projection.actors);
        candidate.items_actors_summary = Some(summary);
    }
    let expected: Summary = decode(&source_summary)?;
    require(
        candidate.summary == expected,
        "measured projection counts differ from source summary",
    )?;
    Ok(candidate)
}

fn normalize_channel(
    input: ChannelInput,
    raw: &Value,
    fields: [&str; 3],
    tables: &Tables<'_>,
) -> Result<QualityChannel, String> {
    require(
        serde_json::to_value(&input.scope_raw).map_err(|e| e.to_string())? == raw[fields[0]],
        "quality raw scope mismatch",
    )?;
    let raw_stats = array(&raw[fields[1]])?;
    let raw_values = array(&raw[fields[2]])?;
    require(
        raw_stats.len() == input.stats.len() && raw_values.len() == input.stats.len(),
        "quality stats truncated or unequal",
    )?;
    let mut stats = Vec::new();
    for (slot, stat) in input.stats.into_iter().enumerate() {
        tables.identity("Stats", &stat.stat)?;
        require(
            stat.slot == slot
                && raw_stats[slot] == stat.stat.row
                && raw_values[slot] == stat.value_permille,
            "quality stat/value mismatch",
        )?;
        stats.push(QualityStat {
            stat_id: stat.stat.id,
            raw_stat: InputRef::row("Stats", stat.stat.row),
            slot,
            value_permille: stat.value_permille,
        });
    }
    Ok(QualityChannel {
        scope_raw: input.scope_raw,
        stats,
    })
}

fn normalize_links(
    links: &[LinkInput],
    raw: &Value,
    tables: &Tables<'_>,
) -> Result<Vec<StatSetLink>, String> {
    let mut expected = Vec::new();
    if !raw["StatSet"].is_null() {
        expected.push(("StatSet", None, &raw["StatSet"]));
    }
    for (slot, value) in array(&raw["AdditionalStatSets"])?.iter().enumerate() {
        if !value.is_null() {
            expected.push(("AdditionalStatSets", Some(slot), value));
        }
    }
    require(
        expected.len() == links.len(),
        "effect stat-set identities truncated",
    )?;
    links
        .iter()
        .zip(expected)
        .map(|(link, (field, slot, row))| {
            tables.identity("GrantedEffectStatSets", &link.stat_set)?;
            // The producer's index is explicitly a hypothesis; preserve it without interpreting scopes.
            require(
                link.source_field == field && link.source_slot == slot && *row == link.stat_set.row,
                "effect stat-set identity/order mismatch",
            )?;
            Ok(StatSetLink {
                stat_set_id: link.stat_set.id.clone(),
                source_field: link.source_field.clone(),
                source_slot: link.source_slot,
                local_index_hypothesis: link.local_index_hypothesis,
            })
        })
        .collect()
}
