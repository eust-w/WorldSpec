---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/architecture/security-and-native-payload.md
last-verified: 2026-07-28
---

# Security and native payload

The Chinese document is the normative source; this page is its official translation.

## Untrusted input

GLB/OBJ/CAD/USD/URDF/MJCF files, textures, archives, and generated results are untrusted data. Ingestion limits paths, size, expansion ratio, resource count, and parse time and rejects path traversal and implicit network references.

Plugins, Python, shared libraries, scripted USD, and runtime extensions are executable content:

- disabled by default;
- isolated from data parsing by process/container;
- least privilege, no implicit network, read-only source;
- outputs identify tool and sandbox versions;
- “not executed” never means “validated.”

## Native Payload

CAD/OpenUSD/MJCF inputs use two parallel paths:

1. **Canonical Mapping**: known fields map to editable WorldSpec objects.
2. **Opaque Preservation**: unknown fields and source blobs remain byte-preserved by digest.

Native Payload declares source format, version, namespace, digest, rights status, and target scope. It cannot override Core truth. It may support round-trip to the original target; other exports report unapplied or unexplained content in LossReport.

Preserving a source blob must never be described as lossless cross-format conversion.
