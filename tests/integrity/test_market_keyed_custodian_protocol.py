from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.market_review.keyed_custodian import (CONTRACT_NAMESPACE, _contract_payload,
    _fingerprint, canonical_bytes, digest, issue_existing_packets, publish_manifest,
    validate_contract)
from tools.validate.schema_validator import OfflineSchemaValidator


class MarketKeyedCustodianProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="market-keyed-custodian-")); self.addCleanup(shutil.rmtree, self.temp, True)
        self.release = self.temp / "release"; self.release.mkdir(); self.external = self.temp / "restricted"; self.external.mkdir()

    def fixture(self):
        assignments = [{"assignment_id": f"market_assignment_{role}_{index:032x}", "reviewer": role} for role in ("annotator_a", "annotator_b") for index in range(200)]
        ledger = self.external / "assignments.jsonl"; ledger.write_bytes(b"".join(canonical_bytes(row) for row in assignments))
        packets = self.external / "packets"; packets.mkdir(); packet_sha = {}
        for role in ("annotator_a", "annotator_b"):
            rows = [{"assignment_id": row["assignment_id"], "review_payload": {"claim_text": f"restricted claim {index}", "requested_fields": ["price", "currency"]}} for index, row in enumerate(assignments) if row["reviewer"] == role]
            content = b"".join(canonical_bytes(row) for row in rows); (packets / f"market-review-{role}-restricted.jsonl").write_bytes(content); packet_sha[role] = digest(content)
        private = self.external / "custodian"; subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
        public = private.with_suffix(".pub").read_text(encoding="utf-8").strip(); fingerprint = _fingerprint(public)
        authority = self.external / "authorities.json"; authority.write_bytes(canonical_bytes({"schema_version":"sky-market-keyed-custodian-authority-bundle-v1", "authorities":[{"authority_id":"market_custodian_authority_fixture", "public_key":public, "fingerprint":fingerprint, "roles":["keyed_market_custodian_contract"]}], "revoked_fingerprints":[]}))
        contract = {"schema_version":"1.0-p4.1", "contract_type":"market_review_keyed_custodian_contract", "cohort_id":"market_keyed_fixture_20260817", "keyed_protocol":"sky-market-review-keyed-custodian-v1", "queue_size":200, "assignment_count":400, "packet_counts":{"annotator_a":200,"annotator_b":200}, "commitment_merkle_root":"A"*64, "split_commitment":"B"*64, "packet_sha256":packet_sha, "assignment_ledger_sha256":digest(ledger.read_bytes()), "custodian_id":"market_custodian_fixture", "authority_id":"market_custodian_authority_fixture", "fingerprint":fingerprint, "signature_file":"contract.sig"}
        contract["contract_sha256"] = digest(canonical_bytes(_contract_payload(contract)))
        contract_path = self.external / "contract.json"; contract_path.write_bytes(canonical_bytes(contract)); payload = self.external / "payload"; payload.write_bytes(canonical_bytes(_contract_payload(contract)))
        subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", str(private), "-n", CONTRACT_NAMESPACE, str(payload)], check=True); shutil.copyfile(payload.with_name(payload.name + ".sig"), self.external / "contract.sig")
        return contract_path, ledger, packets, authority, digest(authority.read_bytes())

    def test_signed_contract_public_aggregate_and_existing_packets(self):
        contract, ledger, packets, authority, authority_sha = self.fixture()
        parsed = json.loads(contract.read_text()); self.assertEqual(validate_contract(parsed, contract, self.release, authority, authority_sha), parsed)
        manifest = publish_manifest(contract, self.release / "data/review/market-keyed-queue-manifest.json", self.release, authority_bundle=authority, authority_bundle_sha256=authority_sha)
        self.assertEqual(manifest["queue_size"], 200); self.assertEqual(manifest["packet_counts"], {"annotator_a":200,"annotator_b":200})
        text = json.dumps(manifest, sort_keys=True)
        for forbidden in ("listing_id", "listing_hash", "review_id", "input_sha256", '"split"', "assignment_ledger"): self.assertNotIn(forbidden, text)
        errors = OfflineSchemaValidator(Path(__file__).resolve().parents[2] / "schemas").validate(manifest, Path(__file__).resolve().parents[2] / "schemas/review/market-keyed-public-manifest.schema.json"); self.assertFalse(errors)
        result = issue_existing_packets(contract, ledger, packets, self.external / "handoff", self.release, authority_bundle=authority, authority_bundle_sha256=authority_sha)
        self.assertEqual(result["status"], "external_keyed_restricted_packets_verified"); self.assertTrue((self.external / "handoff/market-review-annotator_a-restricted.jsonl").is_file())

    def test_tampering_linkage_revocation_and_paths_fail_closed(self):
        contract, ledger, packets, authority, authority_sha = self.fixture()
        with self.assertRaisesRegex(ValueError, "approved release-root"):
            publish_manifest(contract, self.external / "manifest.json", self.release, authority_bundle=authority, authority_bundle_sha256=authority_sha)
        packet = packets / "market-review-annotator_a-restricted.jsonl"; rows = [json.loads(line) for line in packet.read_text().splitlines()]; rows[0]["review_id"] = "market_claim_review_0001"; packet.write_bytes(b"".join(canonical_bytes(row) for row in rows))
        with self.assertRaisesRegex(ValueError, "digest|linkable"):
            issue_existing_packets(contract, ledger, packets, self.external / "handoff", self.release, authority_bundle=authority, authority_bundle_sha256=authority_sha)
        bundle = json.loads(authority.read_text()); bundle["revoked_fingerprints"] = [bundle["authorities"][0]["fingerprint"]]; authority.write_bytes(canonical_bytes(bundle))
        with self.assertRaisesRegex(ValueError, "revoked|identity"):
            validate_contract(json.loads(contract.read_text()), contract, self.release, authority, digest(authority.read_bytes()))

    def test_missing_signature_and_ledger_replay_are_rejected(self):
        contract, ledger, packets, authority, authority_sha = self.fixture(); signature = self.external / "contract.sig"; signature.unlink()
        with self.assertRaisesRegex(ValueError, "signature"):
            validate_contract(json.loads(contract.read_text()), contract, self.release, authority, authority_sha)
        # A replacement unsigned contract cannot make the duplicate assignment ledger valid.
        signature.write_bytes(b"not-a-signature")
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]; rows[1]["assignment_id"] = rows[0]["assignment_id"]; ledger.write_bytes(b"".join(canonical_bytes(row) for row in rows))
        with self.assertRaises(ValueError):
            issue_existing_packets(contract, ledger, packets, self.external / "handoff", self.release, authority_bundle=authority, authority_bundle_sha256=authority_sha)

    def test_second_packet_failure_is_transactional_and_schema_matches_runtime(self):
        contract, ledger, packets, authority, authority_sha = self.fixture()
        second = packets / "market-review-annotator_b-restricted.jsonl"
        second.write_bytes(second.read_bytes() + b"{}\n")
        output = self.external / "handoff"
        with self.assertRaisesRegex(ValueError, "digest"):
            issue_existing_packets(contract, ledger, packets, output, self.release, authority_bundle=authority, authority_bundle_sha256=authority_sha)
        self.assertFalse(output.exists())
        output.mkdir(); (output / "sentinel").write_text("foreign", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            issue_existing_packets(contract, ledger, packets, output, self.release, authority_bundle=authority, authority_bundle_sha256=authority_sha)
        schemas = Path(__file__).resolve().parents[2] / "schemas"; validator = OfflineSchemaValidator(schemas)
        bad_assignment = {"assignment_id":"market_assignment_annotator_b_" + "0" * 32, "reviewer":"annotator_a"}
        self.assertTrue(validator.validate(bad_assignment, schemas / "review/market-keyed-assignment-ledger.schema.json"))
        bad_packet = {"assignment_id":"market_assignment_annotator_a_" + "0" * 32, "review_payload":{"nested":{"split":"heldout"}}}
        self.assertTrue(validator.validate(bad_packet, schemas / "review/market-keyed-restricted-packet.schema.json"))

    def test_destination_race_preserves_foreign_packet(self):
        contract, ledger, packets, authority, authority_sha = self.fixture(); output = self.external / "handoff"
        second = output / "market-review-annotator_b-restricted.jsonl"; original_open = Path.open
        def race_open(path, mode="r", *args, **kwargs):
            if path == second and mode == "xb" and not path.exists():
                path.write_bytes(b"foreign-packet")
            return original_open(path, mode, *args, **kwargs)
        with patch("tools.market_review.keyed_custodian.Path.open", new=race_open):
            with self.assertRaises(FileExistsError):
                issue_existing_packets(contract, ledger, packets, output, self.release, authority_bundle=authority, authority_bundle_sha256=authority_sha)
        self.assertEqual(b"foreign-packet", second.read_bytes())
        self.assertFalse((output / "market-review-annotator_a-restricted.jsonl").exists())


if __name__ == "__main__": unittest.main()
