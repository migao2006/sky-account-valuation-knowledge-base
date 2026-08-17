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
    COMMITMENT_NAMESPACE, REQUIRED_STRATA, _fingerprint, _load_verified_restricted_packets, _quarantined_unissuable_blind_packet_implementation, build_queue, canonical_bytes, digest,
    build_blind_packages, build_conflict_packet, canonical_decision_receipt_payload, import_candidate_ledger, preflight_report,
    validate_manifest, verify_decision_commitments,
)


class ParserReviewOnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="parser-review-")); self.addCleanup(shutil.rmtree, self.temp, True)
        self.release = self.temp / "release"; self.release.mkdir()
        self.external = self.temp / "restricted"; self.external.mkdir()

    @staticmethod
    def _strata(index: int) -> dict[str, str]:
        return {key: f"bucket_{index % 2}" for key in REQUIRED_STRATA}

    def _source(self) -> tuple[Path, str]:
        source = self.external / "source.jsonl"
        source.write_bytes(b"".join(canonical_bytes({"profile": {"claim": "owned", "nonce": index}, "listing": {"kind": "seller"}, "strata": self._strata(index)}) for index in range(201)))
        return source, digest(source.read_bytes())

    def test_fixed_queue_is_anonymous_and_packets_stay_external(self):
        # The release validator loads schemas independently of Python imports.
        schema = json.loads((ROOT / "schemas/review/parser-review-queue.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], "review/parser-review-queue.schema.json")
        source, source_sha = self._source(); manifest_path = self.external / "review-queue-manifest.json"
        manifest = build_queue(self.release, source, source_sha, manifest_path, self.external / "packets")
        self.assertEqual(manifest["queue_size"], 200)
        self.assertEqual(manifest["split_counts"], {"development": 100, "heldout": 100})
        self.assertEqual(manifest, json.loads(manifest_path.read_text(encoding="utf-8")))
        self.assertTrue((self.external / "packets/parser-review-development-restricted.jsonl").is_file())
        encoded = manifest_path.read_text(encoding="utf-8")
        self.assertNotIn("nonce", encoded)
        self.assertNotIn("profile", encoded)
        self.assertEqual(validate_manifest(manifest), [])
        tampered = json.loads(json.dumps(manifest)); tampered["queue"][0]["split"] = "heldout"
        self.assertTrue(validate_manifest(tampered))
        with self.assertRaises(ValueError):
            build_queue(self.release, source, source_sha, self.release / "data/review/parser-gold/claims.jsonl", self.external / "other-packets")
        with self.assertRaises(ValueError):
            build_queue(self.release, source, source_sha, self.release / "inside.json", self.release / "forbidden-packets")
        leaked = self.external / "leaked.jsonl"; rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]; rows[0]["strata"]["era"] = "alice@example.com"; leaked.write_bytes(b"".join(canonical_bytes(row) for row in rows))
        with self.assertRaises(ValueError): build_queue(self.release, leaked, digest(leaked.read_bytes()), self.external / "leaked-manifest.json", self.external / "leaked-packets")

    def test_independent_commitments_require_only_disagreement_adjudication(self):
        source, source_sha = self._source(); manifest = build_queue(self.release, source, source_sha, self.external / "review-queue-manifest.json", self.external / "packets")
        def decisions(role: str, change: bool = False, key_name: str | None = None, payload_reviewer: str | None = None) -> Path:
            rows = []
            for index, queued in enumerate(manifest["queue"]):
                row = {"decision_id": f"{role}_{index}", "queue_id": queued["queue_id"], "input_sha256": queued["input_sha256"], "reviewer": payload_reviewer or role, "expected_canonical_item_ids": ["item_fixture"], "expected_polarity": "owned"}
                if change and index == 0: row["expected_polarity"] = "unknown"
                row["decision_commitment_sha256"] = digest(canonical_bytes(row))
                rows.append(row)
            path = self.external / f"{key_name or role}.jsonl"; path.write_bytes(b"".join(canonical_bytes(row) for row in rows))
            private = self.external / str(key_name or role); subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
            public = private.with_suffix(".pub").read_text(encoding="utf-8").strip(); fingerprint = _fingerprint(public)
            commitment = {"schema_version": "1.0-p3.5", "reviewer": role, "queue_manifest_sha256": manifest["manifest_sha256"], "decision_ledger_sha256": digest(path.read_bytes()), "public_key": public, "fingerprint": fingerprint, "signature_file": path.name + ".sig"}
            payload = self.external / f"{role}.payload"; payload.write_bytes(canonical_bytes({key: value for key, value in commitment.items() if key != "signature_file"}))
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", COMMITMENT_NAMESPACE, str(payload)], check=True, capture_output=True)
            shutil.copyfile(payload.with_name(payload.name + ".sig"), self.external / commitment["signature_file"])
            path.with_suffix(path.suffix + ".commitment.json").write_bytes(canonical_bytes(commitment)); return path
        a, b = decisions("annotator_a"), decisions("annotator_b", True)
        wrong_a = decisions("annotator_a", key_name="wrong_a", payload_reviewer="annotator_b")
        with self.assertRaises(ValueError): build_conflict_packet(manifest, wrong_a, b, self.external / "wrong-conflicts.json", self.release)
        with self.assertRaises(ValueError): verify_decision_commitments(manifest, a, b, None, self.release)
        first_a, first_b = [json.loads(path.read_text(encoding="utf-8").splitlines()[0]) for path in (a, b)]
        adj = self.external / "adj.jsonl"
        adjudication = {"adjudication_id": "adjudication_1", "queue_id": first_a["queue_id"], "input_sha256": first_a["input_sha256"], "annotator_a_commitment_sha256": first_a["decision_commitment_sha256"], "annotator_b_commitment_sha256": first_b["decision_commitment_sha256"], "final_canonical_item_ids": ["item_fixture"], "final_polarity": "owned"}
        adjudication["adjudicator_receipt_sha256"] = digest(canonical_bytes(adjudication)); adj.write_bytes(canonical_bytes(adjudication))
        private = self.external / "adjudicator"; subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
        public = private.with_suffix(".pub").read_text(encoding="utf-8").strip(); fingerprint = _fingerprint(public)
        commitment = {"schema_version": "1.0-p3.5", "reviewer": "adjudicator", "queue_manifest_sha256": manifest["manifest_sha256"], "adjudication_ledger_sha256": digest(adj.read_bytes()), "public_key": public, "fingerprint": fingerprint, "signature_file": adj.name + ".sig"}
        payload = self.external / "adjudicator.payload"; payload.write_bytes(canonical_bytes({key: value for key, value in commitment.items() if key != "signature_file"}))
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", COMMITMENT_NAMESPACE, str(payload)], check=True, capture_output=True)
        shutil.copyfile(payload.with_name(payload.name + ".sig"), self.external / commitment["signature_file"])
        adj.with_suffix(adj.suffix + ".commitment.json").write_bytes(canonical_bytes(commitment))
        report = verify_decision_commitments(manifest, a, b, adj, self.release)
        self.assertEqual(report["disagreement_count"], 1)
        self.assertFalse(report["formal_gold_written"])
        # Even a self-consistent changed split/freeze cannot reuse the signed labels.
        altered = json.loads(json.dumps(manifest)); development = next(row for row in altered["queue"] if row["split"] == "development"); heldout = next(row for row in altered["queue"] if row["split"] == "heldout" and row["strata"] == development["strata"])
        development["split"], heldout["split"] = "heldout", "development"
        altered["development_freeze_sha256"] = digest(canonical_bytes([row for row in altered["queue"] if row["split"] == "development"]))
        altered["manifest_sha256"] = digest(canonical_bytes({key: value for key, value in altered.items() if key != "manifest_sha256"}))
        self.assertEqual(validate_manifest(altered), [])
        with self.assertRaises(ValueError): verify_decision_commitments(altered, a, b, adj, self.release)
        sidecar = adj.with_suffix(adj.suffix + ".commitment.json"); signed = sidecar.read_bytes(); signature = (self.external / "adj.jsonl.sig").read_bytes(); sidecar.unlink()
        with self.assertRaises(ValueError): verify_decision_commitments(manifest, a, b, adj, self.release)
        sidecar.write_bytes(signed)
        # An adjudicator may not reuse either annotator's external signing key.
        reused_public = (self.external / "annotator_a.pub").read_text(encoding="utf-8").strip()
        reused = {"schema_version": "1.0-p3.5", "reviewer": "adjudicator", "queue_manifest_sha256": manifest["manifest_sha256"], "adjudication_ledger_sha256": digest(adj.read_bytes()), "public_key": reused_public, "fingerprint": _fingerprint(reused_public), "signature_file": adj.name + ".sig"}
        reused_payload = self.external / "reused.payload"; reused_payload.write_bytes(canonical_bytes({key: value for key, value in reused.items() if key != "signature_file"}))
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(self.external / "annotator_a"), "-n", COMMITMENT_NAMESPACE, str(reused_payload)], check=True, capture_output=True)
        shutil.copyfile(reused_payload.with_name(reused_payload.name + ".sig"), self.external / reused["signature_file"])
        sidecar.write_bytes(canonical_bytes(reused))
        with self.assertRaises(ValueError): verify_decision_commitments(manifest, a, b, adj, self.release)
        sidecar.write_bytes(signed); (self.external / "adj.jsonl.sig").write_bytes(signature)
        ledger = import_candidate_ledger(manifest, a, b, adj, self.external / "candidate-ledger.json", self.release)
        self.assertEqual(ledger["candidate_count"], 199)
        self.assertFalse(ledger["formal_gold_written"])

    def test_import_rejects_weakened_manifest(self):
        source, source_sha = self._source(); manifest = build_queue(self.release, source, source_sha, self.external / "review-queue-manifest.json", self.external / "packets")
        weakened = dict(manifest); weakened["required_strata"] = []; weakened["manifest_sha256"] = digest(canonical_bytes({key: value for key, value in weakened.items() if key != "manifest_sha256"}))
        self.assertTrue(validate_manifest(weakened))

    def test_blind_packages_fail_closed_when_public_manifest_is_linkable(self):
        source, source_sha = self._source()
        manifest = build_queue(self.release, source, source_sha, self.external / "review-queue-manifest.json", self.external / "packets")
        report = preflight_report(manifest, self.external / "packets", self.release)
        self.assertEqual(report["status"], "not_ready")
        with self.assertRaises(ValueError):
            build_blind_packages(manifest, self.external / "packets", self.external / "issued", "correct-horse-battery-staple", self.release)
        quarantined_output = self.external / "quarantined-issued"
        with self.assertRaises(ValueError):
            _quarantined_unissuable_blind_packet_implementation(manifest, self.external / "packets", quarantined_output, "correct-horse-battery-staple", self.release)
        self.assertFalse(quarantined_output.exists())
        with self.assertRaises(ValueError):
            import_candidate_ledger(manifest, self.external / "missing-a.jsonl", self.external / "missing-b.jsonl", None, self.release / "data/review/parser-gold/claims.jsonl", self.release)

    def test_blind_packet_replays_input_and_exact_frozen_split_and_strata(self):
        source, source_sha = self._source()
        manifest = build_queue(self.release, source, source_sha, self.external / "review-queue-manifest.json", self.external / "packets")
        packet = self.external / "packets/parser-review-development-restricted.jsonl"; original = packet.read_bytes()
        def forged(mutator):
            rows = [json.loads(line) for line in original.decode().splitlines()]; mutator(rows[0])
            content = b"".join(canonical_bytes(row) for row in rows); packet.write_bytes(content)
            altered = json.loads(json.dumps(manifest)); altered["restricted_packet_sha256"]["development"] = digest(content)
            altered["manifest_sha256"] = digest(canonical_bytes({key: value for key, value in altered.items() if key != "manifest_sha256"}))
            with self.assertRaises(ValueError): build_blind_packages(altered, self.external / "packets", self.external / "issued", "correct-horse-battery-staple", self.release)
            with self.assertRaises(ValueError): _load_verified_restricted_packets(altered, self.external / "packets", self.release)
            report = preflight_report(altered, self.external / "packets", self.release)
            self.assertEqual(report["status"], "not_ready")
            self.assertTrue(any("restricted packet verification failed" in error for error in report["errors"]))
            packet.write_bytes(original)
        forged(lambda row: row["profile"].update({"nonce": "tampered"}))
        forged(lambda row: row.update({"split": "heldout"}))
        forged(lambda row: row["strata"].update({"era": "wrong"}))
        weakened = dict(manifest); weakened["queue"] = weakened["queue"][:1]; weakened["queue_size"] = 1; weakened["split_counts"] = {"development": 1, "heldout": 0}; weakened["manifest_sha256"] = digest(canonical_bytes({key: value for key, value in weakened.items() if key != "manifest_sha256"}))
        self.assertTrue(validate_manifest(weakened))


if __name__ == "__main__": unittest.main()
