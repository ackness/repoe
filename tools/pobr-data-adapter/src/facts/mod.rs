//! Authenticated RePoE facts input: envelope and source-lock verification, selected
//! physical tables, the player context archive and guarded output directories.

mod inputs;
mod model;
mod output;
mod physical;
pub(crate) mod player;
pub(crate) mod reader;
mod trust;

pub(crate) use output::Output;

fn json_bytes(value: &impl serde::Serialize) -> Result<Vec<u8>, String> {
    let mut bytes = serde_json::to_vec(value).map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    Ok(bytes)
}
