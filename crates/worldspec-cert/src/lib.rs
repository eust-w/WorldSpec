//! Digest-bound optional Ed25519 certificate signing.

use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use rand_core::OsRng;
use serde_json::{Value, json};
use worldspec_core::{CanonicalError, canonical_json};

pub fn generate_signing_key() -> SigningKey {
    SigningKey::generate(&mut OsRng)
}

fn unsigned_payload(certificate: &Value) -> Result<Vec<u8>, CanonicalError> {
    let mut payload = certificate.clone();
    if let Some(object) = payload.as_object_mut() {
        object.remove("signature");
        object.insert(
            "signatureStatus".to_owned(),
            Value::String("unsigned".to_owned()),
        );
    }
    canonical_json(&payload)
}

pub fn sign_certificate(
    certificate: &mut Value,
    key: &SigningKey,
    public_key_id: &str,
) -> Result<(), CanonicalError> {
    let signature = key.sign(&unsigned_payload(certificate)?);
    let object = certificate
        .as_object_mut()
        .expect("certificate schema requires an object");
    object.insert(
        "signatureStatus".to_owned(),
        Value::String("signed".to_owned()),
    );
    object.insert(
        "signature".to_owned(),
        json!({
            "algorithm": "Ed25519",
            "publicKeyId": public_key_id,
            "value": URL_SAFE_NO_PAD.encode(signature.to_bytes())
        }),
    );
    Ok(())
}

pub fn sign_certificate_with_seed(
    certificate: &mut Value,
    seed: &[u8; 32],
    public_key_id: &str,
) -> Result<(), CanonicalError> {
    sign_certificate(certificate, &SigningKey::from_bytes(seed), public_key_id)
}

pub fn verify_certificate(certificate: &Value, key: &VerifyingKey) -> bool {
    let Some(encoded) = certificate
        .pointer("/signature/value")
        .and_then(Value::as_str)
    else {
        return false;
    };
    let Ok(bytes) = URL_SAFE_NO_PAD.decode(encoded) else {
        return false;
    };
    let Ok(signature) = Signature::from_slice(&bytes) else {
        return false;
    };
    let Ok(payload) = unsigned_payload(certificate) else {
        return false;
    };
    key.verify(&payload, &signature).is_ok()
}

#[cfg(test)]
mod tests {
    use super::{generate_signing_key, sign_certificate, verify_certificate};
    use serde_json::Value;

    fn fixture() -> Value {
        serde_json::from_str(include_str!(
            "../../../examples/minimal-cube/certificate.json"
        ))
        .unwrap()
    }

    #[test]
    fn signature_detects_certificate_tampering() {
        let key = generate_signing_key();
        let mut certificate = fixture();
        sign_certificate(&mut certificate, &key, "key://worldspec/test").unwrap();
        assert!(verify_certificate(&certificate, &key.verifying_key()));
        certificate["assetDigest"] = Value::String(format!("sha256:{}", "9".repeat(64)));
        assert!(!verify_certificate(&certificate, &key.verifying_key()));
    }
}
