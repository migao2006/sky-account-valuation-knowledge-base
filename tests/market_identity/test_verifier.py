import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from tools.market_identity.verifier import canonical_bytes, identity_attestation_payload, sha256_bytes, verify_identity_mapping


class IdentityMappingVerifierTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "release"; self.root.mkdir()
        self.external = self.base / "external"; self.external.mkdir()
        self.binding = self._binding()
        self._write_material()

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, path, value):
        path.write_bytes(canonical_bytes(value))

    def _binding(self):
        observation = {"observation_id": "observation_fixture", "source_snapshot_sha256": "A" * 64, "dedup_cluster_id": "cluster_fixture", "post_date": "2026-08-01"}
        example = {"training_example_id": "training_example_fixture", "training_example_digest": "B" * 64, "account_id": "account_fixture", "dedup_cluster_id": "cluster_fixture", "dedup_cluster_digest": "C" * 64}
        dataset = {"dataset_id": "authorized_market_fixture", "authorization_record_id": "authorization_record_fixture", "manifest_sha256": "D" * 64}
        manifest = {"observations_sha256": "E" * 64}
        return {"observation": observation, "training_example": example, "dataset": dataset, "manifest": manifest}

    def _row(self):
        observation = self.binding["observation"]; example = self.binding["training_example"]; dataset = self.binding["dataset"]; manifest = self.binding["manifest"]
        return {"mapping_id": "identity_mapping_fixture", "dataset_id": dataset["dataset_id"], "authorization_record_id": dataset["authorization_record_id"], "manifest_sha256": dataset["manifest_sha256"], "observations_sha256": manifest["observations_sha256"], "training_example_id": example["training_example_id"], "training_example_digest": example["training_example_digest"], "observation_id": observation["observation_id"], "observation_row_digest": sha256_bytes(canonical_bytes(observation)), "source_snapshot_sha256": observation["source_snapshot_sha256"], "account_id": example["account_id"], "dedup_cluster_id": example["dedup_cluster_id"], "dedup_cluster_digest": example["dedup_cluster_digest"], "identity_commitment": "F" * 64, "identity_commitment_scheme": "resolver-hmac-sha256-v1", "review_scope": "restricted-licensed-source-identity-resolution", "reviewed_at": "2026-08-02"}

    def _write_material(self):
        row = self._row()
        self.mapping = self.external / "mapping.jsonl"; self.mapping.write_bytes(canonical_bytes(row))
        self.mapping_sha = sha256_bytes(self.mapping.read_bytes())
        authorities = []
        self.keys = []
        for number, role in enumerate(("identity_resolver", "identity_dedup_reviewer")):
            key = self.external / f"key{number}"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
            public = key.with_suffix(".pub").read_text(encoding="utf-8").strip()
            fingerprint = subprocess.run(["ssh-keygen", "-lf", str(key.with_suffix(".pub"))], text=True, capture_output=True, check=True).stdout.split()[1]
            authorities.append({"authority_id": f"identity_{role}", "public_key": public, "fingerprint": fingerprint, "roles": [role]})
            self.keys.append(key)
        self.bundle = self.external / "bundle.json"; self._write(self.bundle, {"schema_version": "market-identity-authority-bundle-v1", "authorities": authorities, "revoked_fingerprints": []})
        self.bundle_sha = sha256_bytes(self.bundle.read_bytes())
        root = {"dataset_id": "authorized_market_fixture", "manifest_sha256": "D" * 64, "observations_sha256": "E" * 64}
        claim = {"schema_version": "market-identity-statement-v1", "mapping_sha256": self.mapping_sha, "dataset_roots": [root], "expires_at": (date.today() + timedelta(days=30)).isoformat(), "attestations": []}
        for number, role in enumerate(("identity_resolver", "identity_dedup_reviewer")):
            authority = authorities[number]
            receipt = {"role": role, "authority_id": authority["authority_id"], "fingerprint": authority["fingerprint"], "signature_file": f"{role}.sig"}
            receipt["payload_sha256"] = sha256_bytes(identity_attestation_payload(self.bundle_sha, self.mapping_sha, claim, receipt))
            payload = self.external / f"{role}.payload"; payload.write_bytes(identity_attestation_payload(self.bundle_sha, self.mapping_sha, claim, receipt))
            subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", str(self.keys[number]), "-n", "sky-market-identity-v1", str(payload)], check=True)
            shutil.copyfile(str(payload) + ".sig", self.external / receipt["signature_file"])
            claim["attestations"].append(receipt)
        self.statement = self.external / "statement.json"; self._write(self.statement, claim)
        self.statement_sha = sha256_bytes(self.statement.read_bytes())

    def args(self):
        return (self.bundle, self.bundle_sha, self.mapping, self.mapping_sha, self.statement, self.statement_sha)

    def test_complete_external_mapping_replays(self):
        errors, index = verify_identity_mapping(self.root, [self.binding], *self.args())
        self.assertEqual([], errors)
        self.assertEqual({("authorized_market_fixture", "training_example_fixture")}, set(index))

    def test_changed_account_or_missing_mapping_fails(self):
        row = self._row(); row["account_id"] = "account_other"
        self.mapping.write_bytes(canonical_bytes(row)); mapping_sha = sha256_bytes(self.mapping.read_bytes())
        errors, _ = verify_identity_mapping(self.root, [self.binding], self.bundle, self.bundle_sha, self.mapping, mapping_sha, self.statement, self.statement_sha)
        self.assertTrue(any("does not bind" in error or "does not cover" in error for error in errors))

    def test_local_mapping_is_rejected(self):
        local = self.root / "mapping.jsonl"; shutil.copyfile(self.mapping, local)
        errors, _ = verify_identity_mapping(self.root, [self.binding], self.bundle, self.bundle_sha, local, sha256_bytes(local.read_bytes()), self.statement, self.statement_sha)
        self.assertTrue(any("outside the release root" in error for error in errors))

