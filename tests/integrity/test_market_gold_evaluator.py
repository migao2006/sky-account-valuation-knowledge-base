"""Formal market human-gold gate stays fail-closed until independent evidence exists."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.modeling.market_gold_evaluator import LABEL_FIELDS, build  # noqa: E402
from tools.validate.market_audit import ATTESTATIONS_REL, SIGNATURES_REL, V2_NAMESPACE, _fingerprint, adjudication_commitment, annotation_commitment, queue_commitment, sha256_bytes, v2_attestation_payload, v2_receipt_digest  # noqa: E402
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


class MarketGoldEvaluatorTests(unittest.TestCase):
    @staticmethod
    def _labels() -> dict[str, object]:
        return {"offer_kind": "seller_listing", "entity_kind": "single_account", "server": "international", "currency": "TWD", "price_type": "asking", "price_twd": 1200, "status": "active", "date_verified": False, "verified_sale": False}

    def _signed_v2_fixture(self) -> tuple[Path, Path, str]:
        temporary = Path(tempfile.mkdtemp(prefix="market-gold-v2-")); self.addCleanup(shutil.rmtree, temporary, True)
        release = temporary / "release"; (release / SIGNATURES_REL).mkdir(parents=True)
        queue = [json.loads(line) for line in (ROOT / "data/review/market-claim-review.jsonl").read_text(encoding="utf-8").splitlines() if line]
        (release / "data/review").mkdir(parents=True, exist_ok=True)
        (release / "data/review/market-claim-review.jsonl").write_text("".join(json.dumps(row) + "\n" for row in queue), encoding="utf-8")
        keys = temporary / "keys"; keys.mkdir(); authorities = []; private: dict[str, Path] = {}
        for role, identity in (("annotator_a", "human_a"), ("annotator_b", "human_b"), ("adjudicator", "human_c")):
            key = keys / role; subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
            public = key.with_suffix(".pub").read_text(encoding="utf-8").strip(); fingerprint = _fingerprint(public); self.assertIsNotNone(fingerprint)
            authorities.append({"authority_id": identity, "public_key": public, "fingerprint": fingerprint, "roles": [role]}); private[role] = key
        gold = []; attestations = []
        for number, review in enumerate(queue, 1):
            ledger_id = f"market_claim_gold_{number:04d}"; labels = self._labels()
            row = {"gold_id": ledger_id, "review_id": review["review_id"], "listing_id": review["listing_id"], "listing_text_sha256": review["listing_text_sha256"], "annotation_protocol": "double_independent_human_annotation", "annotator_a": {"annotator_id": "human_a", "annotator_kind": "human", "annotated_at": "2026-08-17", "labels": labels}, "annotator_b": {"annotator_id": "human_b", "annotator_kind": "human", "annotated_at": "2026-08-17", "labels": labels}, "adjudication": {"adjudicator_id": "human_c", "adjudicator_kind": "human", "adjudicated_at": "2026-08-17", "decision": "agreement", "final_labels": labels}, "review_status": "approved_human_gold"}; gold.append(row)
            queue_hash = queue_commitment(review); receipts = []
            for role, identity, hour in (("annotator_a", "human_a", "01"), ("annotator_b", "human_b", "02")):
                receipt = {"schema_version": "sky-market-audit-attestation-v2", "attestation_id": f"market_audit_attestation_{number * 3 - (2 if role == 'annotator_a' else 1):04d}", "ledger_kind": "market_claim_gold", "ledger_id": ledger_id, "role": role, "authority_id": identity, "fingerprint": next(a["fingerprint"] for a in authorities if a["authority_id"] == identity), "signature_file": (SIGNATURES_REL / f"{ledger_id}_{role}.sig").as_posix(), "receipt_type": "blinded_annotation_submission", "review_id": review["review_id"], "submitted_at": f"2026-08-17T{hour}:00:00Z", "queue_commitment_sha256": queue_hash, "annotation_commitment_sha256": annotation_commitment("market_claim_gold", ledger_id, role, queue_hash, row[role])}; receipts.append(receipt)
            receipts.append({"schema_version": "sky-market-audit-attestation-v2", "attestation_id": f"market_audit_attestation_{number * 3:04d}", "ledger_kind": "market_claim_gold", "ledger_id": ledger_id, "role": "adjudicator", "authority_id": "human_c", "fingerprint": next(a["fingerprint"] for a in authorities if a["authority_id"] == "human_c"), "signature_file": (SIGNATURES_REL / f"{ledger_id}_adjudicator.sig").as_posix(), "receipt_type": "adjudication", "review_id": review["review_id"], "adjudicated_at": "2026-08-17T03:00:00Z", "queue_commitment_sha256": queue_hash, "annotator_a_attestation_id": receipts[0]["attestation_id"], "annotator_b_attestation_id": receipts[1]["attestation_id"], "annotator_a_annotation_commitment_sha256": receipts[0]["annotation_commitment_sha256"], "annotator_b_annotation_commitment_sha256": receipts[1]["annotation_commitment_sha256"], "annotator_a_receipt_sha256": v2_receipt_digest(receipts[0]), "annotator_b_receipt_sha256": v2_receipt_digest(receipts[1]), "final_adjudication_commitment_sha256": adjudication_commitment("market_claim_gold", ledger_id, queue_hash, row["adjudication"])})
            for receipt in receipts:
                payload = v2_attestation_payload(receipt); receipt["payload_sha256"] = sha256_bytes(payload); raw = temporary / receipt["attestation_id"]; raw.write_bytes(payload)
                subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(private[receipt["role"]]), "-n", V2_NAMESPACE, str(raw)], check=True, capture_output=True)
                shutil.copyfile(raw.with_name(raw.name + ".sig"), release / receipt["signature_file"]); attestations.append(receipt)
        (release / "data/review/market-claim-gold.jsonl").write_text("".join(json.dumps(row) + "\n" for row in gold), encoding="utf-8")
        (release / ATTESTATIONS_REL).parent.mkdir(parents=True, exist_ok=True); (release / ATTESTATIONS_REL).write_text("".join(json.dumps(row) + "\n" for row in attestations), encoding="utf-8")
        bundle = temporary / "authorities.json"; bundle.write_text(json.dumps({"schema_version": "sky-market-audit-authority-bundle-v1", "authorities": authorities, "revoked_fingerprints": []}), encoding="utf-8")
        return release, bundle, sha256_bytes(bundle.read_bytes())
    def test_committed_empty_report_is_replayable_and_schema_valid(self):
        expected = json.loads((ROOT / "reports/market-gold-evaluation.json").read_text(encoding="utf-8"))
        actual = build(ROOT)
        self.assertEqual(actual, expected)
        self.assertEqual(actual["status"], "not_ready")
        self.assertFalse(actual["publication_ready"])
        self.assertFalse(actual["independent_blinded_decisions_proven"])
        self.assertEqual(actual["gold_row_count"], 0)
        self.assertEqual(set(actual["heldout_minimum_annotator_field_accuracy"]), set(LABEL_FIELDS))
        validator = OfflineSchemaValidator(ROOT / "schemas")
        self.assertEqual(validator.validate(actual, ROOT / "schemas/review/market-gold-evaluation.schema.json"), [])

    def test_current_final_row_attestation_can_never_claim_independent_gold(self):
        # The evaluator deliberately does not treat a signed completed ledger
        # row as proof that annotations were independently submitted first.
        report = build(ROOT)
        self.assertIn("requires externally signed blinded annotation-submission receipts before a formal market-gold ledger can be recognized", report["blocking_reasons"])

    def test_v2_external_receipts_enable_a_perfect_200_row_evaluation(self):
        release, bundle, digest = self._signed_v2_fixture()
        report = build(release, bundle, digest)
        self.assertTrue(report["publication_ready"], report["blocking_reasons"])
        self.assertTrue(report["independent_blinded_decisions_proven"], report["independence_errors"])


if __name__ == "__main__":
    unittest.main()
