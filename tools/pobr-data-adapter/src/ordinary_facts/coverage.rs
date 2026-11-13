//! Strict/forward decisions for per-entity content gaps, and the coverage report.
//!
//! `--mode strict` (the default) keeps today's behaviour: a converter fails at its
//! first content gap with its existing error string. `--mode forward` records the
//! same gap as an [`Issue`] and lets the converter carry on with the forward action
//! the issue names, so one run reports every gap (`docs/ordinary-coverage.md`).
//!
//! A converter routes only enumerated per-entity content decisions through
//! [`Coverage::decide`], at the exact program point that returns the error today:
//!
//! ```text
//! // before: return Err(message);
//! coverage.decide(Issue::new(KIND, entity, Action::Quarantined, message))?;
//! // forward only from here: omit the entity, keep the legacy entry, ...
//! ```
//!
//! Integrity errors (pins, envelopes, column contracts, duplicate keys, dangling
//! foreign keys) never go through `Coverage`; they fail in both modes. Forward mode
//! is never implemented by catching a converter's `Err(String)`.
//!
//! Frozen interface (domain PRs build on it; change it only together with the
//! release aggregator and `docs/ordinary-coverage.md`):
//! - [`Issue`]: `domain` (the domain label, stamped by `Coverage`; it equals the
//!   `--ordinary-domain` value for every converter that takes `Coverage`),
//!   `kind` (stable kebab-case name of the decision site), `entity` (the stable
//!   business identity a policy entry would key on, never a bare physical row),
//!   `action` ([`Action`]), `message` (exactly the strict error string) and
//!   optional `observed` (a free-form JSON object with sorted keys holding the
//!   values needed to write the policy entry, for example `definition_sha256` or
//!   `candidate_lines`; omitted when empty).
//! - `conversion.coverage`, written by [`Coverage::finish`] in forward mode only:
//!   `{"format":"pobr-adapter-coverage/v1","counts":{<every action>:n},"issues":[..]}`,
//!   issues sorted by (`domain`, `kind`, `entity`, `action`, `message`).

use std::collections::BTreeMap;

use serde::Serialize;
use serde_json::{Value, json};

/// Format tag of the `conversion.coverage` object.
pub(crate) const FORMAT: &str = "pobr-adapter-coverage/v1";

/// How a converter treats a per-entity content gap (`--mode`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum AdapterMode {
    /// Fail at the first gap with today's error string; the receipt is unchanged.
    Strict,
    /// Record every gap as an issue in `conversion.coverage` and continue.
    Forward,
}

/// What forward mode did with the entity an issue names.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum Action {
    /// The entity is omitted from the output.
    Quarantined,
    /// The entity is emitted, but some of its fields are not owned.
    EmittedWithGap,
    /// The old entry is kept unchanged.
    RetainedLegacy,
    /// Informational only; the output is unaffected.
    Listed,
}

impl Action {
    const ALL: [Self; 4] = [
        Self::Quarantined,
        Self::EmittedWithGap,
        Self::RetainedLegacy,
        Self::Listed,
    ];

    fn name(self) -> &'static str {
        match self {
            Self::Quarantined => "quarantined",
            Self::EmittedWithGap => "emitted-with-gap",
            Self::RetainedLegacy => "retained-legacy",
            Self::Listed => "listed",
        }
    }
}

/// One per-entity content gap. `domain` is stamped by [`Coverage`].
#[derive(Debug, Clone, PartialEq, Serialize)]
pub(crate) struct Issue {
    domain: &'static str,
    kind: &'static str,
    entity: String,
    action: Action,
    message: String,
    #[serde(skip_serializing_if = "BTreeMap::is_empty")]
    observed: BTreeMap<String, Value>,
}

// Removed by item 5 P10 once the wave-1 callers are merged.
#[cfg_attr(not(test), allow(dead_code))]
impl Issue {
    /// `message` must be exactly the error string strict mode returns at this site.
    pub(crate) fn new(
        kind: &'static str,
        entity: impl Into<String>,
        action: Action,
        message: impl Into<String>,
    ) -> Self {
        Self {
            domain: "",
            kind,
            entity: entity.into(),
            action,
            message: message.into(),
            observed: BTreeMap::new(),
        }
    }

    /// Adds one observed value needed to write the policy entry that closes the issue
    /// (a hash, a list of candidate lines, a field list, ...). Free-form JSON.
    pub(crate) fn observed(mut self, field: impl Into<String>, value: impl Into<Value>) -> Self {
        self.observed.insert(field.into(), value.into());
        self
    }

    /// Sort key: plain string order, so another tool can reproduce it.
    fn key(&self) -> [&str; 5] {
        [
            self.domain,
            self.kind,
            &self.entity,
            self.action.name(),
            &self.message,
        ]
    }
}

/// Per-run decision point and issue collector for one domain.
pub(crate) struct Coverage {
    mode: AdapterMode,
    domain: &'static str,
    issues: Vec<Issue>,
}

impl Coverage {
    /// Whether this run records content gaps and continues.
    pub(crate) fn is_forward(&self) -> bool {
        self.mode == AdapterMode::Forward
    }

    /// `domain` is the `--ordinary-domain` value, stamped on every issue.
    pub(crate) fn new(mode: AdapterMode, domain: &'static str) -> Self {
        Self {
            mode,
            domain,
            issues: Vec::new(),
        }
    }

    /// A content gap that fails today. Strict: `Err(issue.message)`, the unchanged
    /// error at the unchanged program point. Forward: records the issue, `Ok(())`.
    #[cfg_attr(not(test), allow(dead_code))]
    pub(crate) fn decide(&mut self, issue: Issue) -> Result<(), String> {
        match self.mode {
            AdapterMode::Strict => Err(issue.message),
            AdapterMode::Forward => {
                self.record(issue);
                Ok(())
            }
        }
    }

    /// A gap that does not fail today (for example a new entity that is only
    /// counted). Strict: ignored, so strict receipts stay unchanged. Forward: recorded.
    #[cfg_attr(not(test), allow(dead_code))]
    pub(crate) fn note(&mut self, issue: Issue) {
        if self.mode == AdapterMode::Forward {
            self.record(issue);
        }
    }

    fn record(&mut self, mut issue: Issue) {
        issue.domain = self.domain;
        self.issues.push(issue);
    }

    /// Forward: writes `conversion.coverage` (also when there are no issues).
    /// Strict: leaves `conversion` untouched.
    pub(crate) fn finish(mut self, conversion: &mut Value) -> Result<(), String> {
        if self.mode == AdapterMode::Strict {
            return Ok(());
        }
        let conversion = conversion
            .as_object_mut()
            .ok_or("forward coverage needs an object conversion receipt")?;
        if conversion.contains_key("coverage") {
            return Err("conversion receipt already has a coverage field".into());
        }
        self.issues.sort_by(|a, b| a.key().cmp(&b.key()));
        let counts: BTreeMap<_, _> = Action::ALL
            .into_iter()
            .map(|action| {
                let n = self.issues.iter().filter(|i| i.action == action).count();
                (action.name(), n)
            })
            .collect();
        conversion.insert(
            "coverage".into(),
            json!({"format":FORMAT, "counts":counts, "issues":self.issues}),
        );
        Ok(())
    }
}

#[cfg(all(test, any(target_os = "linux", target_os = "macos")))]
mod tests;
