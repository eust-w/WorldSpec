use crate::Diagnostic;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

const FRAME_RELATION_PREFIX: &str = "worldspec://relation/frame.";
const QUATERNION_TOLERANCE: f64 = 1.0e-6;

fn evidence_authority(status: &str) -> u8 {
    match status {
        "measured" => 8,
        "manufacturer_declared" => 7,
        "imported" => 6,
        "reconstructed" => 5,
        "derived" => 4,
        "estimated" => 3,
        "generated" => 2,
        "default" => 1,
        "unknown" => 0,
        _ => 0,
    }
}

fn array<'a>(document: &'a Value, key: &str) -> &'a [Value] {
    document
        .get(key)
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
}

fn string<'a>(value: &'a Value, key: &str) -> Option<&'a str> {
    value.get(key).and_then(Value::as_str)
}

fn collect_ids(value: &Value, counts: &mut BTreeMap<String, usize>) {
    match value {
        Value::Object(object) => {
            if let Some(id) = object.get("id").and_then(Value::as_str) {
                *counts.entry(id.to_owned()).or_default() += 1;
            }
            for child in object.values() {
                collect_ids(child, counts);
            }
        }
        Value::Array(values) => {
            for child in values {
                collect_ids(child, counts);
            }
        }
        _ => {}
    }
}

fn object_ids(values: &[Value]) -> HashSet<String> {
    values
        .iter()
        .filter_map(|value| string(value, "id").map(str::to_owned))
        .collect()
}

fn missing_ref(
    diagnostics: &mut Vec<Diagnostic>,
    known_ids: &HashSet<String>,
    reference: Option<&str>,
    code: &str,
    path: String,
    owner: Option<&str>,
) {
    let Some(reference) = reference else {
        return;
    };
    if !known_ids.contains(reference) {
        let mut diagnostic =
            Diagnostic::error(code, format!("reference does not resolve: {reference}"))
                .at_path(path);
        if let Some(owner) = owner {
            diagnostic = diagnostic.for_object(owner);
        }
        diagnostics.push(diagnostic);
    }
}

fn find_cycle(adjacency: &HashMap<String, Vec<String>>) -> Option<String> {
    fn visit(
        node: &str,
        adjacency: &HashMap<String, Vec<String>>,
        active: &mut HashSet<String>,
        complete: &mut HashSet<String>,
    ) -> Option<String> {
        if active.contains(node) {
            return Some(node.to_owned());
        }
        if complete.contains(node) {
            return None;
        }
        active.insert(node.to_owned());
        if let Some(children) = adjacency.get(node) {
            for child in children {
                if let Some(cycle) = visit(child, adjacency, active, complete) {
                    return Some(cycle);
                }
            }
        }
        active.remove(node);
        complete.insert(node.to_owned());
        None
    }

    let mut active = HashSet::new();
    let mut complete = HashSet::new();
    let mut nodes = adjacency.keys().cloned().collect::<Vec<_>>();
    nodes.sort();
    for node in nodes {
        if let Some(cycle) = visit(&node, adjacency, &mut active, &mut complete) {
            return Some(cycle);
        }
    }
    None
}

fn validate_quaternion(
    diagnostics: &mut Vec<Diagnostic>,
    quaternion: Option<&Value>,
    path: String,
    owner: Option<&str>,
) {
    let Some(values) = quaternion.and_then(Value::as_array) else {
        return;
    };
    let squared_norm = values
        .iter()
        .filter_map(Value::as_f64)
        .map(|value| value * value)
        .sum::<f64>();
    if (squared_norm.sqrt() - 1.0).abs() > QUATERNION_TOLERANCE {
        let mut diagnostic = Diagnostic::error(
            "WS_INV_011_QUATERNION_NOT_NORMALIZED",
            format!("quaternion norm must be 1 within {QUATERNION_TOLERANCE}"),
        )
        .at_path(path);
        if let Some(owner) = owner {
            diagnostic = diagnostic.for_object(owner);
        }
        diagnostics.push(diagnostic);
    }
}

