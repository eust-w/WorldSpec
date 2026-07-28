//! Canonical JSON and SHA-256 content identity.

use serde::Serialize;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::fmt::{Display, Formatter};

/// Errors produced while canonicalizing a serializable value.
#[derive(Debug)]
pub struct CanonicalError(serde_json::Error);

impl Display for CanonicalError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "canonical JSON serialization failed: {}", self.0)
    }
}

impl std::error::Error for CanonicalError {}

impl From<serde_json::Error> for CanonicalError {
    fn from(value: serde_json::Error) -> Self {
        Self(value)
    }
}

fn sort_value(value: Value) -> Value {
    match value {
        Value::Object(object) => {
            let mut keys = object.keys().cloned().collect::<Vec<_>>();
            keys.sort();
            let mut sorted = Map::new();
            for key in keys {
                if let Some(value) = object.get(&key) {
                    sorted.insert(key, sort_value(value.clone()));
                }
            }
            Value::Object(sorted)
        }
        Value::Array(values) => Value::Array(values.into_iter().map(sort_value).collect()),
        other => other,
    }
}

/// Serialize a value as compact JSON with recursively sorted object keys.
///
/// WorldSpec 0.1 forbids non-finite JSON numbers through its schemas. Arrays
/// retain their declared order because ordering is semantically significant.
pub fn canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>, CanonicalError> {
    let value = serde_json::to_value(value)?;
    Ok(serde_json::to_vec(&sort_value(value))?)
}

/// Compute the normative `sha256:<lowercase hex>` digest of canonical JSON.
pub fn canonical_sha256<T: Serialize>(value: &T) -> Result<String, CanonicalError> {
    let bytes = canonical_json(value)?;
    let digest = Sha256::digest(bytes);
    Ok(format!("sha256:{digest:x}"))
}

#[cfg(test)]
mod tests {
    use super::{canonical_json, canonical_sha256};
    use serde_json::json;

    #[test]
    fn object_key_order_does_not_change_identity() {
        let left = json!({"b": 2, "a": {"d": 4, "c": 3}});
        let right = json!({"a": {"c": 3, "d": 4}, "b": 2});
        assert_eq!(
            canonical_json(&left).unwrap(),
            canonical_json(&right).unwrap()
        );
        assert_eq!(
            canonical_sha256(&left).unwrap(),
            canonical_sha256(&right).unwrap()
        );
    }

    #[test]
    fn array_order_remains_significant() {
        assert_ne!(
            canonical_sha256(&json!([1, 2])).unwrap(),
            canonical_sha256(&json!([2, 1])).unwrap()
        );
    }
}
