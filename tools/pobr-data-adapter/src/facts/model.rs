//! Physical passive-tree input shapes and stable references into the authenticated facts.

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// References are resolved only against the input manifest pinned in the candidate receipt.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct InputRef {
    pub payload: String,
    pub pointer: String,
}

impl InputRef {
    pub fn row(table: &str, row: usize) -> Self {
        Self {
            payload: format!("tables/{table}.json"),
            pointer: format!("/rows/{row}/values"),
        }
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub(crate) struct Graph {
    pub tree_id: String,
    pub raw_tree: InputRef,
    pub raw: InputRef,
    pub header: Vec<u64>,
    pub skills_per_orbit_raw: Vec<u64>,
    pub roots: Vec<Root>,
    pub groups: Vec<Group>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Root {
    pub graph_id: u64,
    pub unknown: u64,
}

#[derive(Debug, Serialize, Deserialize)]
pub(crate) struct Group {
    pub x_raw: f64,
    pub y_raw: f64,
    pub flag_raw: u64,
    pub unknown1: u64,
    pub unknown2: i64,
    pub node_order: Vec<u64>,
}

// The v1 projection is deliberately strict; unknown physical metadata remains accessible
// through InputRef rather than being interpreted or duplicated in this candidate schema.
#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(crate) struct Identity {
    pub row: usize,
    pub id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PassiveInput {
    #[expect(
        dead_code,
        reason = "decoded only so that passives.json keeps its exact shape"
    )]
    pub definitions: Vec<DefinitionInput>,
    pub default_graph_instances: Vec<InstanceInput>,
    #[expect(
        dead_code,
        reason = "decoded only so that passives.json keeps its exact shape"
    )]
    pub class_overrides: Vec<ClassInput>,
}

#[expect(
    dead_code,
    reason = "decoded only so that passives.json keeps its exact shape"
)]
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct DefinitionInput {
    pub definition: Identity,
    pub graph_id: u64,
    pub in_default_graph: bool,
    pub stats: Vec<PassiveStatInput>,
}

#[expect(
    dead_code,
    reason = "decoded only so that passives.json keeps its exact shape"
)]
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PassiveStatInput {
    pub slot: usize,
    pub value_field: String,
    pub stat: Identity,
    pub value: i64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct InstanceInput {
    pub definition: Identity,
    pub graph_id: u64,
    pub group: usize,
    pub radius: u64,
    pub position: u64,
    pub connections: Vec<u64>,
    pub splines: Vec<i64>,
}

#[expect(
    dead_code,
    reason = "decoded only so that passives.json keeps its exact shape"
)]
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ClassInput {
    pub row: usize,
    pub character: Identity,
    pub base: Identity,
    pub replacement: Identity,
    pub base_graph_id: u64,
    pub replacement_graph_id: u64,
    pub base_in_default_graph: bool,
    pub replacement_in_default_graph: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct GraphInput {
    pub tree: Identity,
    pub raw_resource: String,
    pub header: Vec<u64>,
    pub skills_per_orbit: Vec<u64>,
    pub roots: Vec<Root>,
    pub groups: Vec<GroupInput>,
    pub parsed_bytes: u64,
    pub radius_semantics: String,
    pub warnings: Vec<Value>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct GroupInput {
    pub group: usize,
    pub x: f64,
    pub y: f64,
    pub flag: u64,
    pub unknown1: u64,
    pub unknown2: i64,
    pub nodes: Vec<NodeInput>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct NodeInput {
    pub graph_id: u64,
    pub radius: u64,
    pub position: u64,
    pub connections: Vec<u64>,
    pub splines: Vec<i64>,
}