/// Validate cross-object invariants for a schema-valid WorldDefinition.
pub fn validate_world_definition(document: &Value) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    let mut id_counts = BTreeMap::new();
    collect_ids(document, &mut id_counts);
    for (id, count) in id_counts.iter().filter(|(_, count)| **count > 1) {
        diagnostics.push(
            Diagnostic::error(
                "WS_INV_001_DUPLICATE_ID",
                format!("object ID appears {count} times"),
            )
            .for_object(id),
        );
    }
    let all_ids = id_counts.keys().cloned().collect::<HashSet<_>>();

    let entities = array(document, "entities");
    let frames = array(document, "frames");
    let components = array(document, "components");
    let relations = array(document, "relations");
    let representations = array(document, "representations");
    let models = array(document, "models");
    let entity_ids = object_ids(entities);
    let frame_ids = object_ids(frames);
    let claim_ids = document
        .pointer("/evidenceGraph/claims")
        .and_then(Value::as_array)
        .map(|items| object_ids(items))
        .unwrap_or_default();
    let source_ids = document
        .pointer("/evidenceGraph/sources")
        .and_then(Value::as_array)
        .map(|items| object_ids(items))
        .unwrap_or_default();
    let derivation_ids = document
        .pointer("/evidenceGraph/derivations")
        .and_then(Value::as_array)
        .map(|items| object_ids(items))
        .unwrap_or_default();
    let clock_ids = object_ids(array(document, "clockDomains"));
    let state_channel_ids = object_ids(array(document, "stateChannels"));
    let root_entity = string(document, "rootEntity");
    let root_frame = string(document, "rootFrame");

    missing_ref(
        &mut diagnostics,
        &entity_ids,
        root_entity,
        "WS_INV_003_ROOT_ENTITY_MISSING",
        "/rootEntity".to_owned(),
        None,
    );
    missing_ref(
        &mut diagnostics,
        &frame_ids,
        root_frame,
        "WS_INV_003_ROOT_FRAME_MISSING",
        "/rootFrame".to_owned(),
        None,
    );

    let mut ownership = HashMap::<String, Vec<String>>::new();
    for (index, entity) in entities.iter().enumerate() {
        let id = string(entity, "id").unwrap_or_default();
        let owner = string(entity, "ownerEntity");
        if Some(id) == root_entity {
            if owner.is_some() {
                diagnostics.push(
                    Diagnostic::error(
                        "WS_INV_003_ROOT_HAS_OWNER",
                        "the root entity cannot have an owner",
                    )
                    .at_path(format!("/entities/{index}/ownerEntity"))
                    .for_object(id),
                );
            }
        } else if owner.is_none() {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_005_ENTITY_OWNER_MISSING",
                    "every non-root entity must have one owner",
                )
                .at_path(format!("/entities/{index}"))
                .for_object(id),
            );
        }
        if let Some(owner) = owner {
            missing_ref(
                &mut diagnostics,
                &entity_ids,
                Some(owner),
                "WS_INV_005_ENTITY_OWNER_UNKNOWN",
                format!("/entities/{index}/ownerEntity"),
                Some(id),
            );
            ownership
                .entry(owner.to_owned())
                .or_default()
                .push(id.to_owned());
        }

        let entity_root_frame = string(entity, "rootFrame");
        missing_ref(
            &mut diagnostics,
            &frame_ids,
            entity_root_frame,
            "WS_INV_006_ROOT_FRAME_UNKNOWN",
            format!("/entities/{index}/rootFrame"),
            Some(id),
        );
        if string(entity, "kind") == Some("spatial") && entity_root_frame.is_none() {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_006_ROOT_FRAME_MISSING",
                    "spatial entity must own a root frame",
                )
                .at_path(format!("/entities/{index}"))
                .for_object(id),
            );
        }
    }
    if let Some(cycle) = find_cycle(&ownership) {
        diagnostics.push(
            Diagnostic::error(
                "WS_INV_004_OWNERSHIP_CYCLE",
                "entity ownership graph is cyclic",
            )
            .for_object(cycle),
        );
    }

    let frame_owner = frames
        .iter()
        .filter_map(|frame| {
            Some((
                string(frame, "id")?.to_owned(),
                string(frame, "ownerEntity")?.to_owned(),
            ))
        })
        .collect::<HashMap<_, _>>();
    for (index, frame) in frames.iter().enumerate() {
        let id = string(frame, "id").unwrap_or_default();
        let owner = string(frame, "ownerEntity");
        missing_ref(
            &mut diagnostics,
            &entity_ids,
            owner,
            "WS_INV_007_FRAME_OWNER_UNKNOWN",
            format!("/frames/{index}/ownerEntity"),
            Some(id),
        );
    }
    for (index, entity) in entities.iter().enumerate() {
        let id = string(entity, "id").unwrap_or_default();
        if let Some(entity_root_frame) = string(entity, "rootFrame")
            && frame_owner.get(entity_root_frame).map(String::as_str) != Some(id)
        {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_007_ROOT_FRAME_WRONG_OWNER",
                    "entity root frame must be owned by that entity",
                )
                .at_path(format!("/entities/{index}/rootFrame"))
                .for_object(id),
            );
        }
    }

    let mut placement = HashMap::<String, Vec<String>>::new();
    let mut incoming = HashMap::<String, usize>::new();
    for (index, relation) in relations.iter().enumerate() {
        let id = string(relation, "id").unwrap_or_default();
        if let Some(endpoints) = relation.get("endpoints").and_then(Value::as_object) {
            for (name, endpoint) in endpoints {
                missing_ref(
                    &mut diagnostics,
                    &all_ids,
                    endpoint.as_str(),
                    "WS_INV_016_RELATION_ENDPOINT_UNKNOWN",
                    format!("/relations/{index}/endpoints/{name}"),
                    Some(id),
                );
            }
        }
        if !string(relation, "type").is_some_and(|value| value.starts_with(FRAME_RELATION_PREFIX)) {
            continue;
        }
        let parent = string(relation, "parentFrame").unwrap_or_default();
        let child = string(relation, "childFrame").unwrap_or_default();
        missing_ref(
            &mut diagnostics,
            &frame_ids,
            Some(parent),
            "WS_INV_016_PARENT_FRAME_UNKNOWN",
            format!("/relations/{index}/parentFrame"),
            Some(id),
        );
        missing_ref(
            &mut diagnostics,
            &frame_ids,
            Some(child),
            "WS_INV_016_CHILD_FRAME_UNKNOWN",
            format!("/relations/{index}/childFrame"),
            Some(id),
        );
        if parent == child {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_017_SELF_FRAME_RELATION",
                    "frame relation parent and child must differ",
                )
                .at_path(format!("/relations/{index}"))
                .for_object(id),
            );
        }
        placement
            .entry(parent.to_owned())
            .or_default()
            .push(child.to_owned());
        *incoming.entry(child.to_owned()).or_default() += 1;
        validate_quaternion(
            &mut diagnostics,
            relation.pointer("/transform/rotationWxyz"),
            format!("/relations/{index}/transform/rotationWxyz"),
            Some(id),
        );
    }
    for (frame_index, frame) in frames.iter().enumerate() {
        let id = string(frame, "id").unwrap_or_default();
        let driver_count = incoming.get(id).copied().unwrap_or_default();
        if Some(id) == root_frame {
            if driver_count != 0 {
                diagnostics.push(
                    Diagnostic::error(
                        "WS_INV_008_ROOT_FRAME_DRIVEN",
                        "the root frame cannot have a placement relation",
                    )
                    .at_path(format!("/frames/{frame_index}"))
                    .for_object(id),
                );
            }
        } else if driver_count == 0 {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_008_FRAME_PLACEMENT_MISSING",
                    "every non-root frame must have one placement relation",
                )
                .at_path(format!("/frames/{frame_index}"))
                .for_object(id),
            );
        } else if driver_count > 1 {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_012_MULTIPLE_FRAME_DRIVERS",
                    format!("frame has {driver_count} placement relations"),
                )
                .at_path(format!("/frames/{frame_index}"))
                .for_object(id),
            );
        }
    }
    if let Some(cycle) = find_cycle(&placement) {
        diagnostics.push(
            Diagnostic::error("WS_INV_009_FRAME_CYCLE", "frame placement graph is cyclic")
                .for_object(cycle),
        );
    }

    for (index, component) in components.iter().enumerate() {
        let id = string(component, "id").unwrap_or_default();
        let owner = string(component, "ownerEntity");
        missing_ref(
            &mut diagnostics,
            &entity_ids,
            owner,
            "WS_INV_014_COMPONENT_OWNER_UNKNOWN",
            format!("/components/{index}/ownerEntity"),
            Some(id),
        );
        if let Some(anchor) = string(component, "anchorFrame") {
            missing_ref(
                &mut diagnostics,
                &frame_ids,
                Some(anchor),
                "WS_INV_014_COMPONENT_FRAME_UNKNOWN",
                format!("/components/{index}/anchorFrame"),
                Some(id),
            );
            if let Some(owner) = owner
                && frame_owner.get(anchor).map(String::as_str) != Some(owner)
            {
                diagnostics.push(
                    Diagnostic::error(
                        "WS_INV_015_COMPONENT_FRAME_WRONG_OWNER",
                        "component anchor frame must belong to the same entity",
                    )
                    .at_path(format!("/components/{index}/anchorFrame"))
                    .for_object(id),
                );
            }
        }
        if let Some(bindings) = component.get("claimBindings").and_then(Value::as_object) {
            for (field, claim_ref) in bindings {
                missing_ref(
                    &mut diagnostics,
                    &claim_ids,
                    claim_ref.as_str(),
                    "WS_INV_032_MISSING_CLAIM",
                    format!("/components/{index}/claimBindings/{field}"),
                    Some(id),
                );
            }
        }
    }

    for (index, representation) in representations.iter().enumerate() {
        let id = string(representation, "id").unwrap_or_default();
        missing_ref(
            &mut diagnostics,
            &entity_ids,
            string(representation, "subjectRef"),
            "WS_INV_022_REPRESENTATION_SUBJECT_UNKNOWN",
            format!("/representations/{index}/subjectRef"),
            Some(id),
        );
        missing_ref(
            &mut diagnostics,
            &frame_ids,
            string(representation, "anchorFrame"),
            "WS_INV_022_REPRESENTATION_FRAME_UNKNOWN",
            format!("/representations/{index}/anchorFrame"),
            Some(id),
        );
        if let Some(claim_refs) = representation.get("claimRefs").and_then(Value::as_array) {
            for (claim_index, claim_ref) in claim_refs.iter().enumerate() {
                missing_ref(
                    &mut diagnostics,
                    &claim_ids,
                    claim_ref.as_str(),
                    "WS_INV_032_MISSING_CLAIM",
                    format!("/representations/{index}/claimRefs/{claim_index}"),
                    Some(id),
                );
            }
        }
        validate_quaternion(
            &mut diagnostics,
            representation.pointer("/mapping/transform/rotationWxyz"),
            format!("/representations/{index}/mapping/transform/rotationWxyz"),
            Some(id),
        );
    }

    for (index, model) in models.iter().enumerate() {
        let id = string(model, "id").unwrap_or_default();
        missing_ref(
            &mut diagnostics,
            &entity_ids,
            string(model, "subjectRef"),
            "WS_INV_021_MODEL_SUBJECT_UNKNOWN",
            format!("/models/{index}/subjectRef"),
            Some(id),
        );
        for (slot, expected) in [
            ("components", object_ids(components)),
            ("representations", object_ids(representations)),
        ] {
            if let Some(references) = model
                .pointer(&format!("/activates/{slot}"))
                .and_then(Value::as_array)
            {
                for (reference_index, reference) in references.iter().enumerate() {
                    missing_ref(
                        &mut diagnostics,
                        &expected,
                        reference.as_str(),
                        "WS_INV_020_MODEL_ACTIVATION_UNKNOWN",
                        format!("/models/{index}/activates/{slot}/{reference_index}"),
                        Some(id),
                    );
                }
            }
        }
    }

    let claims = document
        .pointer("/evidenceGraph/claims")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[]);
    for (index, claim) in claims.iter().enumerate() {
        let id = string(claim, "id").unwrap_or_default();
        missing_ref(
            &mut diagnostics,
            &all_ids,
            claim.pointer("/target/objectRef").and_then(Value::as_str),
            "WS_INV_033_CLAIM_TARGET_UNKNOWN",
            format!("/evidenceGraph/claims/{index}/target/objectRef"),
            Some(id),
        );
        if let Some(derived_by) = string(claim, "derivedBy")
            && let Some(derivation) = derivations_by_id(document).get(derived_by)
        {
            let output_authority = string(claim, "status")
                .map(evidence_authority)
                .unwrap_or_default();
            let claim_by_id = claims
                .iter()
                .filter_map(|item| Some((string(item, "id")?, item)))
                .collect::<HashMap<_, _>>();
            let maximum_input_authority = derivation
                .get("inputs")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .filter_map(|claim_ref| claim_by_id.get(claim_ref))
                .filter_map(|input| string(input, "status"))
                .map(evidence_authority)
                .max()
                .unwrap_or_default();
            if output_authority > maximum_input_authority {
                diagnostics.push(
                    Diagnostic::error(
                        "WS_INV_035_DERIVED_AUTHORITY_UPGRADE",
                        "derived claim authority exceeds every input claim",
                    )
                    .at_path(format!("/evidenceGraph/claims/{index}/status"))
                    .for_object(id),
                );
            }
        }
        if claim.pointer("/assertion/interval").is_some()
            || claim.pointer("/assertion/distribution").is_some()
        {
            if claim.pointer("/assertion/nominalSelectionPolicy").is_none() {
                diagnostics.push(
                    Diagnostic::error(
                        "WS_INV_037_NOMINAL_SELECTION_POLICY_MISSING",
                        "interval or distribution requires an explicit nominal selection policy",
                    )
                    .at_path(format!("/evidenceGraph/claims/{index}/assertion"))
                    .for_object(id),
                );
            }
            if claim.pointer("/assertion/uncertaintyPropagation").is_none() {
                diagnostics.push(
                    Diagnostic::error(
                        "WS_INV_038_UNCERTAINTY_PROPAGATION_MISSING",
                        "uncertain claim must declare propagation state",
                    )
                    .at_path(format!("/evidenceGraph/claims/{index}/assertion"))
                    .for_object(id),
                );
            }
        }
        if let Some(evidence) = claim.get("evidence").and_then(Value::as_array) {
            for (evidence_index, evidence_ref) in evidence.iter().enumerate() {
                missing_ref(
                    &mut diagnostics,
                    &source_ids,
                    evidence_ref.as_str(),
                    "WS_INV_033_EVIDENCE_SOURCE_UNKNOWN",
                    format!("/evidenceGraph/claims/{index}/evidence/{evidence_index}"),
                    Some(id),
                );
            }
        }
        missing_ref(
            &mut diagnostics,
            &derivation_ids,
            string(claim, "derivedBy"),
            "WS_INV_033_DERIVATION_UNKNOWN",
            format!("/evidenceGraph/claims/{index}/derivedBy"),
            Some(id),
        );
    }

    let derivations = document
        .pointer("/evidenceGraph/derivations")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[]);
    let mut derivation_graph = HashMap::<String, Vec<String>>::new();
    for (index, derivation) in derivations.iter().enumerate() {
        let id = string(derivation, "id").unwrap_or_default();
        for (slot, references) in [
            ("inputs", derivation.get("inputs")),
            ("outputs", derivation.get("outputs")),
        ] {
            if let Some(references) = references.and_then(Value::as_array) {
                for (reference_index, reference) in references.iter().enumerate() {
                    missing_ref(
                        &mut diagnostics,
                        &claim_ids,
                        reference.as_str(),
                        "WS_INV_034_DERIVATION_CLAIM_UNKNOWN",
                        format!("/evidenceGraph/derivations/{index}/{slot}/{reference_index}"),
                        Some(id),
                    );
                }
            }
        }
        let inputs = derivation
            .get("inputs")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str);
        let outputs = derivation
            .get("outputs")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .collect::<Vec<_>>();
        for input in inputs {
            derivation_graph
                .entry(input.to_owned())
                .or_default()
                .extend(outputs.iter().map(|output| (*output).to_owned()));
        }
    }
    if let Some(cycle) = find_cycle(&derivation_graph) {
        diagnostics.push(
            Diagnostic::error(
                "WS_INV_034_EVIDENCE_CYCLE",
                "evidence derivation graph is cyclic",
            )
            .for_object(cycle),
        );
    }

    for (index, channel) in array(document, "stateChannels").iter().enumerate() {
        let id = string(channel, "id").unwrap_or_default();
        missing_ref(
            &mut diagnostics,
            &all_ids,
            string(channel, "subjectRef"),
            "WS_INV_028_STATE_SUBJECT_UNKNOWN",
            format!("/stateChannels/{index}/subjectRef"),
            Some(id),
        );
        missing_ref(
            &mut diagnostics,
            &clock_ids,
            string(channel, "clockDomain"),
            "WS_INV_028_CLOCK_DOMAIN_UNKNOWN",
            format!("/stateChannels/{index}/clockDomain"),
            Some(id),
        );
    }
    for (index, entry) in array(document, "initialState").iter().enumerate() {
        missing_ref(
            &mut diagnostics,
            &state_channel_ids,
            string(entry, "channelRef"),
            "WS_INV_027_INITIAL_STATE_CHANNEL_UNKNOWN",
            format!("/initialState/{index}/channelRef"),
            None,
        );
    }

    diagnostics
}

