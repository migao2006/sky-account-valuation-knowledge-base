"""Parser-gold attestations and held-out evaluator tests (temporary keys only)."""
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
from tools.modeling.parser_gold_evaluator import (  # noqa: E402
    ATTESTATIONS_REL, GOLD_REL, NAMESPACE, RULE_MANIFEST_REL, SIGNATURES_REL, _fingerprint,
    _validate_keyed_binding_coverage, attestation_payload, audit_gold, canonical_bytes, evaluate, gold_ledger_sha256, input_sha256,
    manifest_payload, parser_config_sha256, parser_source_sha256, sha256_bytes,
)
from tools.parser_review.onboarding import (  # noqa: E402
    KEYED_CONTRACT_NAMESPACE, _keyed_contract_payload, keyed_commitment_merkle_root,
)


class ParserGoldEvaluatorTests(unittest.TestCase):
    @staticmethod
    def _strata(index: int = 0) -> dict[str, str]:
        return {"account_type": "permanent" if index % 2 else "seasonal", "era": "legacy" if index % 2 else "modern", "season": "season_a" if index % 2 else "season_b", "collaboration": "none" if index % 2 else "yes", "set_context": "single" if index % 2 else "set"}

    def _write_manifest(self, release: Path, gold: list[dict[str, object]]) -> dict[str, object]:
        manifest: dict[str, object] = {"schema_version": "1.0-p3.3", "gold_ledger_sha256": gold_ledger_sha256(gold), "parser_source_sha256": parser_source_sha256(release), "parser_config_sha256": parser_config_sha256(), "development_input_hashes": sorted(str(row["input_sha256"]) for row in gold if row["split"] == "development"), "required_strata": ["account_type", "era", "season", "collaboration", "set_context"], "minimum_distinct_values_per_required_stratum": 2}
        manifest["manifest_sha256"] = sha256_bytes(manifest_payload(manifest))
        path = release / RULE_MANIFEST_REL; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(canonical_bytes(manifest))
        return manifest

    def _key(self, directory: Path, name: str) -> tuple[Path, str, str]:
        private = directory / name
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
        public = private.with_suffix(".pub").read_text(encoding="utf-8").strip()
        fingerprint = _fingerprint(public)
        self.assertIsNotNone(fingerprint)
        return private, public, str(fingerprint)

    def _fixture(self) -> tuple[Path, Path, str, list[dict[str, object]], list[dict[str, object]]]:
        temporary = Path(tempfile.mkdtemp(prefix="parser-gold-test-")); self.addCleanup(shutil.rmtree, temporary, True)
        release = temporary / "release"; (release / SIGNATURES_REL).mkdir(parents=True); (release / "tools/modeling").mkdir(parents=True)
        shutil.copyfile(ROOT / "tools/modeling/parse_item_vectors.py", release / "tools/modeling/parse_item_vectors.py")
        profile, listing = {"claim": "owned"}, {"offer_kind": "seller_listing"}
        gold = [{"gold_id": "parser_gold_0001", "input_sha256": input_sha256(profile, listing), "expected_canonical_item_ids": ["item_test"], "expected_polarity": "owned", "split": "heldout", "strata": self._strata(1)}]
        (release / GOLD_REL).parent.mkdir(parents=True, exist_ok=True)
        (release / GOLD_REL).write_bytes(canonical_bytes(gold[0]))
        manifest = self._write_manifest(release, gold)
        keys = temporary / "keys"; keys.mkdir(); identities = []
        for name, role in (("a", "annotator_a"), ("b", "annotator_b"), ("c", "adjudicator")):
            private, public, fingerprint = self._key(keys, name); identities.append((f"parser_human_{name}", role, private, public, fingerprint))
        attestations = []
        for index, (identity, role, private, _public, fingerprint) in enumerate(identities, 1):
            rel = (SIGNATURES_REL / f"{role}.sig").as_posix()
            entry: dict[str, object] = {"attestation_id": f"parser_gold_attestation_{index:04d}", "gold_id": "parser_gold_0001", "role": role, "authority_id": identity, "fingerprint": fingerprint, "rule_manifest_sha256": manifest["manifest_sha256"], "signature_file": rel}
            payload = attestation_payload(gold[0], manifest, entry); entry["payload_sha256"] = sha256_bytes(payload)
            payload_path = temporary / f"payload-{role}"; payload_path.write_bytes(payload)
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", NAMESPACE, str(payload_path)], check=True, capture_output=True)
            shutil.copyfile(payload_path.with_name(payload_path.name + ".sig"), release / rel); attestations.append(entry)
        (release / ATTESTATIONS_REL).parent.mkdir(parents=True, exist_ok=True)
        (release / ATTESTATIONS_REL).write_bytes(b"".join(canonical_bytes(entry) for entry in attestations))
        bundle = temporary / "authorities.json"
        bundle.write_text(json.dumps({"schema_version": "sky-parser-gold-authority-bundle-v1", "authorities": [{"authority_id": identity, "public_key": public, "fingerprint": fingerprint, "roles": [role]} for identity, role, _private, public, fingerprint in identities], "revoked_fingerprints": []}, sort_keys=True), encoding="utf-8")
        # The keyed custodian is a separate pinned authority.  The contract
        # contains no public key, and the external replay binding is signed
        # and maps this formal gold row into the 200-leaf opaque cohort.
        custodian_private, custodian_public, custodian_fingerprint = self._key(keys, "custodian")
        custodian_bundle = temporary / "custodian-authorities.json"
        custodian_bundle.write_bytes(canonical_bytes({"schema_version": "sky-parser-keyed-custodian-authority-bundle-v1", "authorities": [{"authority_id": "parser_custodian_authority_fixture", "public_key": custodian_public, "fingerprint": custodian_fingerprint, "roles": ["keyed_custodian_contract"]}], "revoked_fingerprints": []}))
        commitments = [f"{index:064X}" for index in range(1, 201)]
        contract = {"schema_version": "1.0-p3.7", "contract_type": "parser_review_keyed_custodian_contract", "cohort_id": "parser_keyed_fixture_20260817", "keyed_protocol": "sky-parser-review-keyed-hmac-v1", "queue_size": 200, "split_counts": {"development": 100, "heldout": 100}, "required_strata": ["account_type", "era", "season", "collaboration", "set_context"], "strata_distinct_value_counts": {key: 2 for key in ["account_type", "era", "season", "collaboration", "set_context"]}, "commitment_merkle_root": keyed_commitment_merkle_root(commitments), "split_commitment": "A" * 64, "packet_sha256": {"annotator_a": "B" * 64, "annotator_b": "C" * 64}, "assignment_ledger_sha256": "D" * 64, "custodian_id": "parser_custodian_fixture", "authority_id": "parser_custodian_authority_fixture", "fingerprint": custodian_fingerprint, "signature_file": "contract.sig"}
        contract["contract_sha256"] = sha256_bytes(canonical_bytes(_keyed_contract_payload(contract)))
        contract_path = temporary / "custodian-contract.json"; contract_path.write_bytes(canonical_bytes(contract))
        contract_payload = temporary / "contract-payload"; contract_payload.write_bytes(canonical_bytes(_keyed_contract_payload(contract)))
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(custodian_private), "-n", KEYED_CONTRACT_NAMESPACE, str(contract_payload)], check=True, capture_output=True); shutil.copyfile(contract_payload.with_name(contract_payload.name + ".sig"), temporary / "contract.sig")
        queue_manifest = {"schema_version": "1.0-p3.7", "status": "keyed_frozen_pending_external_decisions", "cohort_id": contract["cohort_id"], "keyed_protocol": contract["keyed_protocol"], "queue_size": 200, "split_counts": contract["split_counts"], "required_strata": contract["required_strata"], "strata_distinct_value_counts": contract["strata_distinct_value_counts"], "commitment_merkle_root": contract["commitment_merkle_root"], "split_commitment": contract["split_commitment"], "packet_sha256": contract["packet_sha256"], "assignment_ledger_sha256": contract["assignment_ledger_sha256"], "custodian_id": contract["custodian_id"], "custodian_authority_id": contract["authority_id"], "custodian_fingerprint": contract["fingerprint"], "custodian_contract_sha256": contract["contract_sha256"]}
        queue_manifest["manifest_sha256"] = sha256_bytes(canonical_bytes(queue_manifest)); queue_path = release / "data/review/parser-gold/review-queue-manifest.json"; queue_path.write_bytes(canonical_bytes(queue_manifest))
        binding = {"schema_version": "1.0-p3.7", "contract_type": "parser_review_keyed_replay_binding", "cohort_id": contract["cohort_id"], "custodian_contract_sha256": contract["contract_sha256"], "commitment_merkle_root": contract["commitment_merkle_root"], "split_commitment": contract["split_commitment"], "authority_id": contract["authority_id"], "fingerprint": custodian_fingerprint, "cohort_keyed_commitments": commitments, "binding_rows": [{"gold_id": gold[0]["gold_id"], "input_sha256": gold[0]["input_sha256"], "keyed_commitment": commitments[0], "split": gold[0]["split"]}], "signature_file": "binding.sig"}
        binding["binding_sha256"] = sha256_bytes(canonical_bytes({key: value for key, value in binding.items() if key not in {"signature_file", "binding_sha256"}}))
        binding_path = temporary / "binding.json"; binding_path.write_bytes(canonical_bytes(binding)); binding_payload = temporary / "binding-payload"; binding_payload.write_bytes(canonical_bytes({key: value for key, value in binding.items() if key not in {"signature_file", "binding_sha256"}}))
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(custodian_private), "-n", "sky-parser-keyed-replay-binding-v1", str(binding_payload)], check=True, capture_output=True); shutil.copyfile(binding_payload.with_name(binding_payload.name + ".sig"), temporary / "binding.sig")
        self._keyed = {"keyed_authority_bundle": custodian_bundle, "keyed_authority_bundle_sha256": sha256_bytes(custodian_bundle.read_bytes()), "keyed_contract": contract_path, "keyed_contract_sha256": sha256_bytes(contract_path.read_bytes()), "keyed_replay_binding": binding_path, "keyed_replay_binding_sha256": sha256_bytes(binding_path.read_bytes())}
        return release, bundle, sha256_bytes(bundle.read_bytes()), gold, [{"profile": profile, "listing": listing}]

    @staticmethod
    def _parser(profile: dict[str, object], _listing: dict[str, object], _root: Path) -> dict[str, object]:
        state = str(profile["claim"])
        return {"item_states": [{"item_id": "item_test", "state": state}]}

    def test_valid_external_root_and_replay_are_accepted(self):
        release, bundle, digest, gold, inputs = self._fixture()
        self.assertEqual(audit_gold(release, gold, bundle, digest, **self._keyed), [])
        report = evaluate(release, gold, inputs, parser=self._parser)
        self.assertEqual(report["status"], "threshold_not_met")
        self.assertEqual(report["heldout"]["precision"], 1.0)
        self.assertEqual(report["heldout"]["collision_rows"], 0)

    def test_keyed_binding_requires_injective_complete_cohort_mapping(self):
        commitments = [f"{index:064X}" for index in range(1, 201)]
        gold = [{"gold_id": f"parser_gold_{index:04d}"} for index in range(1, 201)]
        rows = [{"gold_id": row["gold_id"], "keyed_commitment": commitments[index], "split": "development" if index < 100 else "heldout"} for index, row in enumerate(gold)]
        _validate_keyed_binding_coverage(gold, rows, commitments)
        duplicated = [dict(row) for row in rows]; duplicated[-1]["keyed_commitment"] = commitments[0]
        with self.assertRaisesRegex(ValueError, "reuses a cohort commitment"):
            _validate_keyed_binding_coverage(gold, duplicated, commitments)
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            _validate_keyed_binding_coverage(gold + [{"gold_id": "parser_gold_0201"}], rows + [dict(rows[0])], commitments)

    def test_tamper_and_no_external_root_fail_closed(self):
        release, bundle, digest, gold, _inputs = self._fixture()
        self.assertTrue(audit_gold(release, gold))
        gold[0]["expected_polarity"] = "confirmed_missing"
        self.assertTrue(audit_gold(release, gold, bundle, digest, **self._keyed))

    def test_tampered_or_empty_rule_manifest_is_rejected(self):
        release, bundle, digest, gold, _inputs = self._fixture()
        (release / RULE_MANIFEST_REL).write_text("{}", encoding="utf-8")
        self.assertTrue(audit_gold(release, gold, bundle, digest, **self._keyed))

    def test_threshold_and_collision_fail_closed(self):
        release, _bundle, _digest, gold, inputs = self._fixture()
        report = evaluate(release, gold, inputs, parser=lambda *_: {"item_states": [{"item_id": "item_test", "state": "owned"}, {"item_id": "item_wrong", "state": "owned"}]})
        self.assertEqual(report["heldout"]["collision_rows"], 1)
        self.assertFalse(report["publication_ready"])
        expanded = []; expanded_inputs = []
        for index in range(200):
            profile = {"claim": "owned", "nonce": index}; listing = {"offer_kind": "seller_listing"}
            row = dict(gold[0]); row["gold_id"] = f"parser_gold_{index + 1:04d}"; row["input_sha256"] = input_sha256(profile, listing); row["split"] = "development" if index < 100 else "heldout"; row["strata"] = self._strata(index); expanded.append(row)
            expanded_inputs.append({"profile": profile, "listing": listing})
        self._write_manifest(release, expanded)
        passed = evaluate(release, expanded, expanded_inputs, parser=self._parser)
        self.assertEqual(passed["status"], "evaluated")
        self.assertTrue(passed["publication_ready"])
        failed = evaluate(release, expanded, expanded_inputs, parser=lambda *_: {"item_states": [{"item_id": "item_test", "state": "owned"}, {"item_id": "item_wrong", "state": "owned"}]})
        self.assertEqual(failed["status"], "evaluated")
        self.assertFalse(failed["publication_ready"])

    def test_199_1_split_and_single_stratum_cannot_pass(self):
        release, _bundle, _digest, gold, _inputs = self._fixture(); rows = []; inputs = []
        for index in range(200):
            profile = {"claim": "owned", "nonce": index}; listing = {"offer_kind": "seller_listing"}
            row = dict(gold[0]); row["gold_id"] = f"parser_gold_{index + 1:04d}"; row["input_sha256"] = input_sha256(profile, listing); row["split"] = "development" if index < 199 else "heldout"; row["strata"] = self._strata(0); rows.append(row); inputs.append({"profile": profile, "listing": listing})
        self._write_manifest(release, rows)
        report = evaluate(release, rows, inputs, parser=self._parser)
        self.assertEqual(report["status"], "threshold_not_met")
        self.assertFalse(report["publication_ready"])

    def test_empty_gold_is_deterministically_not_ready(self):
        report = evaluate(ROOT, [], [], parser=self._parser)
        self.assertEqual(report["status"], "not_ready")
        self.assertFalse(report["publication_ready"])

    def test_development_strata_cannot_mask_single_stratum_heldout(self):
        release, _bundle, _digest, gold, _inputs = self._fixture(); rows = []; inputs = []
        for index in range(200):
            profile = {"claim": "owned", "nonce": index}; listing = {"offer_kind": "seller_listing"}
            row = dict(gold[0]); row["gold_id"] = f"parser_gold_{index + 1:04d}"; row["input_sha256"] = input_sha256(profile, listing); row["split"] = "development" if index < 100 else "heldout"
            row["strata"] = self._strata(index) if index < 100 else self._strata(0)
            rows.append(row); inputs.append({"profile": profile, "listing": listing})
        self._write_manifest(release, rows)
        report = evaluate(release, rows, inputs, parser=self._parser)
        self.assertEqual(report["status"], "threshold_not_met")
        self.assertFalse(report["publication_ready"])


if __name__ == "__main__": unittest.main()
