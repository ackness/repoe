//! Bounded, externally pinned supplemental inputs. No formatter is executed.

use std::fs::{self, File};
use std::io::{Read, Take};
use std::path::{Component, Path};

use serde_json::Value;

use super::trust::require;
use crate::raw_source::sha256_hex;

pub(crate) fn pinned_bytes(path: &Path, expected: &str, cap: u64) -> Result<Vec<u8>, String> {
    check_sha(expected)?;
    let mut bytes = Vec::new();
    open(path, cap)?
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    require(bytes.len() as u64 <= cap, "supplement exceeds byte limit")?;
    require(sha256_hex(&bytes) == expected, "supplement sha256 mismatch")?;
    Ok(bytes)
}

fn check_sha(value: &str) -> Result<(), String> {
    require(
        value.len() == 64
            && value
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)),
        "invalid supplemental sha256",
    )
}

fn open(path: &Path, cap: u64) -> Result<Take<File>, String> {
    let absolute = std::path::absolute(path).map_err(|e| e.to_string())?;
    let mut current = std::path::PathBuf::new();
    for component in absolute.components() {
        require(
            matches!(component, Component::RootDir | Component::Normal(_)),
            "supplement traversal is forbidden",
        )?;
        current.push(component.as_os_str());
        require(
            !fs::symlink_metadata(&current)
                .map_err(|e| e.to_string())?
                .is_symlink(),
            "supplement symlinks are forbidden",
        )?;
    }
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    let file = File::from(
        rustix::fs::open(
            path,
            rustix::fs::OFlags::RDONLY
                | rustix::fs::OFlags::NONBLOCK
                | rustix::fs::OFlags::NOFOLLOW
                | rustix::fs::OFlags::CLOEXEC,
            rustix::fs::Mode::empty(),
        )
        .map_err(|e| format!("{}: {e}", path.display()))?,
    );
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    let file = File::open(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let metadata = file.metadata().map_err(|e| e.to_string())?;
    require(
        metadata.is_file() && metadata.len() <= cap,
        "supplement must be a bounded regular file",
    )?;
    Ok(file.take(cap.checked_add(1).ok_or("supplement size overflow")?))
}

pub(crate) fn index(value: &Value) -> Result<usize, String> {
    value
        .as_u64()
        .and_then(|v| usize::try_from(v).ok())
        .ok_or_else(|| format!("expected physical row index, got {value}"))
}