fn derivations_by_id(document: &Value) -> HashMap<&str, &Value> {
    document
        .pointer("/evidenceGraph/derivations")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|item| Some((string(item, "id")?, item)))
        .collect()
}

/// Validate deterministic model selection and exact build provenance.
pub fn validate_build_manifest(document: &Value) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    let mut selections = HashSet::new();
    for (index, selection) in array(document, "modelSelections").iter().enumerate() {
        let key = (
            string(selection, "subjectRef").unwrap_or_default(),
            string(selection, "family").unwrap_or_default(),
        );
        if !selections.insert(key) {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_019_MODEL_SELECTION_AMBIGUOUS",
                    "a subject and model family may resolve to only one selected model",
                )
                .at_path(format!("/modelSelections/{index}")),
            );
        }
    }
    for field in [
        "worldDefinitionDigest",
        "evidenceGraphDigest",
        "targetProfileDigest",
        "buildIntentDigest",
        "lockDigest",
    ] {
        if document.get(field).is_none() {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_042_BUILD_PROVENANCE_INCOMPLETE",
                    format!("build manifest is missing {field}"),
                )
                .at_path(format!("/{field}")),
            );
        }
    }
    diagnostics
}

/// Validate that every lowering decision is explicit and non-duplicated.
pub fn validate_lowering_plan(document: &Value) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    let mut decisions = HashSet::new();
    for (index, item) in array(document, "items").iter().enumerate() {
        let key = (
            string(item, "sourceRef").unwrap_or_default(),
            string(item, "capability").unwrap_or_default(),
        );
        if !decisions.insert(key) {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_040_LOWERING_DECISION_DUPLICATE",
                    "each source capability must have exactly one lowering decision",
                )
                .at_path(format!("/items/{index}")),
            );
        }
        if string(item, "action") != Some("exact") && string(item, "reason").is_none() {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_040_LOWERING_REASON_MISSING",
                    "non-exact lowering decisions require a reason",
                )
                .at_path(format!("/items/{index}/reason")),
            );
        }
    }
    diagnostics
}

