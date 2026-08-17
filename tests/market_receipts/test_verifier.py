import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.market_receipts.verifier import (
    AUTHORITY_SCHEMA, ARCHIVE_SCHEMA, NAMESPACE, canonical_bytes, sha256_bytes,
    signature_payload, verify_receipt_archive, disclosure_matches_authorized_sale, _fingerprint,
)
from tools.market_authorization import AuthorizedMarketEvaluator


REPO_ROOT = Path(__file__).resolve().parents[2]


class ReceiptArchiveVerifierTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.external = Path(self.temp.name)
        self.keys = []
        for name, group in (("settlement", "payments"), ("witness", "counterparty")):
            private = self.external / name
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
            public = private.with_suffix(".pub").read_text(encoding="utf-8").strip()
            self.keys.append((name, group, private, public, _fingerprint(public)))

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, path, value):
        path.write_bytes(canonical_bytes(value))
        return sha256_bytes(path.read_bytes())

    def _bundle(self, *, same_group=False, revoked=False):
        authorities = []
        for index, (name, group, _private, public, fingerprint) in enumerate(self.keys):
            authorities.append({"issuer_id": f"issuer_{name}", "public_key": public, "fingerprint": fingerprint, "independence_group": "payments" if same_group else group})
        return {"schema_version": AUTHORITY_SCHEMA, "authorities": authorities, "revoked_fingerprints": [self.keys[0][4]] if revoked else []}

    def _archive(self, *, price=10000, pii=False, evidence_classes=("settlement_receipt", "independent_completion_attestation")):
        disclosure = {
            "sale_event_id": "sale_event_fixture_one", "observation_id": "observation_fixture_one",
            "training_example_id": "training_example_fixture_one", "training_example_digest": "A" * 64,
            "observation_row_digest": "B" * 64, "seller_identity_commitment_sha256": "C" * 64,
            "sale_price_twd": price, "sale_completed_at": "2026-08-01T12:00:00Z", "currency": "TWD", "server": "international",
            "evidence_assertions": [],
        }
        for number, (name, _group, private, _public, _fingerprint_value) in enumerate(self.keys):
            assertion = {"assertion_id": f"assertion_{name}", "issuer_id": f"issuer_{name}", "evidence_class": evidence_classes[number], "issued_at": "2026-08-02T00:00:00Z"}
            payload = signature_payload("archive_fixture", disclosure, assertion)
            assertion["payload_sha256"] = sha256_bytes(payload)
            input_path = self.external / f"payload-{name}"
            input_path.write_bytes(payload)
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", NAMESPACE, str(input_path)], check=True, capture_output=True)
            assertion["signature"] = base64.b64encode(input_path.with_suffix(input_path.suffix + ".sig").read_bytes()).decode("ascii")
            disclosure["evidence_assertions"].append(assertion)
        if pii:
            disclosure["evidence_assertions"][0]["contact_name"] = "Alice"
        disclosure["disclosure_digest"] = sha256_bytes(canonical_bytes(disclosure))
        return {"schema_version": ARCHIVE_SCHEMA, "archive_id": "archive_fixture", "issued_at": "2026-08-01T00:00:00Z", "expires_at": "2030-01-01T00:00:00Z", "disclosures": [disclosure]}

    def _verify(self, archive, bundle):
        archive_path, bundle_path = self.external / "archive.json", self.external / "authority.json"
        archive_sha, bundle_sha = self._write(archive_path, archive), self._write(bundle_path, bundle)
        return verify_receipt_archive(REPO_ROOT, archive_path, archive_sha, bundle_path, bundle_sha)

    def test_valid_external_minimal_disclosure_replays(self):
        result = self._verify(self._archive(), self._bundle())
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(1, len(result.disclosures))
        expected = {"observation_id": "observation_fixture_one", "training_example_id": "training_example_fixture_one", "training_example_digest": "A" * 64, "observation_row_digest": "B" * 64, "identity_mapping_commitment_sha256": "C" * 64, "price_twd": 10000, "completed_sale_date": "2026-08-01", "currency": "TWD", "server": "international"}
        self.assertTrue(disclosure_matches_authorized_sale(result.disclosures[0], expected))
        expected["price_twd"] = 10001
        self.assertFalse(disclosure_matches_authorized_sale(result.disclosures[0], expected))
        expected["price_twd"] = 10000; expected["completed_sale_date"] = "2026-08-02"
        self.assertFalse(disclosure_matches_authorized_sale(result.disclosures[0], expected))
        expected["completed_sale_date"] = "2026-08-01"; expected["identity_mapping_commitment_sha256"] = "D" * 64
        self.assertFalse(disclosure_matches_authorized_sale(result.disclosures[0], expected))

    def test_authorization_evaluator_accepts_only_receipt_bound_sale_observation(self):
        observation = {
            "observation_id": "observation_fixture_one", "price_line": "verified_sale",
            "price_twd": 10000, "post_date": "2026-08-01", "date_verified": True,
            "currency": "TWD", "currency_verified": True, "server": "international",
            "server_verified": True, "offer_kind": "seller_listing", "entity_kind": "single_account",
        }
        key = ("authorization_record_fixture", "authorized_market_fixture", "observation_fixture_one", "A" * 64, "B" * 64)
        row = {
            "market_data_authorization": dict(zip(("authorization_record_id", "dataset_id", "observation_id", "row_digest", "manifest_sha256"), key)),
            "price_type": "verified_sale", "selected_price_twd": 10000, "post_date": "2026-08-01",
            "date_verified": True, "currency": "TWD", "currency_verified": True,
            "server": "international", "server_verified": True,
            "offer_kind": "seller_listing", "entity_kind": "single_account",
        }
        unbound = AuthorizedMarketEvaluator(((key, {"observation": observation}),))
        bound = AuthorizedMarketEvaluator(((key, {"observation": observation}),), receipt_bound_observation_ids=("observation_fixture_one",))
        self.assertFalse(unbound(row))
        self.assertTrue(bound(row))

    def test_rejects_bad_bytes_independent_issuers_and_semantic_tamper(self):
        archive, bundle = self._archive(), self._bundle()
        archive_path, bundle_path = self.external / "archive.json", self.external / "authority.json"
        archive_sha, bundle_sha = self._write(archive_path, archive), self._write(bundle_path, bundle)
        archive_path.write_text("{}", encoding="utf-8")
        result = verify_receipt_archive(REPO_ROOT, archive_path, archive_sha, bundle_path, bundle_sha)
        self.assertFalse(result.valid); self.assertIn("external receipt archive SHA-256 does not match injected bytes", result.errors)

        result = self._verify(self._archive(), self._bundle(same_group=True))
        self.assertFalse(result.valid); self.assertTrue(any("not independent" in error for error in result.errors))

        result = self._verify(self._archive(evidence_classes=("independent_completion_attestation", "independent_completion_attestation")), self._bundle())
        self.assertFalse(result.valid); self.assertTrue(any("settlement receipt" in error for error in result.errors))

        duplicate_key_bundle = self._bundle()
        duplicate_key_bundle["authorities"][1]["public_key"] = duplicate_key_bundle["authorities"][0]["public_key"]
        duplicate_key_bundle["authorities"][1]["fingerprint"] = duplicate_key_bundle["authorities"][0]["fingerprint"]
        self.assertFalse(self._verify(self._archive(), duplicate_key_bundle).valid)

        archive = self._archive(); archive["disclosures"][0]["sale_price_twd"] = 9999
        result = self._verify(archive, self._bundle())
        self.assertFalse(result.valid); self.assertTrue(any("digest does not bind" in error or "signature does not bind" in error for error in result.errors))

    def test_rejects_pii_reuse_revocation_and_release_root_inputs(self):
        result = self._verify(self._archive(pii=True), self._bundle())
        self.assertFalse(result.valid); self.assertTrue(any("allowlist" in error or "PII" in error for error in result.errors))

        result = self._verify(self._archive(), self._bundle(revoked=True))
        self.assertFalse(result.valid); self.assertTrue(any("revoked" in error for error in result.errors))

        archive = self._archive(); archive["disclosures"].append(dict(archive["disclosures"][0]))
        result = self._verify(archive, self._bundle())
        self.assertFalse(result.valid); self.assertTrue(any("replayed" in error for error in result.errors))

        local = REPO_ROOT / "receipt-test-not-external.json"
        try:
            sha = self._write(local, self._archive())
            bundle_path = self.external / "authority.json"; bundle_sha = self._write(bundle_path, self._bundle())
            result = verify_receipt_archive(REPO_ROOT, local, sha, bundle_path, bundle_sha)
            self.assertFalse(result.valid); self.assertIn("external receipt archive must be outside the release root", result.errors)
        finally:
            if local.exists():
                local.unlink()


if __name__ == "__main__":
    unittest.main()
