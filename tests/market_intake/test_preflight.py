import importlib.util
import json
import unittest
from pathlib import Path

from tools.market_intake.preflight import preflight
from tools.market_authorization import canonical_bytes, sha256_bytes


TEST_FILE = Path(__file__).resolve().parents[1] / "integrity" / "test_market_data_authorization_signatures.py"
SPEC = importlib.util.spec_from_file_location("authorization_fixtures", TEST_FILE)
FIXTURES = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(FIXTURES)


class MarketIntakePreflightTest(unittest.TestCase):
    def _fixture(self, cls):
        fixture = cls("test_valid_temp_keys_fixture_and_callable_protocol")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        return fixture

    @staticmethod
    def _args(fixture, identity=(), receipt=()):
        return (*fixture.args(), *identity, *receipt)

    def test_empty_registry_is_explicitly_not_ready(self):
        fixture = self._fixture(FIXTURES.AuthorizedMarketIntakeTest)
        (fixture.root / "data/review/market-authorization/registry.jsonl").write_bytes(b"")
        (fixture.root / "data/review/market-authorization/attestations.jsonl").write_bytes(b"")
        report = preflight(fixture.root)
        self.assertEqual("not_ready", report["status"])
        self.assertEqual(["formal_market_registry_empty"], report["reason_codes"])
        self.assertNotIn("identity_commitment", json.dumps(report))

    def test_invalid_injected_digest_does_not_make_report_schema_invalid(self):
        fixture = self._fixture(FIXTURES.AuthorizedMarketIntakeTest)
        report = preflight(fixture.root, authority_bundle_sha256="not-a-sha256")
        self.assertEqual("not_ready", report["status"])
        self.assertNotIn("authority_bundle_sha256", report["input_sha256"])

    def test_v2_needs_identity_but_not_receipts_and_true_temp_signatures_pass(self):
        fixture = self._fixture(FIXTURES.AuthorizedMarketFeatureLineageTest)
        observations, examples, manifest = fixture._write_lineage_fixture()
        identity = fixture._write_external_identity_mapping(observations, examples, manifest)
        report = preflight(fixture.root, *self._args(fixture, identity))
        self.assertEqual("ready", report["status"])
        self.assertEqual("ready", report["identity_binding_status"])
        self.assertEqual("ready", report["receipt_binding_status"])
        self.assertEqual(0, report["v3_dataset_count"])
        self.assertEqual(0, report["verification_error_count"])
        missing = preflight(fixture.root, *fixture.args())
        self.assertEqual("not_ready", missing["status"])
        self.assertIn("identity_trust_material_required_for_v2_v3", missing["reason_codes"])

    def test_legacy_v1_authorization_is_not_a_bound_training_projection(self):
        fixture = self._fixture(FIXTURES.AuthorizedMarketIntakeTest)
        report = preflight(fixture.root, *fixture.args())
        self.assertEqual("not_ready", report["status"])
        self.assertEqual("not_ready", report["training_projection_status"])
        self.assertIn("model_training_projection_not_bound", report["reason_codes"])

    def test_mapping_tamper_extra_and_expiry_fail_closed(self):
        fixture = self._fixture(FIXTURES.AuthorizedMarketFeatureLineageTest)
        observations, examples, manifest = fixture._write_lineage_fixture()
        identity = fixture._write_external_identity_mapping(observations, examples, manifest)
        mapping = identity[2]
        original = mapping.read_bytes()
        mapping.write_bytes(original + b"tamper")
        tampered = preflight(fixture.root, *self._args(fixture, identity))
        self.assertEqual("not_ready", tampered["status"])
        mapping.write_bytes(original + original)
        extra = preflight(fixture.root, *self._args(fixture, (identity[0], fixture._sha(identity[0]), mapping, fixture._sha(mapping), identity[4], fixture._sha(identity[4]))))
        self.assertEqual("not_ready", extra["status"])
        mapping.write_bytes(original)
        tamper = preflight(fixture.root, *self._args(fixture, identity))
        self.assertEqual("ready", tamper["status"])
        statement = identity[4]
        value = json.loads(statement.read_text(encoding="utf-8"))
        value["expires_at"] = "2000-01-01"
        fixture._write(statement, value)
        expired = preflight(fixture.root, *self._args(fixture, (identity[0], fixture._sha(identity[0]), identity[2], fixture._sha(identity[2]), statement, fixture._sha(statement))))
        self.assertEqual("not_ready", expired["status"])

    def test_v3_receipt_is_required_and_true_temp_receipts_pass(self):
        fixture = self._fixture(FIXTURES.VerifiedSaleExternalTrustE2ETest)
        observations, examples, manifest = fixture._write_lineage_fixture(verified_sales=True)
        identity_bundle, mapping, identity_statement, identities = fixture._write_identity_material(observations, examples, manifest)
        receipt_archive, receipt_bundle = fixture._write_receipt_material(observations, examples, identities)
        identity = (identity_bundle, fixture._sha(identity_bundle), mapping, fixture._sha(mapping), identity_statement, fixture._sha(identity_statement))
        receipt = (receipt_archive, fixture._sha(receipt_archive), receipt_bundle, fixture._sha(receipt_bundle))
        absent = preflight(fixture.root, *self._args(fixture, identity))
        self.assertEqual("not_ready", absent["status"])
        self.assertIn("receipt_trust_material_required_for_v3", absent["reason_codes"])
        report = preflight(fixture.root, *self._args(fixture, identity, receipt))
        self.assertEqual("ready", report["status"])
        self.assertEqual(1, report["v3_dataset_count"])
        self.assertNotIn("seller_identity_commitment", json.dumps(report))

    def test_cli_refuses_output_inside_release_root(self):
        fixture = self._fixture(FIXTURES.AuthorizedMarketIntakeTest)
        from tools.market_intake.preflight import _outside
        with self.assertRaises(ValueError):
            _outside(fixture.root / "report.json", fixture.root)

    def test_registry_manifest_path_cannot_escape_or_disclose_version(self):
        fixture = self._fixture(FIXTURES.AuthorizedMarketIntakeTest)
        secret = fixture.external / "secret.json"
        secret.write_text('{"schema_version":"TOP-SECRET-VALUE"}', encoding="utf-8")
        registry_path = fixture.root / "data/review/market-authorization/registry.jsonl"
        row = json.loads(registry_path.read_text(encoding="utf-8").splitlines()[0])
        row["manifest_path"] = str(secret)
        registry_path.write_bytes(canonical_bytes(row))
        report = preflight(fixture.root, *fixture.args())
        self.assertEqual("not_ready", report["status"])
        self.assertIn("formal_market_manifest_path_invalid", report["reason_codes"])
        self.assertNotIn("TOP-SECRET-VALUE", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
