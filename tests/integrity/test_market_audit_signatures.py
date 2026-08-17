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
from market_audit import ATTESTATIONS_REL, NAMESPACE, SIGNATURES_REL, V2_NAMESPACE, adjudication_commitment, annotation_commitment, attestation_payload, audit_market_ledgers, independent_blinded_decisions_errors, queue_commitment, sha256_bytes, v2_attestation_payload, v2_receipt_digest, _fingerprint  # noqa: E402


def labels() -> dict[str, object]:
    return {"offer_kind": "seller_listing", "entity_kind": "single_account", "server": "international", "currency": "TWD", "price_type": "asking", "price_twd": 1200, "status": "active", "date_verified": False, "verified_sale": False}


class MarketAuditSignatureTests(unittest.TestCase):
    def _key(self, directory: Path, name: str) -> tuple[Path, str, str]:
        private = directory / name
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
        public = private.with_suffix(".pub").read_text(encoding="utf-8").strip()
        fingerprint = _fingerprint(public)
        self.assertIsNotNone(fingerprint)
        return private, public, str(fingerprint)

    def _fixture(self, *, near: bool = False, same_key: bool = False, revoked: bool = False, wrong_role: bool = False, v2: bool = False) -> tuple[Path, Path, str, list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
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
            if v2:
                self.assertFalse(near, "v2 fixture is for formal claim gold")
                attestation.update({"schema_version": "sky-market-audit-attestation-v2", "review_id": queue[0]["review_id"], "queue_commitment_sha256": queue_commitment(queue[0])})
                if role in {"annotator_a", "annotator_b"}:
                    attestation.update({"receipt_type": "blinded_annotation_submission", "submitted_at": f"2026-08-17T0{index}:00:00Z", "annotation_commitment_sha256": annotation_commitment(ledger_kind, ledger_id, role, queue_commitment(queue[0]), gold[0][role])})
                else:
                    attestation.update({"receipt_type": "adjudication", "adjudicated_at": "2026-08-17T04:00:00Z", "annotator_a_attestation_id": "market_audit_attestation_0001", "annotator_b_attestation_id": "market_audit_attestation_0002", "annotator_a_annotation_commitment_sha256": "", "annotator_b_annotation_commitment_sha256": "", "annotator_a_receipt_sha256": "", "annotator_b_receipt_sha256": "", "final_adjudication_commitment_sha256": adjudication_commitment(ledger_kind, ledger_id, queue_commitment(queue[0]), gold[0]["adjudication"])})
                    # A and B were added first in the deterministic role order.
                    attestation["annotator_a_annotation_commitment_sha256"] = attestations[0]["annotation_commitment_sha256"]
                    attestation["annotator_b_annotation_commitment_sha256"] = attestations[1]["annotation_commitment_sha256"]
                    attestation["annotator_a_receipt_sha256"] = v2_receipt_digest(attestations[0])
                    attestation["annotator_b_receipt_sha256"] = v2_receipt_digest(attestations[1])
            payload = v2_attestation_payload(attestation) if v2 else attestation_payload(ledger_kind, gold[0], queue[0], attestation)
            attestation["payload_sha256"] = sha256_bytes(payload)
            payload_file = temporary / f"payload_{role}"
            payload_file.write_bytes(payload)
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", V2_NAMESPACE if v2 else NAMESPACE, str(payload_file)], check=True, capture_output=True)
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

    def test_legacy_gold_final_row_signature_is_not_independence_proof(self):
        release, bundle, digest, queue, gold, _ = self._fixture()
        self.assertTrue(self._audit(release, bundle, digest, queue, gold))
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

    def test_v2_blinded_receipts_replay_and_tamper_or_reuse_fail_closed(self):
        release, bundle, digest, queue, gold, attestations = self._fixture(v2=True)
        self.assertEqual(independent_blinded_decisions_errors(release, queue, gold, bundle, digest), [])
        attestations[2]["annotator_a_annotation_commitment_sha256"] = "0" * 64
        (release / ATTESTATIONS_REL).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in attestations), encoding="utf-8", newline="\n")
        self.assertTrue(independent_blinded_decisions_errors(release, queue, gold, bundle, digest))

    def test_v2_receipt_replacement_after_adjudication_fails(self):
        release, bundle, digest, queue, gold, attestations = self._fixture(v2=True)
        attestations[0]["submitted_at"] = "2026-08-17T01:30:00Z"
        payload = v2_attestation_payload(attestations[0]); attestations[0]["payload_sha256"] = sha256_bytes(payload)
        # This replacement models A re-signing a changed receipt after C's
        # adjudication was already signed. C's receipt digest must reject it.
        payload_file = release.parent / "replacement"; payload_file.write_bytes(payload)
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(release.parent / "keys" / "a"), "-n", V2_NAMESPACE, str(payload_file)], check=True, capture_output=True)
        shutil.copyfile(payload_file.with_name(payload_file.name + ".sig"), release / attestations[0]["signature_file"])
        (release / ATTESTATIONS_REL).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in attestations), encoding="utf-8", newline="\n")
        self.assertTrue(independent_blinded_decisions_errors(release, queue, gold, bundle, digest))
        release, bundle, digest, queue, gold, attestations = self._fixture(v2=True)
        attestations[1]["signature_file"] = attestations[0]["signature_file"]
        (release / ATTESTATIONS_REL).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in attestations), encoding="utf-8", newline="\n")
        self.assertTrue(independent_blinded_decisions_errors(release, queue, gold, bundle, digest))


if __name__ == "__main__":
    unittest.main()