/// Validate runtime time ordering, epoch separation, and snapshot binding.
pub fn validate_runtime_record(document: &Value) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    let record_digest = string(document, "worldDefinitionDigest");
    let snapshot_digest = document
        .pointer("/initialSnapshot/worldDefinitionDigest")
        .and_then(Value::as_str);
    if record_digest != snapshot_digest {
        diagnostics.push(
            Diagnostic::error(
                "WS_INV_031_SNAPSHOT_WORLD_DIGEST_MISMATCH",
                "snapshot must bind the exact WorldDefinition digest",
            )
            .at_path("/initialSnapshot/worldDefinitionDigest"),
        );
    }
    let record_epoch = string(document, "epoch");
    for (stream_index, stream) in array(document, "stateStreams").iter().enumerate() {
        if string(stream, "epoch") != record_epoch {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_030_EPOCH_MISMATCH",
                    "state stream epoch differs from its runtime record",
                )
                .at_path(format!("/stateStreams/{stream_index}/epoch")),
            );
        }
        let mut previous = None;
        for (sample_index, sample) in array(stream, "samples").iter().enumerate() {
            let timestamp = sample
                .get("timestamp")
                .and_then(Value::as_f64)
                .unwrap_or_default();
            if previous.is_some_and(|value| timestamp < value) {
                diagnostics.push(
                    Diagnostic::error(
                        "WS_INV_029_TIMESTAMP_NOT_MONOTONIC",
                        "state stream timestamps must be monotonically non-decreasing",
                    )
                    .at_path(format!(
                        "/stateStreams/{stream_index}/samples/{sample_index}/timestamp"
                    )),
                );
            }
            previous = Some(timestamp);
        }
    }
    for (index, event) in array(document, "events").iter().enumerate() {
        if string(event, "epoch") != record_epoch {
            diagnostics.push(
                Diagnostic::error(
                    "WS_INV_030_EVENT_EPOCH_MISMATCH",
                    "event epoch differs from its runtime record",
                )
                .at_path(format!("/events/{index}/epoch")),
            );
        }
    }
    diagnostics
}

