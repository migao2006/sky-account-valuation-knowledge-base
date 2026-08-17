"""Fail-closed coverage for the restricted declarative evidence shadow."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.normalize.apply_days_of_love_faq1374_core_four_cohort import build
from tools.validate.declarative_canonical_evidence import DeclarationError, ledger_bytes, replay
from tools.validate.canonical_evidence_registry import validate_registry
from tools.validate.schema_validator import OfflineSchemaValidator

ROOT = Path(__file__).resolve().parents[2]
DECLARATION = "data/review/shadow/days-of-love-faq1374-core-four.declaration.json"


class DeclarativeCanonicalEvidenceShadowTests(unittest.TestCase):
    def copied_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "repo"
        for relative in ("data", "knowledge", "schemas"):
            shutil.copytree(ROOT / relative, root / relative)
        return root

    @staticmethod
    def declaration(root: Path) -> tuple[Path, dict]:
        path = root / DECLARATION
        return path, json.loads(path.read_text(encoding="utf-8"))

    def mutate(self, root: Path, change) -> None:
        path, value = self.declaration(root)
        change(value)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    def test_days_of_love_shadow_is_semantic_and_byte_parity_with_existing_verifier(self):
        _targets, expected = build(ROOT)
        actual = replay(ROOT, DECLARATION)
        self.assertEqual(actual, expected)
        self.assertEqual(ledger_bytes(actual), ledger_bytes(expected))
        validator = OfflineSchemaValidator(ROOT / "schemas")
        self.assertFalse(validator.validate(json.loads((ROOT / DECLARATION).read_text(encoding="utf-8")), ROOT / "schemas/review/canonical-evidence-declaration.schema.json"))

    def test_path_hash_locator_source_target_tier_and_duplicate_fail_closed(self):
        cases = (
            ("path", lambda value: value["sources"]["official"].update(path="data/source/../research/tgc-faq-1374-days-of-love-core-four.json")),
            ("hash", lambda value: value["sources"]["official"].update(sha256="0" * 64)),
            ("locator", lambda value: value["rules"][0].update(claim_locator="/facts/missing")),
            ("source", lambda value: value["rules"][0].update(source_key="unregistered")),
            ("target", lambda value: value["rules"][0].update(target_id=17)),
            ("tier", lambda value: value["sources"]["official"].update(source_tier="untrusted")),
            ("duplicate", lambda value: value["rules"].append(dict(value["rules"][0]))),
        )
        for name, change in cases:
            with self.subTest(name=name):
                root = self.copied_root()
                self.mutate(root, change)
                with self.assertRaises(DeclarationError):
                    replay(root, DECLARATION)

    def test_exact_source_item_id_and_forbidden_execution_fields_fail_closed(self):
        root = self.copied_root()
        self.mutate(root, lambda value: value["rules"][0].update(source_item_id_exact="other_item"))
        with self.assertRaises(DeclarationError):
            replay(root, DECLARATION)
        root = self.copied_root()
        self.mutate(root, lambda value: value.update(regex=".*"))
        with self.assertRaises(DeclarationError):
            replay(root, DECLARATION)

    @staticmethod
    def rows(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def production_cohort(self, root: Path) -> dict:
        declaration_path, declaration = self.declaration(root)
        declaration["declaration_format"] = "canonical_evidence_declaration_v2"
        declaration["mode"] = "production"
        # A production declaration may only assert values on its selected
        # source object and values already present on the canonical target.
        declaration["sources"] = {"official": declaration["sources"]["official"]}
        declaration["rules"] = [rule for rule in declaration["rules"] if rule["source_key"] == "official" and rule["field_path"] in {"canonical_name_en", "original_currency", "original_cost"}]
        target = root / "data/review/canonical-evidence-declarations/temporary.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(declaration, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        digest = hashlib.sha256(target.read_bytes()).hexdigest().upper()
        ledger_path = root / "data/review/temporary-production-canonical-evidence.jsonl"
        ledger_path.write_bytes(ledger_bytes(replay(root, target.relative_to(root))))
        approvals = []; authorities = []
        bundle = root.parent / "external-canonical-review-authority.json"
        for reviewer in ("reviewer_alice", "reviewer_bob"):
            reviewed_at = "2026-08-17"
            key = root.parent / reviewer
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
            public_key = " ".join(key.with_suffix(".pub").read_text(encoding="utf-8").split()[:2])
            fingerprint = subprocess.run(["ssh-keygen", "-lf", str(key.with_suffix(".pub")), "-E", "sha256"], capture_output=True, text=True, check=True).stdout.split()[1]
            authorities.append({"authority_id": reviewer, "fingerprint": fingerprint, "public_key": public_key, "roles": ["canonical_evidence_reviewer"]})
            payload = f"canonical_evidence_review_v1\0{declaration['cohort_id']}\0{digest}\0{reviewer}\0{reviewed_at}".encode("utf-8")
            payload_path = root.parent / f"{reviewer}.payload"; payload_path.write_bytes(payload)
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "sky-canonical-evidence-review-v1", str(payload_path)], check=True, capture_output=True)
            approvals.append({"authority_id": reviewer, "fingerprint": fingerprint, "reviewed_at": reviewed_at, "payload_sha256": hashlib.sha256(payload).hexdigest().upper(), "signature": __import__("base64").b64encode(payload_path.with_suffix(".payload.sig").read_bytes()).decode("ascii")})
        bundle.write_text(json.dumps({"schema_version": "canonical-evidence-review-authority-bundle-v1", "authorities": authorities}), encoding="utf-8")
        review_path = root / "data/review/canonical-evidence-reviews/temporary.json"
        review_path.parent.mkdir(parents=True)
        review_path.write_text(json.dumps({"review_format": "canonical_evidence_review_v1", "cohort_id": declaration["cohort_id"], "declaration_sha256": digest, "review_status": "approved", "release_required": True, "approvals": approvals}, indent=2) + "\n", encoding="utf-8", newline="\n")
        targets = sorted({rule["target_id"] for rule in declaration["rules"]})
        return {"cohort_id": declaration["cohort_id"], "evidence_path": "data/review/temporary-production-canonical-evidence.jsonl", "verifier_id": "declarative_v2", "snapshot_paths": sorted(source["path"] for source in declaration["sources"].values()), "source_ids": sorted(source["source_id"] for source in declaration["sources"].values()), "target_item_ids": targets, "target_set_ids": [], "release_required": True, "review_status": "approved", "declaration_path": "data/review/canonical-evidence-declarations/temporary.json", "declaration_sha256": digest, "review_metadata_path": "data/review/canonical-evidence-reviews/temporary.json", "_bundle": bundle}

    def production_problems(self, root: Path, cohort: dict) -> list[str]:
        bundle = cohort.pop("_bundle", None)
        (root / "data/review/canonical-evidence-cohorts.jsonl").write_text(json.dumps(cohort, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
        items = {row["item_id"]: row for row in self.rows(root / "knowledge/items/items.jsonl")}
        sets = {row["set_id"]: row for row in self.rows(root / "knowledge/sets/item-sets.jsonl")}
        sources = {row["source_id"]: row for row in self.rows(root / "knowledge/sources/sources.jsonl")}
        return validate_registry(root, items, sets, sources, bundle, hashlib.sha256(Path(bundle).read_bytes()).hexdigest().upper() if bundle else None)[0]

    def production_result(self, root: Path, cohort: dict):
        bundle = cohort.pop("_bundle", None)
        (root / "data/review/canonical-evidence-cohorts.jsonl").write_text(json.dumps(cohort, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
        items = {row["item_id"]: row for row in self.rows(root / "knowledge/items/items.jsonl")}
        sets = {row["set_id"]: row for row in self.rows(root / "knowledge/sets/item-sets.jsonl")}
        sources = {row["source_id"]: row for row in self.rows(root / "knowledge/sources/sources.jsonl")}
        return validate_registry(root, items, sets, sources, bundle, hashlib.sha256(Path(bundle).read_bytes()).hexdigest().upper() if bundle else None)

    def test_production_declaration_is_replayable_only_with_dual_approval(self):
        root = self.copied_root()
        cohort = self.production_cohort(root)
        problems, active = self.production_result(root, cohort)
        self.assertEqual(problems, [])
        self.assertEqual(list(active), [cohort["cohort_id"]])
        self.assertEqual(len(active[cohort["cohort_id"]]), len(replay(root, cohort["declaration_path"])))
        validator = OfflineSchemaValidator(root / "schemas")
        self.assertFalse(validator.validate(cohort, root / "schemas/review/canonical-evidence-cohort.schema.json"))

    def test_production_rejects_shadow_tamper_traversal_pointer_transform_and_duplicate_reviewer(self):
        cases = (
            ("shadow", lambda root, cohort: json.loads((root / cohort["declaration_path"]).read_text(encoding="utf-8"))),
            ("digest", lambda root, cohort: cohort.update(declaration_sha256="0" * 64)),
            ("path", lambda root, cohort: cohort.update(declaration_path="data/review/canonical-evidence-declarations/../shadow/days-of-love-faq1374-core-four.declaration.json")),
            ("pointer", lambda root, cohort: self._mutate_production(root, cohort, lambda value: value["rules"][0].update(claim_locator="/missing"))),
            ("transform", lambda root, cohort: self._mutate_production(root, cohort, lambda value: value["rules"][0].update(transform="code"))),
            ("reviewer", lambda root, cohort: self._duplicate_reviewer(root, cohort)),
        )
        for name, change in cases:
            with self.subTest(name=name):
                root = self.copied_root(); cohort = self.production_cohort(root)
                if name == "shadow":
                    declaration = change(root, cohort); declaration["declaration_format"] = "canonical_evidence_declaration_v1"; declaration["mode"] = "shadow_only"; declaration["reviewed_at"] = "2026-08-17"
                    path = root / cohort["declaration_path"]; path.write_text(json.dumps(declaration), encoding="utf-8", newline="\n"); cohort["declaration_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest().upper()
                    review = json.loads((root / cohort["review_metadata_path"]).read_text(encoding="utf-8")); review["declaration_sha256"] = cohort["declaration_sha256"]; (root / cohort["review_metadata_path"]).write_text(json.dumps(review), encoding="utf-8", newline="\n")
                else: change(root, cohort)
                self.assertTrue(self.production_problems(root, cohort))

    def test_production_rejects_outside_item_and_canonical_availability_mismatch(self):
        root = self.copied_root(); cohort = self.production_cohort(root)
        path = root / cohort["declaration_path"]; declaration = json.loads(path.read_text(encoding="utf-8"))
        declaration["rules"][0]["claim_locator"] = "/facts/historical_window_start_date"
        path.write_text(json.dumps(declaration), encoding="utf-8", newline="\n")
        cohort["declaration_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        self.assertTrue(self.production_problems(root, cohort))
        root = self.copied_root(); cohort = self.production_cohort(root)
        path = root / cohort["declaration_path"]; declaration = json.loads(path.read_text(encoding="utf-8"))
        declaration["rules"][0]["field_path"] = "availability_status"
        path.write_text(json.dumps(declaration), encoding="utf-8", newline="\n")
        cohort["declaration_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        self.assertTrue(self.production_problems(root, cohort))

    def test_declarative_duplicate_path_digest_and_target_are_rejected(self):
        for field in ("declaration_path", "declaration_sha256", "target_item_ids"):
            with self.subTest(field=field):
                root = self.copied_root(); cohort = self.production_cohort(root)
                duplicate = dict(cohort); duplicate["cohort_id"] = "canonical_cohort_second_declarative"
                if field == "target_item_ids":
                    duplicate["declaration_path"] = "data/review/canonical-evidence-declarations/second.json"; duplicate["declaration_sha256"] = "F" * 64
                registry = dict(cohort); bundle = registry.pop("_bundle"); duplicate.pop("_bundle", None)
                (root / "data/review/canonical-evidence-cohorts.jsonl").write_text("\n".join(json.dumps(row, separators=(",", ":")) for row in (registry, duplicate)) + "\n", encoding="utf-8")
                items = {row["item_id"]: row for row in self.rows(root / "knowledge/items/items.jsonl")}; sets = {row["set_id"]: row for row in self.rows(root / "knowledge/sets/item-sets.jsonl")}; sources = {row["source_id"]: row for row in self.rows(root / "knowledge/sources/sources.jsonl")}
                self.assertTrue(validate_registry(root, items, sets, sources, bundle, hashlib.sha256(bundle.read_bytes()).hexdigest().upper())[0])

    def test_external_reviewer_bundle_rejects_same_key_wrong_fingerprint_and_inside_root(self):
        for case in ("same_key", "wrong_fingerprint", "inside_root"):
            with self.subTest(case=case):
                root = self.copied_root(); cohort = self.production_cohort(root); bundle = cohort["_bundle"]
                if case == "inside_root":
                    copied = root / "data/review/external-authority.json"; copied.write_bytes(bundle.read_bytes()); cohort["_bundle"] = copied
                else:
                    value = json.loads(bundle.read_text(encoding="utf-8"))
                    if case == "same_key":
                        value["authorities"][1]["public_key"] = value["authorities"][0]["public_key"]
                        value["authorities"][1]["fingerprint"] = value["authorities"][0]["fingerprint"]
                    else:
                        value["authorities"][0]["fingerprint"] = "SHA256:not-the-key"
                    bundle.write_text(json.dumps(value), encoding="utf-8")
                self.assertTrue(self.production_problems(root, cohort))

    @staticmethod
    def _mutate_production(root: Path, cohort: dict, change) -> None:
        path = root / cohort["declaration_path"]; value = json.loads(path.read_text(encoding="utf-8")); change(value); path.write_text(json.dumps(value), encoding="utf-8", newline="\n")

    @staticmethod
    def _duplicate_reviewer(root: Path, cohort: dict) -> None:
        path = root / cohort["review_metadata_path"]; value = json.loads(path.read_text(encoding="utf-8")); value["approvals"][1]["authority_id"] = value["approvals"][0]["authority_id"]; path.write_text(json.dumps(value), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    unittest.main()
