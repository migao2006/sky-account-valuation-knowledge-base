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
from tools.parser_review.onboarding import (  # noqa: E402
    KEYED_CONTRACT_NAMESPACE, REQUIRED_STRATA, _fingerprint, _keyed_contract_payload,
    canonical_bytes, digest, issue_keyed_blind_packages, publish_keyed_queue_manifest,
    validate_keyed_custodian_contract, validate_manifest,
)


class KeyedCustodianProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="keyed-parser-review-")); self.addCleanup(shutil.rmtree, self.temp, True)
        self.release = self.temp / "release"; self.release.mkdir(); self.external = self.temp / "restricted"; self.external.mkdir()

    def _contract(self) -> tuple[Path, Path, Path]:
        assignments = [
            {"assignment_id": f"assignment_{role}_{index:032x}", "reviewer": role}
            for role in ("annotator_a", "annotator_b") for index in range(200)
        ]
        ledger = self.external / "assignments.jsonl"; ledger.write_bytes(b"".join(canonical_bytes(row) for row in assignments))
        packets = self.external / "packets"; packets.mkdir()
        packet_hashes = {}
        for role in ("annotator_a", "annotator_b"):
            rows = [
                {"assignment_id": row["assignment_id"], "profile": {"opaque": index}, "listing": {"claim": "x"}, "strata": {key: f"bucket_{index % 2}" for key in REQUIRED_STRATA}}
                for index, row in enumerate(assignments) if row["reviewer"] == role
            ]
            content = b"".join(canonical_bytes(row) for row in rows); (packets / f"parser-review-{role}-blind.jsonl").write_bytes(content); packet_hashes[role] = digest(content)
        private = self.external / "custodian"; subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
        public = private.with_suffix(".pub").read_text(encoding="utf-8").strip()
        contract = {
            "schema_version": "1.0-p3.6", "contract_type": "parser_review_keyed_custodian_contract", "cohort_id": "parser_keyed_fixture_20260817", "keyed_protocol": "sky-parser-review-keyed-hmac-v1",
            "queue_size": 200, "split_counts": {"development": 100, "heldout": 100}, "required_strata": list(REQUIRED_STRATA), "strata_distinct_value_counts": {key: 2 for key in REQUIRED_STRATA},
            "commitment_merkle_root": "A" * 64, "split_commitment": "B" * 64, "packet_sha256": packet_hashes, "assignment_ledger_sha256": digest(ledger.read_bytes()),
            "custodian_id": "parser_custodian_fixture", "public_key": public, "fingerprint": _fingerprint(public), "signature_file": "contract.sig",
        }
        contract["contract_sha256"] = digest(canonical_bytes(_keyed_contract_payload(contract)))
        path = self.external / "contract.json"; path.write_bytes(canonical_bytes(contract))
        payload = self.external / "contract.payload"; payload.write_bytes(canonical_bytes(_keyed_contract_payload(contract)))
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", KEYED_CONTRACT_NAMESPACE, str(payload)], check=True, capture_output=True)
        shutil.copyfile(payload.with_name(payload.name + ".sig"), self.external / "contract.sig")
        return path, ledger, packets

    def test_contract_publishes_non_linkable_manifest_and_issues_packets(self):
        contract, ledger, packets = self._contract()
        parsed = json.loads(contract.read_text()); self.assertEqual(validate_keyed_custodian_contract(parsed, contract, self.release), parsed)
        manifest = publish_keyed_queue_manifest(contract, self.release / "data/review/parser-gold/review-queue-manifest.json", self.release)
        public_text = json.dumps(manifest, sort_keys=True)
        self.assertEqual(manifest["split_counts"], {"development": 100, "heldout": 100})
        self.assertEqual(validate_manifest(manifest), [])
        for forbidden in ("input_sha256", "input_commitment", "queue_id", '"split"', "profile", "listing", "source_sha256"):
            self.assertNotIn(forbidden, public_text)
        result = issue_keyed_blind_packages(contract, ledger, packets, self.external / "handoff", self.release)
        self.assertEqual(result["status"], "external_keyed_blind_packets_issued")
        self.assertTrue((self.external / "handoff/parser-review-annotator_a-blind.jsonl").is_file())

    def test_unsigned_or_linkable_contract_or_packet_is_rejected(self):
        contract, ledger, packets = self._contract(); data = json.loads(contract.read_text())
        signature = (self.external / "contract.sig").read_bytes(); (self.external / "contract.sig").unlink()
        with self.assertRaises(ValueError): publish_keyed_queue_manifest(contract, self.external / "manifest.json", self.release)
        # Restore the signed contract, then prove packet fields cannot leak split linkage.
        (self.external / "contract.sig").write_bytes(signature)
        packet = packets / "parser-review-annotator_a-blind.jsonl"; rows = [json.loads(line) for line in packet.read_text().splitlines()]; rows[0]["split"] = "heldout"; packet.write_bytes(b"".join(canonical_bytes(row) for row in rows))
        with self.assertRaises(ValueError): issue_keyed_blind_packages(contract, ledger, packets, self.external / "handoff", self.release)


if __name__ == "__main__":
    unittest.main()