/// Validate certificate state transitions that cannot be expressed by shape alone.
pub fn validate_certificate(document: &Value) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    let invalidated = !array(document, "invalidatedBy").is_empty();
    if invalidated && document.get("valid").and_then(Value::as_bool) == Some(true) {
        diagnostics.push(
            Diagnostic::error(
                "CERT_INVALIDATION_CONFLICT",
                "an invalidated certificate cannot remain valid",
            )
            .at_path("/valid"),
        );
    }
    diagnostics
}

/// Validate result accounting and execution-evidence semantics for a ConformanceReport.
pub fn validate_conformance_report(document: &Value) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    let tests = array(document, "tests");
    let mut passed = 0_u64;
    let mut failed = 0_u64;
    let mut unknown = 0_u64;
    let mut not_run = 0_u64;
    for test in tests {
        match string(test, "result") {
            Some("pass") => passed += 1,
            Some("fail") => failed += 1,
            Some("unknown") => unknown += 1,
            Some("not_run") => not_run += 1,
            _ => {}
        }
    }
    let expected = [
        ("passed", passed),
        ("failed", failed),
        ("unknown", unknown),
        ("notRun", not_run),
    ];
    for (field, actual) in expected {
        let declared = document
            .pointer(&format!("/summary/{field}"))
            .and_then(Value::as_u64)
            .unwrap_or_default();
        if declared != actual {
            diagnostics.push(
                Diagnostic::error(
                    "CONFORMANCE_SUMMARY_MISMATCH",
                    format!("summary.{field} is {declared}, but tests require {actual}"),
                )
                .at_path(format!("/summary/{field}")),
            );
        }
    }
    let declared_overall = document
        .pointer("/summary/overall")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let expected_overall = if failed > 0 {
        "fail"
    } else if unknown > 0 || not_run > 0 {
        "incomplete"
    } else {
        "pass"
    };
    if declared_overall != expected_overall {
        diagnostics.push(
            Diagnostic::error(
                "CONFORMANCE_OVERALL_MISMATCH",
                format!(
                    "summary.overall is {declared_overall}, but test results require {expected_overall}"
                ),
            )
            .at_path("/summary/overall"),
        );
    }
    if string(document, "executionEvidence") == Some("not_executed")
        && (passed > 0 || declared_overall == "pass")
    {
        diagnostics.push(
            Diagnostic::error(
                "CONFORMANCE_EXECUTION_EVIDENCE_CONFLICT",
                "not_executed evidence cannot contain passing runtime tests",
            )
            .at_path("/executionEvidence"),
        );
    }
    diagnostics
}

