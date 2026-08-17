from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.market_review.onboarding import (QUEUE_SIZE, build_conflict_packet,
    canonical_submission_receipt, import_candidate_final_ledger,
    issue_blind_packets, load_fixed_queue)
from tools.validate.schema_validator import OfflineSchemaValidator


class MarketReviewOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2]
        self.temp = tempfile.TemporaryDirectory(); self.external = Path(self.temp.name)
        self.queue = load_fixed_queue(self.root)

    def tearDown(self): self.temp.cleanup()

    def _rows(self, role: str, *, divergent: bool = False):
        rows = []
        for index, queue in enumerate(self.queue):
            rows.append({"attestation_id": f"market_audit_attestation_{index + (1 if role == 'annotator_a' else 201):04d}", "ledger_id": f"market_claim_gold_{index + 1:04d}", "role": role, "authority_id": f"human_{role}", "fingerprint": "SHA256:external", "review_id": queue["review_id"], "submitted_at": "2026-08-17T00:00:00Z", "annotation": {"decision": "x" if not divergent or index else "y"}})
        return rows

    def _jsonl(self, name: str, rows):
        path = self.external / name; path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"); return path

    def test_fixed_200_coverage_and_unsigned_v2_receipt(self):
        self.assertEqual(QUEUE_SIZE, len(self.queue))
        receipt = canonical_submission_receipt(self.queue[0], self._rows("annotator_a")[0])
        self.assertEqual("sky-market-audit-v2", receipt["signature_namespace"])
        self.assertNotIn("signature_file", receipt["receipt"])
        self.assertEqual(64, len(receipt["receipt_sha256"]))

    def test_public_queue_blinding_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "keyed custodian"):
            issue_blind_packets(self.external / "packets", self.external / "issued", self.root)

    def test_conflicts_only_include_commitments_and_stay_external(self):
        a = self._jsonl("a.jsonl", self._rows("annotator_a")); b = self._jsonl("b.jsonl", self._rows("annotator_b", divergent=True))
        packet = build_conflict_packet(a, b, self.external / "conflicts.json", self.root)
        self.assertEqual(1, packet["conflict_count"])
        self.assertNotIn("annotation", packet["conflicts"][0])
        with self.assertRaisesRegex(ValueError, "outside"):
            build_conflict_packet(a, b, self.root / "data/review/conflicts.json", self.root)

    def test_tamper_role_replay_and_reserved_paths_are_rejected(self):
        row = self._rows("annotator_a")[0]; row["review_id"] = self.queue[1]["review_id"]
        with self.assertRaisesRegex(ValueError, "queue linkage"):
            canonical_submission_receipt(self.queue[0], row)
        a = self._jsonl("a.jsonl", self._rows("annotator_a")); b = self._jsonl("b.jsonl", self._rows("annotator_b"))
        with self.assertRaisesRegex(ValueError, "reserved"):
            build_conflict_packet(a, b, self.external / "market-claim-gold.jsonl", self.root)
        adj = self._jsonl("adj.jsonl", [])
        with self.assertRaisesRegex(ValueError, "authority bundle"):
            import_candidate_final_ledger(a, b, adj, self.external / "candidate.json", self.root)

    def test_fake_queue_row_and_reused_receipt_ids_are_rejected(self):
        fake = dict(self.queue[0]); fake["listing_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "committed fixed cohort"):
            canonical_submission_receipt(fake, self._rows("annotator_a")[0], self.root)
        rows = self._rows("annotator_a"); rows[1]["attestation_id"] = rows[0]["attestation_id"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_conflict_packet(self._jsonl("duplicate-a.jsonl", rows), self._jsonl("valid-b.jsonl", self._rows("annotator_b")), self.external / "duplicate-conflicts.json", self.root)
        invalid = {"schema_version":"market-review-conflict-packet-v1","queue_size":200,"conflict_count":1,"conflicts":[{"review_id":7,"annotator_a_attestation_id":"a","annotator_b_attestation_id":"b","annotator_a_receipt_sha256":7,"annotator_b_receipt_sha256":7}],"notice":"x"}
        errors = OfflineSchemaValidator(self.root / "schemas").validate(invalid, self.root / "schemas/review/market-review-conflict-packet.schema.json")
        self.assertTrue(errors)
