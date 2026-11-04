//! Physical table rows and the default passive graph, checked against the authenticated facts.

use std::collections::{BTreeMap, BTreeSet};

use serde::de::DeserializeOwned;
use serde_json::Value;

use super::Profile;
use super::model::{Graph, GraphInput, Group, Identity, InputRef, PassiveInput};
use super::trust::{self, VerifiedInput, require};
use crate::native_facts::{core_skills, gems, items_actors};

pub(crate) fn normalize_graph(
    graph: GraphInput,
    passives: &PassiveInput,
    tables: &Tables<'_>,
    input: &VerifiedInput,
) -> Result<Graph, String> {
    let tree = tables.identity("PassiveSkillTrees", &graph.tree)?;
    require(
        format!("{}.psg", text(&tree["PassiveSkillGraph"])?) == graph.raw_resource,
        "physical Default tree resource mismatch",
    )?;
    require(
        graph.tree.id == "Default"
            && graph.raw_resource == "Metadata/PassiveSkillGraph.psg"
            && graph.header == [3, 0]
            && graph.warnings.is_empty()
            && !graph.radius_semantics.is_empty()
            && graph.parsed_bytes
                == input.manifest["source_identity"]["raw_resources"][&graph.raw_resource]["bytes"],
        "invalid default graph identity/framing",
    )?;
    let instances: BTreeMap<_, _> = passives
        .default_graph_instances
        .iter()
        .map(|i| (i.graph_id, i))
        .collect();
    require(
        instances.len() == passives.default_graph_instances.len(),
        "duplicate graph instance",
    )?;
    // Only instantiated IDs require a unique physical join. Off-graph placeholder IDs
    // may repeat and still represent distinct definitions.
    let mut physical_definitions = BTreeMap::<u64, Vec<usize>>::new();
    for row in 0..tables.len("PassiveSkills") {
        if let Some(id) = tables.row("PassiveSkills", row)?["PassiveSkillGraphId"].as_u64()
            && instances.contains_key(&id)
        {
            physical_definitions.entry(id).or_default().push(row);
        }
    }
    for instance in instances.values() {
        let definitions = physical_definitions.get(&instance.graph_id);
        require(
            definitions.is_some_and(|rows| rows.len() == 1),
            "instantiated graph id must identify exactly one physical definition",
        )?;
        require(
            definitions.is_some_and(|rows| rows[0] == instance.definition.row),
            "instance selected physical definition mismatch",
        )?;
        tables.identity("PassiveSkills", &instance.definition)?;
        require(
            instance.connections.len() == instance.splines.len(),
            "graph connection/spline lengths differ",
        )?;
        for edge in &instance.connections {
            require(instances.contains_key(edge), "unresolved graph edge")?;
        }
    }
    for root in &graph.roots {
        require(
            instances.contains_key(&root.graph_id),
            "unresolved graph root",
        )?;
    }
    let mut seen = BTreeSet::new();
    let mut groups = Vec::new();
    for (index, group) in graph.groups.into_iter().enumerate() {
        require(group.group == index, "graph group order mismatch")?;
        let mut node_order = Vec::new();
        for node in group.nodes {
            require(seen.insert(node.graph_id), "duplicate graph node")?;
            let instance = instances
                .get(&node.graph_id)
                .ok_or("unresolved graph node")?;
            require(
                instance.group == index
                    && instance.radius == node.radius
                    && instance.position == node.position
                    && instance.connections == node.connections
                    && instance.splines == node.splines,
                "graph instance/topology mismatch",
            )?;
            node_order.push(node.graph_id);
        }
        groups.push(Group {
            x_raw: group.x,
            y_raw: group.y,
            flag_raw: group.flag,
            unknown1: group.unknown1,
            unknown2: group.unknown2,
            node_order,
        });
    }
    require(
        seen.len() == instances.len(),
        "graph instances missing from groups",
    )?;
    Ok(Graph {
        tree_id: graph.tree.id,
        raw_tree: InputRef::row("PassiveSkillTrees", graph.tree.row),
        raw: InputRef {
            payload: "graph.json".into(),
            pointer: String::new(),
        },
        header: graph.header,
        skills_per_orbit_raw: graph.skills_per_orbit,
        roots: graph.roots,
        groups,
    })
}

pub(crate) struct Tables<'src> {
    rows: BTreeMap<&'static str, Vec<&'src Value>>,
}

impl<'src> Tables<'src> {
    pub(crate) fn new(input: &'src VerifiedInput) -> Result<Self, String> {
        Self::read(input, &trust::tables(input.profile), true)
    }

