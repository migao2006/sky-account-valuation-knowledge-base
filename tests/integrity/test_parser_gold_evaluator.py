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
    attestation_payload, audit_gold, canonical_bytes, evaluate, gold_ledger_sha256, input_sha256,
    manifest_payload, parser_config_sha256, parser_source_sha256, sha256_bytes,
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
        return release, bundle, sha256_bytes(bundle.read_bytes()), gold, [{"profile": profile, "listing": listing}]

    @staticmethod
    def _parser(profile: dict[str, object], _listing: dict[str, object], _root: Path) -> dict[str, object]:
        state = str(profile["claim"])
        return {"item_states": [{"item_id": "item_test", "state": state}]}

    def test_valid_external_root_and_replay_are_accepted(self):
        release, bundle, digest, gold, inputs = self._fixture()
        self.assertEqual(audit_gold(release, gold, bundle, digest), [])
        report = evaluate(release, gold, inputs, parser=self._parser)
        self.assertEqual(report["status"], "threshold_not_met")
        self.assertEqual(report["heldout"]["precision"], 1.0)
        self.assertEqual(report["heldout"]["collision_rows"], 0)

    def test_tamper_and_no_external_root_fail_closed(self):
        release, bundle, digest, gold, _inputs = self._fixture()
        self.assertTrue(audit_gold(release, gold))
        gold[0]["expected_polarity"] = "confirmed_missing"
        self.assertTrue(audit_gold(release, gold, bundle, digest))

    def test_tampered_or_empty_rule_manifest_is_rejected(self):
        release, bundle, digest, gold, _inputs = self._fixture()
        (release / RULE_MANIFEST_REL).write_text("{}", encoding="utf-8")
        self.assertTrue(audit_gold(release, gold, bundle, digest))

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
