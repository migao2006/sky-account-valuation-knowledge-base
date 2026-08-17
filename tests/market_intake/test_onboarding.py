import json
import tempfile
import unittest
from pathlib import Path

from tools.market_authorization import _valid_observation, canonical_bytes, sha256_bytes, training_example_commitment
from tools.market_intake.onboarding import IntakeError, build, canonical_signing_payload, sha256
from tools.validate.schema_validator import OfflineSchemaValidator
from tools.modeling.catalog_provenance import catalog_provenance
from tools.modeling.catalog_provenance import read_jsonl
from tools.modeling.market_feature_contract import VERSION
from tools.modeling.publication_dataset import _derive_split, freeze


REPO_ROOT = Path(__file__).resolve().parents[2]


def digest(label: str | bytes) -> str:
    return sha256(label if isinstance(label, bytes) else label.encode("utf-8"))


def record(number: int, day: str = "2026-08-01") -> dict:
    states = [{"item_id": row["item_id"], "state": "owned" if index == number % 123 else "unknown", "evidence_state": "profile_claim", "conflict": False} for index, row in enumerate(read_jsonl(REPO_ROOT / "knowledge/items/items.jsonl"))]
    payload = {"feature_contract_version": VERSION, "feature_groups": {"base_account": {"account_type": "unknown", "wing_state": "unknown", "special_appearance": []}, "season_profiles": [], "item_sets": [], "collection": {"bundle_claim_level": "unknown"}, "resources": {"values": {"white_candles": number, "hearts": None, "red_candles": None, "season_candles": None}}, "map_completion": {"standard_maps": "unknown", "second_tier_capes": "unknown"}, "bindings": {"risk_state": "unknown", "platforms": [{"platform": platform, "status": "unknown"} for platform in ("google", "apple", "game_center", "facebook", "nintendo", "playstation", "steam", "huawei", "twitter")]}, "ownership_history": "unknown"}, "item_states": states}
    return {
        "dedup_cluster_digest": digest(f"cluster-{number}"),
        "account_commitment_digest": digest(f"account-{number}"), "post_date": day,
        "currency": "TWD", "server": "international", "offer_kind": "seller_listing", "entity_kind": "single_account",
        "price_line": "asking", "price_twd": 1000 + number,
        "feature_payload": payload,
        "catalog_provenance": catalog_provenance(REPO_ROOT), "catalog_provenance_sha256": digest(canonical_bytes(catalog_provenance(REPO_ROOT))),
    }


class MarketProviderOnboardingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.external = Path(self.temp.name) / "external"; self.external.mkdir()
        self.staging = self.external / "staging.json"
        self.output = self.external / "output"

    def tearDown(self):
        self.temp.cleanup()

    def write_stage(self, rows):
        for index, row in enumerate(rows):
            snapshot = self.external / f"immutable-source-{index}.bin"
            snapshot.write_bytes(f"restricted-source-byte-{index}".encode("utf-8"))
            row["source_snapshot_path"] = str(snapshot)
            row["source_snapshot_sha256"] = sha256(snapshot.read_bytes())
        value = {"schema_version": "authorized-market-staging-v1", "dataset_id": "authorized_market_provider_fixture", "authorization_record_id": "authorization_record_provider_fixture", "expires_at": "2027-01-01", "records": rows}
        self.staging.write_bytes(canonical_bytes(value))
        return sha256(self.staging.read_bytes())

    def test_build_is_deterministic_and_outputs_v2_contract(self):
        checksum = self.write_stage([record(2, "2026-08-02"), record(1, "2026-08-01")])
        validator = OfflineSchemaValidator(REPO_ROOT / "schemas")
        self.assertEqual([], validator.validate(json.loads(self.staging.read_text()), REPO_ROOT / "schemas/market/authorized-market-staging.schema.json"))
        result = build(REPO_ROOT, self.staging, checksum, self.output, "v2")
        observations = [json.loads(line) for line in (self.output / "observations.jsonl").read_text().splitlines()]
        examples = [json.loads(line) for line in (self.output / "training-examples.jsonl").read_text().splitlines()]
        self.assertEqual([], [error for row in observations for error in validator.validate(row, REPO_ROOT / "schemas/market/authorized-market-observation.schema.json")])
        self.assertEqual([], [error for row in examples for error in validator.validate(row, REPO_ROOT / "schemas/market/authorized-market-training-example.schema.json")])
        self.assertEqual([], validator.validate(result["manifest"], REPO_ROOT / "schemas/market/authorized-market-manifest.schema.json"))
        self.assertEqual(2, len(observations)); self.assertTrue(all(_valid_observation(row, "authorized-market-manifest-v2") for row in observations))
        self.assertEqual(2, len(examples))
        self.assertTrue(all(row["training_example_digest"] == sha256_bytes(canonical_bytes(training_example_commitment(row))) for row in examples))
        self.assertTrue(all(row["source_snapshot_sha256"] == example["source_snapshot_sha256"] for row, example in zip(sorted(observations, key=lambda value: value["observation_id"]), sorted(examples, key=lambda value: value["observation_id"]))))
        self.assertFalse((self.output / "source-lineage.json").exists())
        self.assertEqual("authorized-market-manifest-v2", result["manifest"]["schema_version"])
        self.assertIsNone(result["registry_candidate"]["statement_sha256"])
        self.assertFalse(result["capacity_report"]["date_split"]["requirements_met"])
        self.assertFalse(result["capacity_report"]["independence_verified"])
        self.assertEqual((self.output / "observations.jsonl").read_bytes(), b"".join(canonical_bytes(row) for row in observations))

    def test_tampered_staging_digest_fails(self):
        checksum = self.write_stage([record(1)])
        self.staging.write_bytes(self.staging.read_bytes() + b" ")
        with self.assertRaisesRegex(IntakeError, "SHA-256"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_tampered_immutable_source_bytes_fail_even_with_unchanged_staging(self):
        checksum = self.write_stage([record(1)])
        stage = json.loads(self.staging.read_text())
        Path(stage["records"][0]["source_snapshot_path"]).write_bytes(b"tampered restricted bytes")
        with self.assertRaisesRegex(IntakeError, "immutable source snapshot SHA-256"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_pii_raw_text_url_and_handle_fail_preflight(self):
        bad = record(1); bad["feature_payload"] = {"caption": "seller says hello", "url": "https://example.test", "owner_handle": "@secret"}
        checksum = self.write_stage([bad])
        with self.assertRaisesRegex(IntakeError, "PII/raw text/URL/handle"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_nested_numeric_phone_and_taiwan_id_fail_preflight(self):
        bad = record(1); bad["feature_payload"] = {"nested": {"opaque_value": "912345678", "other": "A123456789"}}
        checksum = self.write_stage([bad])
        with self.assertRaisesRegex(IntakeError, "PII/raw text/URL/handle"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_numeric_json_phone_and_cjk_name_fail_preflight(self):
        bad = record(1); bad["feature_payload"] = {"feature_groups": {"base_account": {"account_type": "unknown", "contact_value": 912345678, "opaque_label": "陳小明"}}}
        checksum = self.write_stage([bad])
        with self.assertRaisesRegex(IntakeError, "PII/raw text/URL/handle"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_arbitrary_latin_handle_value_or_key_fails_allowlist(self):
        bad = record(1); bad["feature_payload"] = {"feature_groups": {"base_account": {"account_type": "AliceSecretHandle"}}}
        checksum = self.write_stage([bad])
        with self.assertRaisesRegex(IntakeError, "runtime contract"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")
        bad = record(2); bad["feature_payload"] = {"feature_groups": {"base_account": {"account_type": "unknown", "opaque_label": "AliceSecretHandle"}}}
        checksum = self.write_stage([bad])
        with self.assertRaisesRegex(IntakeError, "unsupported"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_runtime_feature_contract_and_catalog_digest_required(self):
        bad = record(1); bad["feature_payload"] = {"vector_schema": "fixture-v1"}
        checksum = self.write_stage([bad])
        with self.assertRaisesRegex(IntakeError, "runtime contract"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_400_row_bundle_is_consumable_by_publication_freeze(self):
        catalog = catalog_provenance(REPO_ROOT)
        rows = []
        for number in range(400):
            # 300 early and 100 later clusters make a genuine time-forward
            # capacity cohort without inventing a price or feature.
            day = "2026-01-01" if number < 300 else "2026-02-01"
            value = record(number + 1, day)
            value["catalog_provenance"] = catalog
            value["catalog_provenance_sha256"] = digest(canonical_bytes(catalog))
            rows.append(value)
        checksum = self.write_stage(rows)
        build(REPO_ROOT, self.staging, checksum, self.output, "v2")
        observations = [json.loads(line) for line in (self.output / "observations.jsonl").read_text().splitlines()]
        examples = [json.loads(line) for line in (self.output / "training-examples.jsonl").read_text().splitlines()]
        by_observation = {row["observation_id"]: row for row in observations}
        clean, vectors = [], []
        for index, example in enumerate(examples):
            observation = by_observation[example["observation_id"]]
            vectors.append(example["feature_payload"])
            clean.append({"cleaned_price_id": f"cleaned_{index:04d}", "history_id": f"history_{index:04d}", "account_id": example["account_id"], "cluster_id": example["dedup_cluster_id"], "currency": "TWD", "server": "international", "price_line": "normal_listing", "selected_price_twd": observation["price_twd"], "post_date": observation["post_date"], "date_verified": True, "training_example_id": example["training_example_id"], "training_example_digest": example["training_example_digest"], "feature_payload_sha256": example["feature_payload_sha256"], "catalog_provenance_sha256": example["catalog_provenance_sha256"], "dedup_cluster_digest": example["dedup_cluster_digest"]})
        registered = [{**example, "_registered_observation": by_observation[example["observation_id"]]} for example in examples]
        manifest = freeze(clean, vectors, catalog, [], registered)
        self.assertEqual(400, manifest["dataset_row_count"])
        # This is intentionally synthetic staging data, never a registry
        # entry.  Its SHA-256 commitments are nevertheless generated by the
        # real intake and it must exercise the exact production split logic.
        split = _derive_split(manifest, allow_test_synthetic=False)
        self.assertEqual("ready_for_evaluation", split["status"])
        pool = split["market_pools"][0]
        self.assertEqual((300, 100), (len(pool["training_cluster_ids"]), len(pool["holdout_cluster_ids"])))
        self.assertFalse(build(REPO_ROOT, self.staging, checksum, self.output, "v2")["capacity_report"]["date_split"]["requirements_met"])
        bad = record(2); bad["catalog_provenance_sha256"] = "A" * 64
        checksum = self.write_stage([bad])
        with self.assertRaisesRegex(IntakeError, "catalog_provenance SHA-256"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")
        bad = record(3); bad["catalog_provenance"] = {"catalog_sha256": "A" * 64}; bad["catalog_provenance_sha256"] = digest(canonical_bytes(bad["catalog_provenance"]))
        checksum = self.write_stage([bad])
        with self.assertRaisesRegex(IntakeError, "differs from the current release catalog"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_duplicate_cluster_event_or_account_fails(self):
        first, second = record(1), record(2)
        second["dedup_cluster_digest"] = first["dedup_cluster_digest"]
        checksum = self.write_stage([first, second])
        with self.assertRaisesRegex(IntakeError, "duplicate dedup_cluster_digest"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_duplicate_derived_id_via_same_source_bytes_fails(self):
        first, second = record(1), record(2)
        checksum = self.write_stage([first, second])
        stage = json.loads(self.staging.read_text())
        first_path = Path(stage["records"][0]["source_snapshot_path"])
        second_path = Path(stage["records"][1]["source_snapshot_path"])
        second_path.write_bytes(first_path.read_bytes())
        stage["records"][1]["source_snapshot_sha256"] = stage["records"][0]["source_snapshot_sha256"]
        self.staging.write_bytes(canonical_bytes(stage)); checksum = sha256(self.staging.read_bytes())
        with self.assertRaisesRegex(IntakeError, "duplicate immutable source snapshot"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_prefix_collision_in_cluster_or_account_digest_fails(self):
        first, second = record(1), record(2)
        first["dedup_cluster_digest"], second["dedup_cluster_digest"] = "A" * 24 + "B" * 40, "A" * 24 + "C" * 40
        checksum = self.write_stage([first, second])
        with self.assertRaisesRegex(IntakeError, "duplicate derived dedup cluster ID"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")
        first, second = record(3), record(4)
        first["account_commitment_digest"], second["account_commitment_digest"] = "D" * 24 + "E" * 40, "D" * 24 + "F" * 40
        checksum = self.write_stage([first, second])
        with self.assertRaisesRegex(IntakeError, "duplicate derived account ID"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_invalid_date_fails(self):
        bad = record(1, "2026-02-30")
        checksum = self.write_stage([bad])
        with self.assertRaisesRegex(IntakeError, "real ISO-8601"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_expired_authorization_candidate_fails_fast(self):
        checksum = self.write_stage([record(1)])
        stage = json.loads(self.staging.read_text()); stage["expires_at"] = "2020-01-01"
        self.staging.write_bytes(canonical_bytes(stage)); checksum = sha256(self.staging.read_bytes())
        with self.assertRaisesRegex(IntakeError, "future date"):
            build(REPO_ROOT, self.staging, checksum, self.output, "v2")

    def test_insufficient_capacity_is_reported_not_fabricated(self):
        checksum = self.write_stage([record(1, "2026-01-01"), record(2, "2026-02-01")])
        result = build(REPO_ROOT, self.staging, checksum, self.output, "v2")
        split = result["capacity_report"]["date_split"]
        self.assertEqual((1, 1), (split["training_cluster_count"], split["heldout_cluster_count"]))
        self.assertFalse(split["requirements_met"])

    def test_v3_requires_structural_completed_sale_evidence(self):
        row = record(1); row.update({"price_line": "verified_sale", "completed_sale_verified": True, "sale_verified": True, "completed_sale_date": row["post_date"], "completion_evidence": [{"evidence_id": "evidence_one", "source_lineage_id": "lineage_one", "evidence_sha256": digest("one")}, {"evidence_id": "evidence_two", "source_lineage_id": "lineage_two", "evidence_sha256": digest("two")}], "independent_evidence_ids": ["evidence_one", "evidence_two"]})
        row["completion_evidence_digest"] = sha256(canonical_bytes(row["completion_evidence"]))
        checksum = self.write_stage([row])
        result = build(REPO_ROOT, self.staging, checksum, self.output, "v3")
        self.assertEqual("authorized-market-manifest-v3", result["manifest"]["schema_version"])
        observation = json.loads((self.output / "observations.jsonl").read_text())
        self.assertTrue(_valid_observation(observation, "authorized-market-manifest-v3"))

    def test_canonical_signing_payload_is_bytes_and_unsigned(self):
        candidate = {"dataset_id": "authorized_market_provider_fixture"}
        payload = canonical_signing_payload(candidate, {"dataset_id": "authorized_market_provider_fixture"}, {"schema_version": "authorized-market-statement-v1"}, {"attestation_id": "authorized_market_attestation_fixture"})
        self.assertIsInstance(payload, bytes)
        self.assertIn(b"sky-authorized-market-v1", payload)


if __name__ == "__main__":
    unittest.main()