    /// Read selected, already authenticated tables with the existing physical-row checks.
    pub(crate) fn selected(
        input: &'src VerifiedInput,
        selected: &[&'static str],
    ) -> Result<Self, String> {
        Self::read(input, selected, false)
    }

    fn read(
        input: &'src VerifiedInput,
        selected: &[&'static str],
        native_projection: bool,
    ) -> Result<Self, String> {
        Self::read_documents(&input.documents, selected, input.profile, native_projection)
    }

    /// Supplemental physical tables use the same row/column checks, without a
    /// full-profile projection or a fabricated parent fact manifest.
    pub(crate) fn selected_documents(
        documents: &'src BTreeMap<String, Value>,
        selected: &[&'static str],
    ) -> Result<Self, String> {
        Self::read_documents(documents, selected, Profile::ItemsActorsBc, false)
    }

    fn read_documents(
        documents: &'src BTreeMap<String, Value>,
        selected: &[&'static str],
        profile: Profile,
        native_projection: bool,
    ) -> Result<Self, String> {
        let mut rows = BTreeMap::new();
        for &table in selected {
            let doc = documents
                .get(&format!("tables/{table}.json"))
                .ok_or_else(|| format!("unverified physical table: {table}"))?;
            trust::exact_keys(
                doc,
                &[
                    "columns",
                    "physical_fields",
                    "raw_resource",
                    "row_key",
                    "rows",
                    "table",
                    "validation",
                ]
                .map(String::from),
            )?;
            require(
                doc["table"] == table
                    && doc["raw_resource"] == format!("Data/Balance/{table}.datc64")
                    && doc["row_key"].is_string(),
                "physical table identity mismatch",
            )?;
            let fields: Vec<String> = decode(&doc["physical_fields"])?;
            if native_projection && profile != Profile::BaseV1 {
                require(
                    core_skills::required_fields(table)
                        .iter()
                        .all(|required| fields.iter().any(|field| field == required)),
                    "missing core-skill physical field",
                )?;
            }
            if native_projection
                && matches!(profile, Profile::GemsConstraintsA1 | Profile::ItemsActorsBc)
            {
                require(
                    gems::required_fields(table)
                        .iter()
                        .all(|required| fields.iter().any(|field| field == required)),
                    "missing gem physical field",
                )?;
            }
            if native_projection && profile == Profile::ItemsActorsBc {
                require(
                    items_actors::required_fields(table)
                        .iter()
                        .all(|required| fields.contains(required)),
                    "missing items/actors physical field",
                )?;
            }
            let unique: BTreeSet<_> = fields.iter().collect();
            require(
                unique.len() == fields.len() && !fields.is_empty(),
                "invalid physical field inventory",
            )?;
            let mut mapped = Vec::new();
            for (index, column) in array(&doc["columns"])?.iter().enumerate() {
                require(
                    column["source_column"] == index && column["schema"].is_object(),
                    "invalid physical column metadata",
                )?;
                let column_fields: Vec<String> = decode(&column["physical_fields"])?;
                mapped.extend(column_fields);
            }
            require(mapped == fields, "physical column mapping mismatch")?;
            let source_rows = array(&doc["rows"])?;
            let validation = &doc["validation"];
            require(
                validation["rows"] == source_rows.len()
                    && validation["warnings"] == serde_json::json!([])
                    && validation["schema_row_bytes"]
                        .as_u64()
                        .is_some_and(|v| v > 0)
                    && if profile == Profile::ItemsActorsBc && source_rows.is_empty() {
                        validation["actual_row_bytes"] == 0
                    } else {
                        validation["schema_row_bytes"] == validation["actual_row_bytes"]
                    },
                "physical table validation failed",
            )?;
            let mut values = Vec::new();
            let mut ids = BTreeSet::new();
            for (index, row) in source_rows.iter().enumerate() {
                trust::exact_keys(row, &["_row".into(), "values".into()])?;
                require(row["_row"] == index, "physical row order mismatch")?;
                trust::exact_keys(&row["values"], &fields)?;
                if fields.iter().any(|f| f == "Id") {
                    if profile == Profile::ItemsActorsBc && table == "SummonedSpecificMonsters" {
                        require(
                            row["values"]["Id"].is_i64() || row["values"]["Id"].is_u64(),
                            "invalid numeric summoned-monster Id",
                        )?;
                    } else {
                        let id = text(&row["values"]["Id"])?;
                        require(
                            !id.is_empty() && ids.insert(id),
                            "empty or duplicate stable game id",
                        )?;
                    }
                }
                values.push(&row["values"]);
            }
            rows.insert(table, values);
        }
        Ok(Self { rows })
    }

    pub(crate) fn len(&self, table: &str) -> usize {
        self.rows[table].len()
    }

    pub(crate) fn row(&self, table: &str, row: usize) -> Result<&'src Value, String> {
        self.rows
            .get(table)
            .ok_or_else(|| format!("unverified physical table: {table}"))?
            .get(row)
            .copied()
            .ok_or_else(|| format!("unresolved physical row {table}/{row}"))
    }

    pub(crate) fn identity(&self, table: &str, identity: &Identity) -> Result<&'src Value, String> {
        let row = self.row(table, identity.row)?;
        require(
            row["Id"] == identity.id,
            &format!("{table} stable id/row mismatch"),
        )?;
        Ok(row)
    }
}

pub(crate) fn decode<T: DeserializeOwned>(value: &Value) -> Result<T, String> {
    T::deserialize(value).map_err(|e| e.to_string())
}

pub(crate) fn array(value: &Value) -> Result<&[Value], String> {
    value
        .as_array()
        .map(Vec::as_slice)
        .ok_or_else(|| "expected array".into())
}

pub(crate) fn text(value: &Value) -> Result<&str, String> {
    value
        .as_str()
        .ok_or_else(|| "expected stable string id".into())
}
