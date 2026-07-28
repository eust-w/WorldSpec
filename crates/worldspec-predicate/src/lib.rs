//! Deterministic reference evaluators for versioned WorldSpec predicates.
//!
//! The reference engine consumes canonical evidence, not simulator-native
//! booleans. Backend adapters are responsible for producing that evidence.

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Truth {
    True,
    False,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PredicateResult {
    pub truth: Truth,
    pub robustness: Option<f64>,
    pub confidence: f64,
    pub evidence: Vec<String>,
    pub diagnostics: Vec<String>,
}

impl PredicateResult {
    fn known(robustness: f64, confidence: f64, evidence: &[&str]) -> Self {
        Self {
            truth: if robustness >= 0.0 {
                Truth::True
            } else {
                Truth::False
            },
            robustness: Some(robustness),
            confidence: confidence.clamp(0.0, 1.0),
            evidence: evidence.iter().map(|item| (*item).to_owned()).collect(),
            diagnostics: Vec::new(),
        }
    }

    fn unknown(reason: impl Into<String>) -> Self {
        Self {
            truth: Truth::Unknown,
            robustness: None,
            confidence: 0.0,
            evidence: Vec::new(),
            diagnostics: vec![reason.into()],
        }
    }
}

fn finite(values: &[f64]) -> bool {
    values.iter().all(|value| value.is_finite())
}

fn number(evidence: &Value, key: &str) -> Option<f64> {
    evidence.get(key).and_then(Value::as_f64)
}

fn boolean(evidence: &Value, key: &str) -> Option<bool> {
    evidence.get(key).and_then(Value::as_bool)
}

fn threshold(profile: &Value, key: &str) -> Option<f64> {
    profile.pointer(&format!("/thresholds/{key}"))?.as_f64()
}

fn confidence(evidence: &Value) -> f64 {
    evidence
        .get("confidence")
        .and_then(Value::as_f64)
        .unwrap_or(1.0)
}

/// Evaluate a canonical predicate by its stable predicate ID.
///
/// Supported v0.1 predicates deliberately cover the evidence needed by the
/// first rigid manipulation task. Missing or non-finite evidence returns
/// `unknown`; it never silently becomes `false`.
pub fn evaluate(predicate_id: &str, profile: &Value, evidence: &Value) -> PredicateResult {
    match predicate_id {
        "predicate://worldspec/stable" => stable(profile, evidence),
        "predicate://worldspec/open" => open(profile, evidence),
        "predicate://worldspec/closed" => closed(profile, evidence),
        "predicate://worldspec/inside" => inside(profile, evidence),
        "predicate://worldspec/released" => released(evidence),
        "predicate://worldspec/upright" => upright(profile, evidence),
        "predicate://worldspec/finite" => finite_state(evidence),
        "predicate://worldspec/within_limits" => within_limits(evidence),
        "predicate://worldspec/no_dangerous_collision" => no_dangerous_collision(evidence),
        "predicate://worldspec/no_excessive_penetration" => {
            no_excessive_penetration(profile, evidence)
        }
        _ => PredicateResult::unknown(format!("unsupported predicate: {predicate_id}")),
    }
}

fn stable(profile: &Value, evidence: &Value) -> PredicateResult {
    let Some(linear_speed) = number(evidence, "linearSpeed") else {
        return PredicateResult::unknown("stable requires linearSpeed");
    };
    let Some(angular_speed) = number(evidence, "angularSpeed") else {
        return PredicateResult::unknown("stable requires angularSpeed");
    };
    let Some(pose_drift) = number(evidence, "poseDrift") else {
        return PredicateResult::unknown("stable requires poseDrift");
    };
    let Some(max_linear) = threshold(profile, "maximumLinearSpeed") else {
        return PredicateResult::unknown("stable profile lacks maximumLinearSpeed");
    };
    let Some(max_angular) = threshold(profile, "maximumAngularSpeed") else {
        return PredicateResult::unknown("stable profile lacks maximumAngularSpeed");
    };
    let Some(max_drift) = threshold(profile, "maximumPoseDrift") else {
        return PredicateResult::unknown("stable profile lacks maximumPoseDrift");
    };
    if !finite(&[
        linear_speed,
        angular_speed,
        pose_drift,
        max_linear,
        max_angular,
        max_drift,
    ]) {
        return PredicateResult::unknown("stable evidence contains a non-finite number");
    }
    PredicateResult::known(
        (max_linear - linear_speed)
            .min(max_angular - angular_speed)
            .min(max_drift - pose_drift),
        confidence(evidence),
        &["linearSpeed", "angularSpeed", "poseDrift"],
    )
}

fn normalized_openness(profile: &Value, evidence: &Value, mode: &str) -> PredicateResult {
    let Some(openness) = number(evidence, "normalizedOpenness") else {
        return PredicateResult::unknown(format!("{mode} requires normalizedOpenness"));
    };
    if !openness.is_finite() || !(0.0..=1.0).contains(&openness) {
        return PredicateResult::unknown("normalizedOpenness must be finite and within [0, 1]");
    }
    let (key, robustness) = if mode == "open" {
        let Some(minimum) = threshold(profile, "minimumOpenness") else {
            return PredicateResult::unknown("open profile lacks minimumOpenness");
        };
        ("normalizedOpenness", openness - minimum)
    } else {
        let Some(maximum) = threshold(profile, "maximumOpenness") else {
            return PredicateResult::unknown("closed profile lacks maximumOpenness");
        };
        ("normalizedOpenness", maximum - openness)
    };
    PredicateResult::known(
        robustness,
        confidence(evidence),
        &[key, "assetOpennessMapping"],
    )
}

fn open(profile: &Value, evidence: &Value) -> PredicateResult {
    normalized_openness(profile, evidence, "open")
}

fn closed(profile: &Value, evidence: &Value) -> PredicateResult {
    normalized_openness(profile, evidence, "closed")
}

fn inside(profile: &Value, evidence: &Value) -> PredicateResult {
    let Some(containment) = number(evidence, "containmentRatio") else {
        return PredicateResult::unknown("inside requires containmentRatio");
    };
    let Some(clearance) = number(evidence, "minimumClearance") else {
        return PredicateResult::unknown("inside requires minimumClearance");
    };
    let Some(penetration) = number(evidence, "maximumWallPenetration") else {
        return PredicateResult::unknown("inside requires maximumWallPenetration");
    };
    let Some(min_containment) = threshold(profile, "minimumContainmentRatio") else {
        return PredicateResult::unknown("inside profile lacks minimumContainmentRatio");
    };
    let Some(min_clearance) = threshold(profile, "minimumClearance") else {
        return PredicateResult::unknown("inside profile lacks minimumClearance");
    };
    let Some(max_penetration) = threshold(profile, "maximumWallPenetration") else {
        return PredicateResult::unknown("inside profile lacks maximumWallPenetration");
    };
    if !finite(&[
        containment,
        clearance,
        penetration,
        min_containment,
        min_clearance,
        max_penetration,
    ]) {
        return PredicateResult::unknown("inside evidence contains a non-finite number");
    }
    PredicateResult::known(
        (containment - min_containment)
            .min(clearance - min_clearance)
            .min(max_penetration - penetration),
        confidence(evidence),
        &[
            "canonicalOccupancyVolume",
            "canonicalUsableReceptacleVolume",
            "containmentRatio",
            "minimumClearance",
            "maximumWallPenetration",
        ],
    )
}

fn released(evidence: &Value) -> PredicateResult {
    let Some(secured) = boolean(evidence, "effectorSecured") else {
        return PredicateResult::unknown("released requires effectorSecured");
    };
    let relative_motion_bounded = boolean(evidence, "relativeMotionBounded").unwrap_or(false);
    let robustness = if secured || relative_motion_bounded {
        -1.0
    } else {
        1.0
    };
    PredicateResult::known(
        robustness,
        confidence(evidence),
        &["effectorSecured", "relativeMotionBounded"],
    )
}

fn upright(profile: &Value, evidence: &Value) -> PredicateResult {
    let Some(tilt) = number(evidence, "tiltRadians") else {
        return PredicateResult::unknown("upright requires tiltRadians");
    };
    let Some(maximum) = threshold(profile, "maximumTiltRadians") else {
        return PredicateResult::unknown("upright profile lacks maximumTiltRadians");
    };
    if !finite(&[tilt, maximum]) {
        return PredicateResult::unknown("upright evidence contains a non-finite number");
    }
    PredicateResult::known(
        maximum - tilt.abs(),
        confidence(evidence),
        &["gravityDirection", "subjectUpAxis", "tiltRadians"],
    )
}

fn finite_state(evidence: &Value) -> PredicateResult {
    let Some(all_finite) = boolean(evidence, "allFinite") else {
        return PredicateResult::unknown("finite requires allFinite");
    };
    PredicateResult::known(
        if all_finite { 1.0 } else { -1.0 },
        confidence(evidence),
        &["canonicalStateChannels"],
    )
}

fn within_limits(evidence: &Value) -> PredicateResult {
    let Some(maximum_margin) = number(evidence, "minimumLimitMargin") else {
        return PredicateResult::unknown("within_limits requires minimumLimitMargin");
    };
    if !maximum_margin.is_finite() {
        return PredicateResult::unknown("minimumLimitMargin is non-finite");
    }
    PredicateResult::known(
        maximum_margin,
        confidence(evidence),
        &["jointLimits", "torqueLimits", "minimumLimitMargin"],
    )
}

fn no_dangerous_collision(evidence: &Value) -> PredicateResult {
    let Some(maximum_impulse_margin) = number(evidence, "minimumCollisionSafetyMargin") else {
        return PredicateResult::unknown(
            "no_dangerous_collision requires minimumCollisionSafetyMargin",
        );
    };
    if !maximum_impulse_margin.is_finite() {
        return PredicateResult::unknown("minimumCollisionSafetyMargin is non-finite");
    }
    PredicateResult::known(
        maximum_impulse_margin,
        confidence(evidence),
        &["aggregatedContactImpulse", "collisionSafetyPolicy"],
    )
}

fn no_excessive_penetration(profile: &Value, evidence: &Value) -> PredicateResult {
    let Some(penetration) = number(evidence, "maximumPenetration") else {
        return PredicateResult::unknown("no_excessive_penetration requires maximumPenetration");
    };
    let Some(maximum) = threshold(profile, "maximumPenetration") else {
        return PredicateResult::unknown(
            "no_excessive_penetration profile lacks maximumPenetration",
        );
    };
    if !finite(&[penetration, maximum]) {
        return PredicateResult::unknown("penetration evidence contains a non-finite number");
    }
    PredicateResult::known(
        maximum - penetration,
        confidence(evidence),
        &["canonicalCollisionPairs", "maximumPenetration"],
    )
}

/// Compute the duration for which the trailing samples continuously satisfy a
/// predicate. Unknown and false samples reset the interval.
pub fn trailing_true_duration(samples: &[(f64, Truth)]) -> Option<f64> {
    if samples.is_empty() || samples.iter().any(|(time, _)| !time.is_finite()) {
        return None;
    }
    let mut start = None;
    let mut last = None;
    for (time, truth) in samples {
        if last.is_some_and(|previous| *time < previous) {
            return None;
        }
        last = Some(*time);
        if *truth == Truth::True {
            start.get_or_insert(*time);
        } else {
            start = None;
        }
    }
    Some(match (start, last) {
        (Some(first), Some(final_time)) => final_time - first,
        _ => 0.0,
    })
}

/// Stable JSON representation used by adapters and evidence reports.
pub fn result_json(result: &PredicateResult) -> Value {
    serde_json::to_value(result).unwrap_or_else(|_| {
        json!({
            "truth": "unknown",
            "robustness": null,
            "confidence": 0.0,
            "evidence": [],
            "diagnostics": ["serialization failure"]
        })
    })
}

#[cfg(test)]
mod tests {
    use super::{Truth, evaluate, trailing_true_duration};
    use serde_json::json;

    fn profile(predicate_id: &str, thresholds: serde_json::Value) -> serde_json::Value {
        json!({
            "predicateId": predicate_id,
            "thresholds": thresholds
        })
    }

    #[test]
    fn inside_uses_canonical_semantic_geometry_margins() {
        let result = evaluate(
            "predicate://worldspec/inside",
            &profile(
                "predicate://worldspec/inside",
                json!({
                    "minimumContainmentRatio": 0.95,
                    "minimumClearance": 0.001,
                    "maximumWallPenetration": 0.002
                }),
            ),
            &json!({
                "containmentRatio": 0.98,
                "minimumClearance": 0.003,
                "maximumWallPenetration": 0.0005,
                "confidence": 0.9
            }),
        );
        assert_eq!(result.truth, Truth::True);
        assert!(result.robustness.is_some_and(|value| value > 0.0));
        assert_eq!(result.confidence, 0.9);
    }

    #[test]
    fn missing_evidence_is_unknown_not_false() {
        let result = evaluate(
            "predicate://worldspec/stable",
            &profile("predicate://worldspec/stable", json!({})),
            &json!({}),
        );
        assert_eq!(result.truth, Truth::Unknown);
        assert_eq!(result.robustness, None);
    }

    #[test]
    fn released_rejects_an_active_attachment() {
        let result = evaluate(
            "predicate://worldspec/released",
            &profile("predicate://worldspec/released", json!({})),
            &json!({
                "effectorSecured": true,
                "relativeMotionBounded": true
            }),
        );
        assert_eq!(result.truth, Truth::False);
    }

    #[test]
    fn hold_duration_resets_on_non_true_sample() {
        let duration = trailing_true_duration(&[
            (0.0, Truth::True),
            (0.2, Truth::False),
            (0.4, Truth::True),
            (0.9, Truth::True),
        ]);
        assert_eq!(duration, Some(0.5));
    }
}