/// Validate semantic coverage rules for a schema-valid LossReport.
pub fn validate_loss_report(report: &Value, target_profile: Option<&Value>) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    let entries = array(report, "entries");
    let source_count = report
        .pointer("/coverage/sourceItemCount")
        .and_then(Value::as_u64)
        .unwrap_or_default() as usize;
    let reported_count = report
        .pointer("/coverage/reportedItemCount")
        .and_then(Value::as_u64)
        .unwrap_or_default() as usize;
    let complete = report
        .pointer("/coverage/complete")
        .and_then(Value::as_bool)
        .unwrap_or(false);

    if reported_count != entries.len() {
        diagnostics.push(
            Diagnostic::error(
                "LOSS_REPORTED_COUNT_MISMATCH",
                format!(
                    "reportedItemCount is {reported_count}, but entries contains {} items",
                    entries.len()
                ),
            )
            .at_path("/coverage/reportedItemCount"),
        );
    }
    if complete && source_count != reported_count {
        diagnostics.push(
            Diagnostic::error(
                "LOSS_COVERAGE_MISMATCH",
                format!(
                    "complete coverage requires sourceItemCount ({source_count}) to equal reportedItemCount ({reported_count})"
                ),
            )
            .at_path("/coverage"),
        );
    }

    if let Some(target_profile) = target_profile {
        let reported_capabilities = entries
            .iter()
            .filter_map(|entry| string(entry, "capability"))
            .collect::<BTreeSet<_>>();
        for (index, capability) in array(target_profile, "capabilities").iter().enumerate() {
            if string(capability, "support") != Some("exact")
                && let Some(id) = string(capability, "id")
                && !reported_capabilities.contains(id)
            {
                diagnostics.push(
                    Diagnostic::error(
                        "LOSS_UNREPORTED_NON_EXACT_CAPABILITY",
                        "non-exact target capability has no LossReport entry",
                    )
                    .at_path(format!("/capabilities/{index}"))
                    .for_object(id),
                );
            }
        }
    }

    diagnostics
}
