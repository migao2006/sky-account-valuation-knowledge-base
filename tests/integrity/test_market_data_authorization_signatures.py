import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from tools.market_authorization import (NAMESPACE, attestation_payload, canonical_bytes,
    _valid_iso_date, make_authorization_evaluator, model_training_authorization_reasons, sha256_bytes, verify_authorized_market_intake)
from tools.modeling.clean_prices import clean as clean_prices


class AuthorizedMarketIntakeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "release"
        (self.root / "data/review/market-authorization/signatures").mkdir(parents=True)
        (self.root / "data/review/market-authorization/datasets/authorized_market_fixture").mkdir(parents=True)
        self.external = self.base / "external"; self.external.mkdir()
        self._write_fixture()

    def tearDown(self): self.temp.cleanup()
    def _write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    def _sha(self, path): return sha256_bytes(path.read_bytes())
    def _write_fixture(self):
        dsid = "authorized_market_fixture"; ddir = self.root / "data/review/market-authorization/datasets" / dsid
        observation = {"observation_id":"observation_fixture_0001", "dedup_cluster_id":"cluster_fixture_0001", "post_date":"2026-08-01", "date_verified":True, "currency":"TWD", "currency_verified":True, "server":"international", "server_verified":True, "offer_kind":"seller_listing", "entity_kind":"single_account", "price_line":"asking", "price_twd":1000}
        op = ddir / "observations.jsonl"; op.write_bytes(canonical_bytes(observation))
        manifest = {"schema_version":"authorized-market-manifest-v1", "dataset_id":dsid,
            "observations_path":f"data/review/market-authorization/datasets/{dsid}/observations.jsonl", "observations_sha256":self._sha(op),
            "observation_digests":[{"observation_id":observation["observation_id"], "row_digest":sha256_bytes(canonical_bytes(observation)), "dedup_cluster_digest":sha256_bytes(canonical_bytes(observation["dedup_cluster_id"]))}]}
        mp=ddir/"manifest.json"; self._write(mp,manifest)
        statement={"schema_version":"authorized-market-statement-v1", "dataset_id":dsid, "manifest_sha256":self._sha(mp), "observations_sha256":self._sha(op), "expires_at":(date.today()+timedelta(days=30)).isoformat()}
        self.statement_path=self.external/"statement.json"; self._write(self.statement_path,statement)
        self.dataset={"dataset_id":dsid, "authorization_record_id":"authorization_record_fixture", "manifest_path":f"data/review/market-authorization/datasets/{dsid}/manifest.json", "manifest_sha256":self._sha(mp), "statement_sha256":self._sha(self.statement_path), "expires_at":statement["expires_at"]}
        (self.root/"data/review/market-authorization/registry.jsonl").write_bytes(canonical_bytes(self.dataset))
        authorities=[]; entries=[]
        for num,role in enumerate(("data_steward","privacy_reviewer","method_reviewer")):
            key=self.external/f"key{num}"; subprocess.run(["ssh-keygen","-q","-t","ed25519","-N","","-f",str(key)],check=True)
            public=(key.with_suffix(".pub")).read_text(encoding="utf-8").strip()
            fp=subprocess.run(["ssh-keygen","-lf",str(key.with_suffix(".pub"))],text=True,capture_output=True,check=True).stdout.split()[1]
            aid=f"authority_{role}"
            authorities.append({"authority_id":aid,"public_key":public,"fingerprint":fp,"roles":[role]})
            rel=f"data/review/market-authorization/signatures/{role}.sig"
            entry={"attestation_id":f"authorized_market_attestation_{num:04d}","dataset_id":dsid,"role":role,"authority_id":aid,"fingerprint":fp,"statement_sha256":self.dataset["statement_sha256"],"manifest_sha256":self._sha(mp),"observations_sha256":self._sha(op),"signature_file":rel}
            entry["payload_sha256"]=sha256_bytes(attestation_payload(self.dataset,manifest,statement,entry))
            payload=self.external/f"payload{num}"; payload.write_bytes(attestation_payload(self.dataset,manifest,statement,entry))
            subprocess.run(["ssh-keygen","-Y","sign","-q","-f",str(key),"-n",NAMESPACE,str(payload)],check=True)
            shutil.copyfile(str(payload)+".sig",self.root/rel)
            entries.append(entry)
        (self.root/"data/review/market-authorization/attestations.jsonl").write_bytes(b"".join(canonical_bytes(x) for x in entries))
        self.bundle_path=self.external/"bundle.json"; self._write(self.bundle_path,{"schema_version":"authorized-market-authority-bundle-v1","authorities":authorities,"revoked_fingerprints":[]})
    def args(self): return (self.bundle_path,self._sha(self.bundle_path),self.statement_path,self._sha(self.statement_path))
    def errors(self): return verify_authorized_market_intake(self.root,*self.args())
    def test_valid_temp_keys_fixture_and_callable_protocol(self):
        self.assertEqual([],self.errors())
        evaluator=make_authorization_evaluator(self.root,*self.args())
        manifest=json.loads((self.root/"data/review/market-authorization/datasets/authorized_market_fixture/manifest.json").read_text())
        row=json.loads((self.root/"data/review/market-authorization/datasets/authorized_market_fixture/observations.jsonl").read_text())
        allowed={"authorization_record_id":"authorization_record_fixture", "dataset_id":"authorized_market_fixture", "observation_id":row["observation_id"], "row_digest":sha256_bytes(canonical_bytes(row)), "manifest_sha256":manifest and self.dataset["manifest_sha256"]}
        allowed.update({
            "status":"authorized_model_training", "allowed_uses":["model_training","comparable_estimation"],
            "source_snapshot":{"artifact_path":self.dataset["manifest_path"],"sha256":self.dataset["manifest_sha256"],"captured_at":"2026-08-01","replayable":True},
            "license_evidence":{"kind":"explicit_data_license","evidence_id":"authorization_record_fixture","verified":True},
            "replay_evidence":[{"evidence_id":"observation_fixture_0001","source_locator":"/observation_fixture_0001","content_sha256":allowed["row_digest"],"reviewed_at":"2026-08-01"}],
        })
        comparable={
            "market_data_authorization":allowed, "selected_price_twd":row["price_twd"],
            "price_type":"asking", "post_date":row["post_date"], "date_verified":True,
            "currency":"TWD", "currency_verified":True, "server":"international",
            "server_verified":True, "offer_kind":"seller_listing", "entity_kind":"single_account",
        }
        self.assertTrue(evaluator(comparable))
        self.assertIn("market_data_feature_lineage_evaluator_required", model_training_authorization_reasons(comparable, evaluator))
        duplicate_rows=[]
        for number in (1,2):
            candidate=dict(comparable, history_id=f"history_authorized_{number}", account_id=f"account_authorized_{number}", observed_at="2026-08-01", base_account_type="unknown")
            duplicate_rows.append(candidate)
        normal, urgent, exclusions=clean_prices(duplicate_rows,evaluator)
        self.assertEqual(([],[]),(normal,urgent))
        self.assertEqual(2,len(exclusions))
        self.assertTrue(all("market_data_feature_lineage_evaluator_required" in row["reason_codes"] for row in exclusions))
        changed=dict(comparable, selected_price_twd=1001)
        self.assertFalse(evaluator(changed))
        allowed["observation_id"]="observation_missing"
        self.assertFalse(evaluator(comparable))
    def test_tamper_observations_fails(self):
        p=self.root/"data/review/market-authorization/datasets/authorized_market_fixture/observations.jsonl"
        p.write_text('{"observation_id":"observation_tampered","dedup_cluster_id":"cluster_fixture_0001"}\n',encoding="utf-8")
        self.assertTrue(any("digests" in x or "statement" in x for x in self.errors()))
    def test_self_filled_authorization_without_injected_trust_fails(self):
        self.assertTrue(any("must be injected" in x for x in verify_authorized_market_intake(self.root)))
    def test_repo_local_external_files_fail(self):
        local=self.root/"local-bundle.json"; shutil.copyfile(self.bundle_path,local)
        self.assertTrue(any("outside the release root" in x for x in verify_authorized_market_intake(self.root,local,self._sha(local),self.statement_path,self._sha(self.statement_path))))
    def test_wrong_role_fails(self):
        p=self.bundle_path; value=json.loads(p.read_text(encoding="utf-8")); value["authorities"][0]["roles"]=["method_reviewer"]; self._write(p,value)
        self.assertTrue(any("does not hold role" in x for x in self.errors()))
    def test_revoked_fingerprint_fails(self):
        value=json.loads(self.bundle_path.read_text(encoding="utf-8")); value["revoked_fingerprints"]=[value["authorities"][0]["fingerprint"]]; self._write(self.bundle_path,value)
        self.assertTrue(any("revoked" in x or "does not hold role" in x for x in self.errors()))
    def test_expiry_fails(self):
        value=json.loads(self.statement_path.read_text(encoding="utf-8")); value["expires_at"]=(date.today()-timedelta(days=1)).isoformat(); self._write(self.statement_path,value)
        # Statement mutation intentionally invalidates its recorded digest too.
        self.assertTrue(any("expired" in x or "does not bind" in x for x in self.errors()))
    def test_nested_pii_fails(self):
        p=self.root/"data/review/market-authorization/datasets/authorized_market_fixture/observations.jsonl"
        row=json.loads(p.read_text(encoding="utf-8")); row["metadata"]={"nested":{"email":"person@example.com"}}; p.write_bytes(canonical_bytes(row))
        self.assertTrue(any("PII" in x for x in self.errors()))

    def test_record_reused_for_unlisted_observation_fails_closed(self):
        evaluator=make_authorization_evaluator(self.root,*self.args())
        self.assertFalse(evaluator({"market_data_authorization":{"authorization_record_id":"authorization_record_fixture", "dataset_id":"authorized_market_fixture", "observation_id":"observation_unlisted", "row_digest":"A"*64, "manifest_sha256":self.dataset["manifest_sha256"]}}))

    def test_row_digest_change_fails_closed(self):
        evaluator=make_authorization_evaluator(self.root,*self.args())
        self.assertFalse(evaluator({"market_data_authorization":{"authorization_record_id":"authorization_record_fixture", "dataset_id":"authorized_market_fixture", "observation_id":"observation_fixture_0001", "row_digest":"B"*64, "manifest_sha256":self.dataset["manifest_sha256"]}}))

    def test_statement_whitespace_bytes_change_fails(self):
        args=self.args()
        self.statement_path.write_text(self.statement_path.read_text(encoding="utf-8") + "\n",encoding="utf-8")
        self.assertTrue(any("SHA-256" in x for x in verify_authorized_market_intake(self.root,*args)))

    def test_empty_formal_registry_passes_offline(self):
        (self.root/"data/review/market-authorization/registry.jsonl").write_text("",encoding="utf-8")
        (self.root/"data/review/market-authorization/attestations.jsonl").write_text("",encoding="utf-8")
        self.assertEqual([],verify_authorized_market_intake(self.root))

    def test_observation_date_requires_real_iso_calendar_date(self):
        self.assertTrue(_valid_iso_date("2026-08-01"))
        self.assertFalse(_valid_iso_date("not-a-date"))
        self.assertFalse(_valid_iso_date("2026-02-30"))
