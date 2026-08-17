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
    COMMITMENT_NAMESPACE, REQUIRED_STRATA, _fingerprint, build_queue, canonical_bytes, digest,
    validate_manifest, verify_decision_commitments,
)


class ParserReviewOnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="parser-review-")); self.addCleanup(shutil.rmtree, self.temp, True)
        self.release = self.temp / "release"; self.release.mkdir()
        self.external = self.temp / "restricted"; self.external.mkdir()

    @staticmethod
    def _strata(index: int) -> dict[str, str]:
        return {key: f"{key}_{index % 2}" for key in REQUIRED_STRATA}

    def _source(self) -> tuple[Path, str]:
        source = self.external / "source.jsonl"
        source.write_bytes(b"".join(canonical_bytes({"profile": {"claim": "owned", "nonce": index}, "listing": {"kind": "seller"}, "strata": self._strata(index)}) for index in range(201)))
        return source, digest(source.read_bytes())

    def test_fixed_queue_is_anonymous_and_packets_stay_external(self):
        # The release validator loads schemas independently of Python imports.
        schema = json.loads((ROOT / "schemas/review/parser-review-queue.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], "review/parser-review-queue.schema.json")
        source, source_sha = self._source(); manifest_path = self.release / "manifest.json"
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
            build_queue(self.release, source, source_sha, self.release / "inside.json", self.release / "forbidden-packets")

    def test_independent_commitments_require_only_disagreement_adjudication(self):
        source, source_sha = self._source(); manifest = build_queue(self.release, source, source_sha, self.release / "manifest.json", self.external / "packets")
        def decisions(role: str, change: bool = False, key_name: str | None = None) -> Path:
            rows = []
            for index, queued in enumerate(manifest["queue"]):
                row = {"decision_id": f"{role}_{index}", "queue_id": queued["queue_id"], "input_sha256": queued["input_sha256"], "reviewer": role, "expected_canonical_item_ids": ["item_fixture"], "expected_polarity": "owned"}
                if change and index == 0: row["expected_polarity"] = "unknown"
                row["decision_commitment_sha256"] = digest(canonical_bytes(row))
                rows.append(row)
            path = self.external / f"{role}.jsonl"; path.write_bytes(b"".join(canonical_bytes(row) for row in rows))
            private = self.external / str(key_name or role); subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
            public = private.with_suffix(".pub").read_text(encoding="utf-8").strip(); fingerprint = _fingerprint(public)
            commitment = {"schema_version": "1.0-p3.4", "reviewer": role, "decision_ledger_sha256": digest(path.read_bytes()), "public_key": public, "fingerprint": fingerprint, "signature_file": path.name + ".sig"}
            payload = self.external / f"{role}.payload"; payload.write_bytes(canonical_bytes({key: value for key, value in commitment.items() if key != "signature_file"}))
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", COMMITMENT_NAMESPACE, str(payload)], check=True, capture_output=True)
            shutil.copyfile(payload.with_name(payload.name + ".sig"), self.external / commitment["signature_file"])
            path.with_suffix(path.suffix + ".commitment.json").write_bytes(canonical_bytes(commitment)); return path
        a, b = decisions("annotator_a"), decisions("annotator_b", True)
        with self.assertRaises(ValueError): verify_decision_commitments(manifest, a, b, None, self.release)
        first_a, first_b = [json.loads(path.read_text(encoding="utf-8").splitlines()[0]) for path in (a, b)]
        adj = self.external / "adj.jsonl"; adj.write_bytes(canonical_bytes({"adjudication_id": "adj_1", "queue_id": first_a["queue_id"], "annotator_a_commitment_sha256": first_a["decision_commitment_sha256"], "annotator_b_commitment_sha256": first_b["decision_commitment_sha256"], "adjudicator_commitment_sha256": "A" * 64}))
        report = verify_decision_commitments(manifest, a, b, adj, self.release)
        self.assertEqual(report["disagreement_count"], 1)
        self.assertFalse(report["formal_gold_written"])

    def test_import_rejects_weakened_manifest(self):
        source, source_sha = self._source(); manifest = build_queue(self.release, source, source_sha, self.release / "manifest.json", self.external / "packets")
        weakened = dict(manifest); weakened["required_strata"] = []; weakened["manifest_sha256"] = digest(canonical_bytes({key: value for key, value in weakened.items() if key != "manifest_sha256"}))
        self.assertTrue(validate_manifest(weakened))
        weakened = dict(manifest); weakened["queue"] = weakened["queue"][:1]; weakened["queue_size"] = 1; weakened["split_counts"] = {"development": 1, "heldout": 0}; weakened["manifest_sha256"] = digest(canonical_bytes({key: value for key, value in weakened.items() if key != "manifest_sha256"}))
        self.assertTrue(validate_manifest(weakened))


if __name__ == "__main__": unittest.main()
