"""External-only, OpenSSH replay tests for the first market finalizer."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, timedelta
from pathlib import Path

from tools.market_authorization import NAMESPACE, _fingerprint, attestation_payload, canonical_bytes, sha256_bytes, verify_authorized_market_intake
from tools.market_intake.finalization import FinalizationError, finalize, finalize_append_v2
from tools.market_intake.onboarding import build, sha256
from tests.market_intake.test_onboarding import REPO_ROOT, record


class MarketFinalizationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.external = Path(self.temp.name) / "external"; self.external.mkdir()
        self.release = Path(self.temp.name) / "release"
        self.serial = 0
        self.v2_authorities = []
        # The verifier intentionally needs the exact current catalog contract.
        # Copy only mutable/read release artefacts, excluding git state.
        for name in ("data", "knowledge", "schemas"):
            shutil.copytree(REPO_ROOT / name, self.release / name)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, path: Path, value: object) -> str:
        path.write_bytes(canonical_bytes(value)); return sha256(path.read_bytes())

    def _candidate(self, tag: str = "fixture") -> Path:
        snapshot = self.external / f"source-{tag}.bin"; snapshot.write_bytes(f"licensed-source-{tag}".encode())
        number = {"fixture": 1, "first": 1, "second": 2, "third": 3}.get(tag, 9)
        value = record(number); value.update({"source_snapshot_path": str(snapshot), "source_snapshot_sha256": sha256(snapshot.read_bytes())})
        staging = self.external / f"staging-{tag}.json"
        stage = {"schema_version": "authorized-market-staging-v1", "dataset_id": f"authorized_market_finalizer_{tag}", "authorization_record_id": f"authorization_record_finalizer_{tag}", "expires_at": (date.today() + timedelta(days=30)).isoformat(), "records": [value]}
        digest = self._write(staging, stage); output = self.external / f"candidate-{tag}"
        build(self.release, staging, digest, output, "v2")
        return output

    def _signed_inputs(self, candidate: Path, *, bad_signature: bool = False) -> tuple[Path, str, Path, str, Path, str]:
        self.serial += 1
        manifest, candidate_registry = (json.loads((candidate / "manifest.json").read_text()), json.loads((candidate / "registry-candidate.json").read_text()))
        registry = {key: candidate_registry[key] for key in ("dataset_id", "authorization_record_id", "manifest_path", "manifest_sha256", "expires_at")}
        statement = {"schema_version": "authorized-market-statement-v1", "dataset_id": registry["dataset_id"], "manifest_sha256": registry["manifest_sha256"], "observations_sha256": manifest["observations_sha256"], "expires_at": registry["expires_at"]}
        statement_path = self.external / "statement.json"; statement_sha = self._write(statement_path, statement); registry["statement_sha256"] = statement_sha
        authorities = []; keys = []
        for number, role in enumerate(("data_steward", "privacy_reviewer", "method_reviewer"), 1):
            private = self.external / f"key{self.serial}-{number}"; subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
            public = (private.with_suffix(".pub")).read_text().strip(); fingerprint = _fingerprint(public)
            authorities.append({"authority_id": f"authority_finalizer_{number}", "public_key": public, "fingerprint": fingerprint, "roles": [role]}); keys.append((private, role, authorities[-1]))
        bundle_path = self.external / "authority.json"; bundle_sha = self._write(bundle_path, {"schema_version": "authorized-market-authority-bundle-v1", "authorities": authorities, "revoked_fingerprints": []})
        receipts = []
        for number, (private, role, authority) in enumerate(keys, 1):
            name = f"finalizer-{number}.sig"
            entry = {"attestation_id": f"authorized_market_attestation_{number:04d}", "dataset_id": registry["dataset_id"], "role": role, "authority_id": authority["authority_id"], "fingerprint": authority["fingerprint"], "statement_sha256": statement_sha, "manifest_sha256": registry["manifest_sha256"], "observations_sha256": manifest["observations_sha256"], "payload_sha256": "", "signature_file": f"data/review/market-authorization/signatures/{name}"}
            entry["payload_sha256"] = sha256_bytes(attestation_payload(registry, manifest, statement, entry))
            payload = self.external / f"payload-{number}"; payload.write_bytes(attestation_payload(registry, manifest, statement, entry))
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", NAMESPACE, str(payload)], check=True, capture_output=True)
            signature = payload.with_suffix(payload.suffix + ".sig"); target = self.external / name; signature.replace(target)
            if bad_signature and number == 1: target.write_bytes(b"tampered")
            receipts.append({"attestation": entry, "attestation_sha256": sha256(canonical_bytes(entry)), "signature_path": str(target), "signature_sha256": sha256(target.read_bytes())})
        handoff = {"schema_version": "authorized-market-finalization-handoff-v1", "candidate": {"dataset_id": registry["dataset_id"], "authorization_record_id": registry["authorization_record_id"], "manifest_sha256": registry["manifest_sha256"], "observations_sha256": manifest["observations_sha256"], "training_examples_sha256": manifest["training_examples_sha256"], "registry_candidate_sha256": sha256((candidate / "registry-candidate.json").read_bytes())}, "authority_bundle_sha256": bundle_sha, "statement_sha256": statement_sha, "attestations": receipts}
        handoff_path = self.external / "handoff.json"; handoff_sha = self._write(handoff_path, handoff)
        return bundle_path, bundle_sha, statement_path, statement_sha, handoff_path, handoff_sha

    def _finalize(self, candidate: Path, inputs: tuple[Path, str, Path, str, Path, str]):
        bundle, bundle_sha, statement, statement_sha, handoff, handoff_sha = inputs
        return finalize(self.release, candidate, sha256((candidate / "manifest.json").read_bytes()), bundle, bundle_sha, statement, statement_sha, handoff, handoff_sha)

    def _signed_inputs_v2(self, candidate: Path, coverage: list[Path]) -> tuple[Path, str, Path, str, Path, str]:
        """Create only externally held v2 transport/signature artefacts."""
        self.serial += 1
        manifest = json.loads((candidate / "manifest.json").read_text())
        registry_candidate = json.loads((candidate / "registry-candidate.json").read_text())
        registry = {key: registry_candidate[key] for key in ("dataset_id", "authorization_record_id", "manifest_path", "manifest_sha256", "expires_at")}
        claims = []
        candidate_claim = None
        for directory in coverage:
            m = json.loads((directory / "manifest.json").read_text()); r = json.loads((directory / "registry-candidate.json").read_text())
            claim = {"schema_version": "authorized-market-statement-v1", "dataset_id": r["dataset_id"], "manifest_sha256": r["manifest_sha256"], "observations_sha256": m["observations_sha256"], "expires_at": r["expires_at"]}
            claims.append(claim)
            if claim["dataset_id"] == registry["dataset_id"]: candidate_claim = claim
        assert candidate_claim is not None
        candidate_claim_sha = sha256(canonical_bytes(candidate_claim)); registry["statement_sha256"] = candidate_claim_sha
        authorities = []; keys = []
        for number, role in enumerate(("data_steward", "privacy_reviewer", "method_reviewer"), 1):
            private = self.external / f"v2-key{self.serial}-{number}"; subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
            public = private.with_suffix(".pub").read_text().strip(); authority = {"authority_id": f"authority_append_{self.serial}_{number}", "public_key": public, "fingerprint": _fingerprint(public), "roles": [role]}
            authorities.append(authority); keys.append((private, role, authority))
        self.v2_authorities.extend(authorities)
        bundle_path = self.external / f"authority-v2-{self.serial}.json"; bundle_sha = self._write(bundle_path, {"schema_version": "authorized-market-authority-bundle-v1", "authorities": self.v2_authorities, "revoked_fingerprints": []})
        receipts = []
        for number, (private, role, authority) in enumerate(keys, 1):
            name = f"append-{self.serial}-{number}.sig"
            entry = {"attestation_id": f"authorized_market_attestation_{self.serial * 10 + number:04d}", "dataset_id": registry["dataset_id"], "role": role, "authority_id": authority["authority_id"], "fingerprint": authority["fingerprint"], "statement_sha256": candidate_claim_sha, "manifest_sha256": registry["manifest_sha256"], "observations_sha256": manifest["observations_sha256"], "payload_sha256": "", "signature_file": f"data/review/market-authorization/signatures/{name}"}
            entry["payload_sha256"] = sha256_bytes(attestation_payload(registry, manifest, candidate_claim, entry))
            payload = self.external / f"append-payload-{self.serial}-{number}"; payload.write_bytes(attestation_payload(registry, manifest, candidate_claim, entry))
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", NAMESPACE, str(payload)], check=True, capture_output=True)
            signature = payload.with_suffix(payload.suffix + ".sig"); target = self.external / name; signature.replace(target)
            receipts.append({"attestation": entry, "attestation_sha256": sha256(canonical_bytes(entry)), "signature_path": str(target), "signature_sha256": sha256(target.read_bytes())})
        statement_path = self.external / f"statement-v2-{self.serial}.json"; statement_sha = self._write(statement_path, {"schema_version": "authorized-market-statement-bundle-v2", "statements": claims})
        handoff = {"schema_version": "authorized-market-finalization-handoff-v2", "candidate": {"dataset_id": registry["dataset_id"], "authorization_record_id": registry["authorization_record_id"], "manifest_sha256": registry["manifest_sha256"], "observations_sha256": manifest["observations_sha256"], "training_examples_sha256": manifest["training_examples_sha256"], "registry_candidate_sha256": sha256((candidate / "registry-candidate.json").read_bytes())}, "authority_bundle_sha256": bundle_sha, "statement_bundle_sha256": statement_sha, "attestations": receipts}
        handoff_path = self.external / f"handoff-v2-{self.serial}.json"; handoff_sha = self._write(handoff_path, handoff)
        return bundle_path, bundle_sha, statement_path, statement_sha, handoff_path, handoff_sha

    def _append_v2(self, candidate: Path, inputs: tuple[Path, str, Path, str, Path, str]):
        bundle, bundle_sha, statement, statement_sha, handoff, handoff_sha = inputs
        return finalize_append_v2(self.release, candidate, sha256((candidate / "manifest.json").read_bytes()), bundle, bundle_sha, statement, statement_sha, handoff, handoff_sha)

    def test_happy_path_imports_fixed_paths_and_replays(self):
        candidate = self._candidate(); inputs = self._signed_inputs(candidate)
        result = self._finalize(candidate, inputs)
        self.assertEqual("authorized_market_finalizer_fixture", result["dataset_id"])
        self.assertEqual([], verify_authorized_market_intake(self.release, inputs[0], inputs[1], inputs[2], inputs[3]))
        self.assertTrue((self.release / "data/review/market-authorization/datasets/authorized_market_finalizer_fixture/manifest.json").is_file())
        self.assertEqual(3, len((self.release / "data/review/market-authorization/attestations.jsonl").read_text().splitlines()))

    def test_tampered_signature_rolls_back_all_formal_rows(self):
        candidate = self._candidate(); inputs = self._signed_inputs(candidate, bad_signature=True)
        with self.assertRaisesRegex(FinalizationError, "formal authorization replay failed"):
            self._finalize(candidate, inputs)
        self.assertFalse((self.release / "data/review/market-authorization/datasets/authorized_market_finalizer_fixture").exists())
        self.assertFalse((self.release / "data/review/market-authorization/registry.jsonl").read_text().strip())
        self.assertFalse((self.release / "data/review/market-authorization/attestations.jsonl").read_text().strip())

    def test_interrupt_rolls_back_and_install_race_never_overwrites(self):
        candidate = self._candidate(); inputs = self._signed_inputs(candidate)
        with patch("tools.market_intake.finalization.verify_authorized_market_intake", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self._finalize(candidate, inputs)
        self.assertFalse((self.release / "data/review/market-authorization/datasets/authorized_market_finalizer_fixture").exists())
        self.assertFalse((self.release / "data/review/market-authorization/registry.jsonl").read_text().strip())
        inputs = self._signed_inputs(candidate)
        import os
        original_rename = os.rename
        sentinel = self.release / "data/review/market-authorization/signatures/finalizer-1.sig"
        def race(source, target):
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_bytes(b"do-not-overwrite")
            return original_rename(source, target)
        with patch("tools.market_intake.finalization.os.rename", side_effect=race):
            with self.assertRaises(FileExistsError):
                self._finalize(candidate, inputs)
        self.assertEqual(b"do-not-overwrite", sentinel.read_bytes())
        self.assertFalse((self.release / "data/review/market-authorization/datasets/authorized_market_finalizer_fixture").exists())

    def test_partial_signature_copy_and_extra_attestation_field_fail_closed(self):
        candidate = self._candidate(); inputs = self._signed_inputs(candidate)
        def partial_copy(_source, target):
            target.write(b"partial")
            raise OSError("simulated interrupted copy")
        with patch("tools.market_intake.finalization.shutil.copyfileobj", side_effect=partial_copy):
            with self.assertRaisesRegex(OSError, "interrupted copy"):
                self._finalize(candidate, inputs)
        self.assertFalse((self.release / "data/review/market-authorization/signatures/finalizer-1.sig").exists())
        self.assertFalse((self.release / "data/review/market-authorization/datasets/authorized_market_finalizer_fixture").exists())
        inputs = list(self._signed_inputs(candidate))
        handoff = json.loads(inputs[4].read_text())
        handoff["attestations"][0]["attestation"]["reviewer_email"] = "private@example.com"
        handoff["attestations"][0]["attestation_sha256"] = sha256(canonical_bytes(handoff["attestations"][0]["attestation"]))
        inputs[5] = self._write(inputs[4], handoff)
        with self.assertRaisesRegex(FinalizationError, "formal schema"):
            self._finalize(candidate, tuple(inputs))

    def test_signed_manifest_with_schema_extra_is_never_imported(self):
        candidate = self._candidate()
        manifest = json.loads((candidate / "manifest.json").read_text())
        manifest["unexpected_signed_field"] = "must-not-enter-release"
        (candidate / "manifest.json").write_bytes(canonical_bytes(manifest))
        registry = json.loads((candidate / "registry-candidate.json").read_text())
        registry["manifest_sha256"] = sha256((candidate / "manifest.json").read_bytes())
        (candidate / "registry-candidate.json").write_bytes(canonical_bytes(registry))
        inputs = self._signed_inputs(candidate)
        with self.assertRaisesRegex(FinalizationError, "candidate manifest does not satisfy"):
            self._finalize(candidate, inputs)
        self.assertFalse((self.release / "data/review/market-authorization/datasets/authorized_market_finalizer_fixture").exists())

    def test_handoff_tamper_path_traversal_and_existing_registry_fail_closed(self):
        candidate = self._candidate(); inputs = list(self._signed_inputs(candidate))
        handoff = json.loads(inputs[4].read_text()); handoff["candidate"]["observations_sha256"] = "A" * 64
        inputs[5] = self._write(inputs[4], handoff)
        with self.assertRaisesRegex(FinalizationError, "handoff does not bind"):
            self._finalize(candidate, tuple(inputs))
        inputs = self._signed_inputs(candidate); handoff = json.loads(inputs[4].read_text()); handoff["attestations"][0]["attestation"]["signature_file"] = "data/review/market-authorization/signatures/../escape.sig"; handoff["attestations"][0]["attestation_sha256"] = sha256(canonical_bytes(handoff["attestations"][0]["attestation"])); inputs = list(inputs); inputs[5] = self._write(inputs[4], handoff)
        with self.assertRaisesRegex(FinalizationError, "attestation metadata"):
            self._finalize(candidate, tuple(inputs))
        (self.release / "data/review/market-authorization/registry.jsonl").write_text('{"existing":true}\n', encoding="utf-8")
        with self.assertRaisesRegex(FinalizationError, "empty formal registry"):
            self._finalize(candidate, self._signed_inputs(candidate))

    def test_v2_append_exact_coverage_and_collision_rollback(self):
        first, second = self._candidate("first"), self._candidate("second")
        first_inputs = self._signed_inputs_v2(first, [first])
        self.assertEqual("v2", self._append_v2(first, first_inputs)["append_protocol"])
        second_inputs = self._signed_inputs_v2(second, [first, second])
        self.assertEqual("authorized_market_finalizer_second", self._append_v2(second, second_inputs)["dataset_id"])
        self.assertEqual([], verify_authorized_market_intake(self.release, *second_inputs[:4]))
        self.assertEqual(2, len((self.release / "data/review/market-authorization/registry.jsonl").read_text().splitlines()))
        # A transport bundle omitting historic data cannot append anything.
        third = self._candidate("third"); bad_inputs = self._signed_inputs_v2(third, [third])
        with self.assertRaisesRegex(FinalizationError, "exactly cover"):
            self._append_v2(third, bad_inputs)
        self.assertFalse((self.release / "data/review/market-authorization/datasets/authorized_market_finalizer_third").exists())
        # Authorization records are ledger-global identifiers, even when the
        # dataset ID itself is new.
        registry_candidate = json.loads((third / "registry-candidate.json").read_text())
        registry_candidate["authorization_record_id"] = "authorization_record_finalizer_first"
        (third / "registry-candidate.json").write_bytes(canonical_bytes(registry_candidate))
        collision_inputs = self._signed_inputs_v2(third, [first, second, third])
        with self.assertRaisesRegex(FinalizationError, "collide"):
            self._append_v2(third, collision_inputs)

    def test_v2_interrupt_rolls_back_only_owned_bytes(self):
        first, second = self._candidate("first"), self._candidate("second")
        self._append_v2(first, self._signed_inputs_v2(first, [first]))
        inputs = self._signed_inputs_v2(second, [first, second])
        with patch("tools.market_intake.finalization.verify_authorized_market_intake", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self._append_v2(second, inputs)
        self.assertFalse((self.release / "data/review/market-authorization/datasets/authorized_market_finalizer_second").exists())
        # A path injected after our preflight is never opened with overwrite,
        # and remains present after transaction rollback.
        inputs = self._signed_inputs_v2(second, [first, second])
        sentinel = self.release / "data/review/market-authorization/signatures/append-3-1.sig"
        import os
        original_rename = os.rename
        def race(source, target):
            sentinel.parent.mkdir(parents=True, exist_ok=True); sentinel.write_bytes(b"foreign-sentinel")
            return original_rename(source, target)
        with patch("tools.market_intake.finalization.os.rename", side_effect=race):
            with self.assertRaises(FileExistsError): self._append_v2(second, inputs)
        self.assertEqual(b"foreign-sentinel", sentinel.read_bytes())

    def test_v2_candidate_change_before_install_leaves_no_orphan(self):
        first, second = self._candidate("first"), self._candidate("second")
        self._append_v2(first, self._signed_inputs_v2(first, [first]))
        inputs = self._signed_inputs_v2(second, [first, second])
        original_copy = shutil.copyfile
        changed = False
        def mutate_then_copy(source, target, *args, **kwargs):
            nonlocal changed
            source_path = Path(source)
            if not changed and source_path == second / "observations.jsonl":
                source_path.write_bytes(source_path.read_bytes() + b"{}\n"); changed = True
            return original_copy(source, target, *args, **kwargs)
        with patch("tools.market_intake.finalization.shutil.copyfile", side_effect=mutate_then_copy):
            with self.assertRaisesRegex(FinalizationError, "changed after preflight"):
                self._append_v2(second, inputs)
        self.assertFalse((self.release / "data/review/market-authorization/datasets/authorized_market_finalizer_second").exists())


if __name__ == "__main__":
    unittest.main()
