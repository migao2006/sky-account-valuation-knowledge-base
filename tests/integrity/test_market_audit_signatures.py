"""OpenSSH detached market-audit contract tests (all keys are temporary)."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))
from market_audit import ATTESTATIONS_REL, NAMESPACE, SIGNATURES_REL, attestation_payload, audit_market_ledgers, sha256_bytes, _fingerprint  # noqa: E402


def labels() -> dict[str, object]:
    return {"offer_kind": "seller_listing", "entity_kind": "single_account", "server": "international", "currency": "TWD", "price_type": "asking", "price_twd": 1200, "status": "active", "date_verified": False}


class MarketAuditSignatureTests(unittest.TestCase):
    def _key(self, directory: Path, name: str) -> tuple[Path, str, str]:
        private = directory / name
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
        public = private.with_suffix(".pub").read_text(encoding="utf-8").strip()
        fingerprint = _fingerprint(public)
        self.assertIsNotNone(fingerprint)
        return private, public, str(fingerprint)

    def _fixture(self, *, near: bool = False, same_key: bool = False, revoked: bool = False, wrong_role: bool = False) -> tuple[Path, Path, str, list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        temporary = Path(tempfile.mkdtemp(prefix="market-audit-test-"))
        self.addCleanup(shutil.rmtree, temporary, True)
        release = temporary / "release"; release.mkdir()
        signatures = release / SIGNATURES_REL; signatures.mkdir(parents=True)
        keys = temporary / "keys"; keys.mkdir()
        key_a, pub_a, fp_a = self._key(keys, "a")
        key_b, pub_b, fp_b = (key_a, pub_a, fp_a) if same_key else self._key(keys, "b")
        key_c, pub_c, fp_c = self._key(keys, "c")
        queue = [{"review_id": "market_near_miss_review_0001" if near else "market_claim_review_0001", "listing_id": "listing_0001", "listing_text_sha256": "A" * 64, "required_fields" if near else "requested_fields": ["server" if near else "offer_kind"]}]
        gold = ([{
            "evidence_id": "market_near_miss_evidence_0001", "review_id": "market_near_miss_review_0001", "listing_id": "listing_0001", "listing_text_sha256": "A" * 64,
            "field": "server", "value": "international",
            "reviewers": [{"reviewer_id": "human_a", "reviewer_kind": "human", "reviewed_at": "2026-08-17", "value": "international"}, {"reviewer_id": "human_b", "reviewer_kind": "human", "reviewed_at": "2026-08-17", "value": "international"}],
            "adjudication": {"adjudicator_id": "human_c", "adjudicator_kind": "human", "adjudicated_at": "2026-08-17", "decision": "agreement", "final_value": "international"}, "review_status": "approved_human_field_evidence",
        }] if near else [{
            "gold_id": "market_claim_gold_0001", "review_id": "market_claim_review_0001", "listing_id": "listing_0001", "listing_text_sha256": "A" * 64,
            "annotation_protocol": "double_independent_human_annotation",
            "annotator_a": {"annotator_id": "human_a", "annotator_kind": "human", "annotated_at": "2026-08-17", "labels": labels()},
            "annotator_b": {"annotator_id": "human_b", "annotator_kind": "human", "annotated_at": "2026-08-17", "labels": labels()},
            "adjudication": {"adjudicator_id": "human_c", "adjudicator_kind": "human", "adjudicated_at": "2026-08-17", "decision": "agreement", "final_labels": labels()}, "review_status": "approved_human_gold",
        }])
        ledger_kind = "market_near_miss_approved_evidence" if near else "market_claim_gold"
        ledger_id = "market_near_miss_evidence_0001" if near else "market_claim_gold_0001"
        roles = ("reviewer_a", "reviewer_b", "adjudicator") if near else ("annotator_a", "annotator_b", "adjudicator")
        authority_data = [("human_a", key_a, pub_a, fp_a, roles[0]), ("human_b", key_b, pub_b, fp_b, roles[1]), ("human_c", key_c, pub_c, fp_c, roles[2])]
        attestations: list[dict[str, object]] = []
        for index, (identity, private, _public, fingerprint, role) in enumerate(authority_data, 1):
            signature_rel = (SIGNATURES_REL / f"ledger_{role}.sig").as_posix()
            attestation: dict[str, object] = {"attestation_id": f"market_audit_attestation_{index:04d}", "ledger_kind": ledger_kind, "ledger_id": ledger_id, "role": role, "authority_id": identity, "fingerprint": fingerprint, "signature_file": signature_rel}
            payload = attestation_payload(ledger_kind, gold[0], queue[0], attestation)
            attestation["payload_sha256"] = sha256_bytes(payload)
            payload_file = temporary / f"payload_{role}"
            payload_file.write_bytes(payload)
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", NAMESPACE, str(payload_file)], check=True, capture_output=True)
            shutil.copyfile(payload_file.with_name(payload_file.name + ".sig"), release / signature_rel)
            attestations.append(attestation)
        (release / ATTESTATIONS_REL).parent.mkdir(parents=True, exist_ok=True)
        (release / ATTESTATIONS_REL).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in attestations), encoding="utf-8", newline="\n")
        authorities = []
        for identity, _private, public, fingerprint, role in authority_data:
            roles = [] if wrong_role and identity == "human_b" else [role]
            authorities.append({"authority_id": identity, "public_key": public, "fingerprint": fingerprint, "roles": roles})
        bundle = temporary / "authorities.json"
        bundle.write_text(json.dumps({"schema_version": "sky-market-audit-authority-bundle-v1", "authorities": authorities, "revoked_fingerprints": [fp_b] if revoked else []}, sort_keys=True), encoding="utf-8")
        return release, bundle, sha256_bytes(bundle.read_bytes()), queue, gold, attestations

    def _audit(self, release: Path, bundle: Path, digest: str, queue: list[dict[str, object]], gold: list[dict[str, object]]) -> list[str]:
        if "evidence_id" in gold[0]:
            return audit_market_ledgers(release, [], [], queue, gold, bundle, digest)
        return audit_market_ledgers(release, queue, gold, [], [], bundle, digest)

    def test_valid_external_root_and_signatures_are_accepted(self):
        release, bundle, digest, queue, gold, _ = self._fixture()
        self.assertEqual(self._audit(release, bundle, digest, queue, gold), [])
        release, bundle, digest, queue, evidence, _ = self._fixture(near=True)
        self.assertEqual(self._audit(release, bundle, digest, queue, evidence), [])

    def test_no_external_root_and_tamper_fail_closed(self):
        release, bundle, digest, queue, gold, _ = self._fixture()
        self.assertTrue(audit_market_ledgers(release, queue, gold, [], []))
        gold[0]["annotator_a"]["labels"]["currency"] = "CNY"  # type: ignore[index]
        self.assertTrue(self._audit(release, bundle, digest, queue, gold))

    def test_signature_reuse_same_key_revocation_and_wrong_role_fail_closed(self):
        release, bundle, digest, queue, gold, attestations = self._fixture()
        attestations[1]["signature_file"] = attestations[0]["signature_file"]
        (release / ATTESTATIONS_REL).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in attestations), encoding="utf-8")
        self.assertTrue(self._audit(release, bundle, digest, queue, gold))
        release, bundle, digest, queue, gold, _ = self._fixture(same_key=True)
        self.assertTrue(self._audit(release, bundle, digest, queue, gold))
        release, bundle, digest, queue, gold, _ = self._fixture(revoked=True)
        self.assertTrue(self._audit(release, bundle, digest, queue, gold))
        release, bundle, digest, queue, gold, _ = self._fixture(wrong_role=True)
        self.assertTrue(self._audit(release, bundle, digest, queue, gold))

    def test_wrong_bundle_hash_fails_closed(self):
        release, bundle, _digest, queue, gold, _ = self._fixture()
        self.assertTrue(self._audit(release, bundle, "0" * 64, queue, gold))


if __name__ == "__main__":
    unittest.main()
