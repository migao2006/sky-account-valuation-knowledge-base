import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from tools.market_authorization import (AuthorizedMarketEvaluator, NAMESPACE, attestation_payload, canonical_bytes,
    _valid_iso_date, make_authorization_evaluator, model_training_authorization_reasons, sha256_bytes, training_example_commitment, verify_authorized_market_intake)
from tools.modeling.catalog_provenance import catalog_provenance
from tools.modeling.clean_prices import clean as clean_prices, clean_authorized, clean_authorized_with_verified_sales
from tools.validate.validate import authorized_market_schema_files
from tools.validate.schema_validator import OfflineSchemaValidator

REPO_ROOT = Path(__file__).resolve().parents[2]


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
        normal, urgent, exclusions=clean_authorized(duplicate_rows, self.root, *self.args())
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


class AuthorizedMarketFeatureLineageTest(AuthorizedMarketIntakeTest):
    """v2 binds each signed sale to exactly one anonymous model input."""
    def _write_lineage_fixture(self, verified_sales=False):
        (self.root / "knowledge/items").mkdir(parents=True, exist_ok=True)
        (self.root / "knowledge/aliases").mkdir(parents=True, exist_ok=True)
        (self.root / "knowledge/sets").mkdir(parents=True, exist_ok=True)
        (self.root / "knowledge/items/items.jsonl").write_text('{"item_id":"item_fixture"}\n', encoding="utf-8")
        (self.root / "knowledge/aliases/item-aliases.jsonl").write_text("", encoding="utf-8")
        (self.root / "knowledge/sets/item-sets.jsonl").write_text("", encoding="utf-8")
        dsid="authorized_market_fixture"; ddir=self.root / "data/review/market-authorization/datasets" / dsid
        observations=[
            {"observation_id":"observation_fixture_0001", "dedup_cluster_id":"cluster_fixture_0001", "post_date":"2026-08-01", "date_verified":True, "currency":"TWD", "currency_verified":True, "server":"international", "server_verified":True, "offer_kind":"seller_listing", "entity_kind":"single_account", "price_line":"asking", "price_twd":1000},
            {"observation_id":"observation_fixture_0002", "dedup_cluster_id":"cluster_fixture_0002", "post_date":"2026-08-02", "date_verified":True, "currency":"TWD", "currency_verified":True, "server":"international", "server_verified":True, "offer_kind":"seller_listing", "entity_kind":"single_account", "price_line":"reduced", "price_twd":2000},
        ]
        if verified_sales:
            for observation in observations:
                completion_evidence = [
                    {"evidence_id": "evidence_fixture_a", "source_lineage_id": "lineage_fixture_a", "evidence_sha256": "A" * 64},
                    {"evidence_id": "evidence_fixture_b", "source_lineage_id": "lineage_fixture_b", "evidence_sha256": "B" * 64},
                ]
                observation.update({
                    "price_line": "verified_sale", "completed_sale_verified": True,
                    "sale_verified": True, "completed_sale_date": observation["post_date"],
                    "completion_evidence": completion_evidence,
                    "completion_evidence_digest": sha256_bytes(canonical_bytes(completion_evidence)),
                    "independent_evidence_ids": ["evidence_fixture_a", "evidence_fixture_b"],
                })
        op=ddir/"observations.jsonl"; op.write_bytes(b"".join(canonical_bytes(row) for row in observations))
        provenance=catalog_provenance(self.root)
        examples=[]
        for number, observation in enumerate(observations, 1):
            example={"training_example_id":f"training_example_fixture_{number:04d}", "observation_id":observation["observation_id"], "account_id":f"account_fixture_{number:04d}", "feature_payload":{"model_inputs":{"fixture_value":number}, "vector_schema":"fixture-v1"}, "catalog_provenance":provenance, "dedup_cluster_id":observation["dedup_cluster_id"]}
            example["feature_payload_sha256"]=sha256_bytes(canonical_bytes(example["feature_payload"]))
            example["catalog_provenance_sha256"]=sha256_bytes(canonical_bytes(provenance))
            example["dedup_cluster_digest"]=sha256_bytes(canonical_bytes(example["dedup_cluster_id"]))
            if verified_sales:
                example.update({
                    "observation_row_digest": sha256_bytes(canonical_bytes(observation)),
                    "price_line": "verified_sale", "completed_sale_verified": True,
                    "sale_verified": True,
                    "completion_evidence_digest": observation["completion_evidence_digest"],
                    "independent_evidence_ids": observation["independent_evidence_ids"],
                })
            example["training_example_digest"]=sha256_bytes(canonical_bytes(training_example_commitment(example)))
            examples.append(example)
        tp=ddir/"training-examples.jsonl"; tp.write_bytes(b"".join(canonical_bytes(row) for row in examples))
        manifest={"schema_version":"authorized-market-manifest-v3" if verified_sales else "authorized-market-manifest-v2", "dataset_id":dsid, "observations_path":f"data/review/market-authorization/datasets/{dsid}/observations.jsonl", "observations_sha256":self._sha(op), "observation_digests":[{"observation_id":row["observation_id"],"row_digest":sha256_bytes(canonical_bytes(row)),"dedup_cluster_digest":sha256_bytes(canonical_bytes(row["dedup_cluster_id"]))} for row in observations], "training_examples_path":f"data/review/market-authorization/datasets/{dsid}/training-examples.jsonl", "training_examples_sha256":self._sha(tp), "training_example_digests":[{"training_example_id":row["training_example_id"],"training_example_digest":row["training_example_digest"],"observation_id":row["observation_id"],"account_id":row["account_id"],"feature_payload_sha256":row["feature_payload_sha256"],"catalog_provenance_sha256":row["catalog_provenance_sha256"],"dedup_cluster_digest":row["dedup_cluster_digest"]} for row in examples]}
        mp=ddir/"manifest.json"; self._write(mp,manifest)
        statement={"schema_version":"authorized-market-statement-v1", "dataset_id":dsid, "manifest_sha256":self._sha(mp), "observations_sha256":self._sha(op), "expires_at":(date.today()+timedelta(days=30)).isoformat()}
        self._write(self.statement_path,statement)
        self.dataset.update({"manifest_sha256":self._sha(mp), "statement_sha256":self._sha(self.statement_path), "expires_at":statement["expires_at"]})
        (self.root/"data/review/market-authorization/registry.jsonl").write_bytes(canonical_bytes(self.dataset))
        authorities=json.loads(self.bundle_path.read_text(encoding="utf-8"))["authorities"]; entries=[]
        for number, role in enumerate(("data_steward","privacy_reviewer","method_reviewer")):
            authority=next(value for value in authorities if role in value["roles"])
            rel=f"data/review/market-authorization/signatures/{role}.sig"
            entry={"attestation_id":f"authorized_market_attestation_{number:04d}","dataset_id":dsid,"role":role,"authority_id":authority["authority_id"],"fingerprint":authority["fingerprint"],"statement_sha256":self.dataset["statement_sha256"],"manifest_sha256":self.dataset["manifest_sha256"],"observations_sha256":self._sha(op),"signature_file":rel}
            entry["payload_sha256"]=sha256_bytes(attestation_payload(self.dataset,manifest,statement,entry))
            payload=self.external/f"lineage-payload-{number}"; payload.write_bytes(attestation_payload(self.dataset,manifest,statement,entry))
            Path(str(payload)+".sig").unlink(missing_ok=True)
            subprocess.run(["ssh-keygen","-Y","sign","-q","-f",str(self.external/f"key{number}"),"-n",NAMESPACE,str(payload)],check=True)
            shutil.copyfile(str(payload)+".sig",self.root/rel); entries.append(entry)
        (self.root/"data/review/market-authorization/attestations.jsonl").write_bytes(b"".join(canonical_bytes(entry) for entry in entries))
        return observations, examples, manifest

    def _lineage_row(self, observations, examples, manifest, number=0):
        observation, example=observations[number], examples[number]
        authorization={"authorization_record_id":self.dataset["authorization_record_id"],"dataset_id":self.dataset["dataset_id"],"observation_id":observation["observation_id"],"row_digest":sha256_bytes(canonical_bytes(observation)),"manifest_sha256":self.dataset["manifest_sha256"]}
        row={"market_data_authorization":authorization,"selected_price_twd":observation["price_twd"],"price_type":"asking" if observation["price_line"]=="asking" else ("verified_sale" if observation["price_line"]=="verified_sale" else "reduced"),"post_date":observation["post_date"],"date_verified":True,"currency":"TWD","currency_verified":True,"server":"international","server_verified":True,"offer_kind":"seller_listing","entity_kind":"single_account","account_id":example["account_id"],"dedup_cluster_id":example["dedup_cluster_id"],"feature_payload":example["feature_payload"],"catalog_provenance":example["catalog_provenance"],"feature_lineage":{key:example[key] for key in ("training_example_id","training_example_digest","feature_payload_sha256","catalog_provenance_sha256","dedup_cluster_digest")}}
        if observation["price_line"] == "verified_sale":
            row.update({key: observation[key] for key in ("completed_sale_verified", "sale_verified", "completed_sale_date", "completion_evidence_digest", "independent_evidence_ids")})
            row["feature_lineage"].update({key: example[key] for key in ("observation_row_digest", "completion_evidence_digest")})
        return row

    def test_v2_binds_exact_feature_price_cluster_and_catalog(self):
        observations, examples, manifest=self._write_lineage_fixture()
        self.assertEqual([], self.errors())
        evaluator=make_authorization_evaluator(self.root,*self.args())
        self.assertTrue(evaluator.feature_lineage_bound)
        row=self._lineage_row(observations,examples,manifest)
        self.assertTrue(evaluator(row))
        authorized=dict(row, history_id="history_fixture_0001", observed_at="2026-08-01", base_account_type="unknown", market_data_authorization=dict(row["market_data_authorization"], status="authorized_model_training", allowed_uses=["model_training","comparable_estimation"], source_snapshot={"replayable":True,"sha256":"A"*64}, replay_evidence=[{"source_locator":"fixture","content_sha256":"A"*64}], license_evidence={"verified":True,"kind":"explicit_data_license"}))
        self.assertEqual([], model_training_authorization_reasons(authorized, evaluator))
        normal, urgent, exclusions=clean_authorized([authorized], self.root, *self.args())
        self.assertEqual((1, []), (len(urgent), exclusions))
        self.assertEqual(observations[0]["dedup_cluster_id"], normal[0]["cluster_id"])
        self.assertEqual(examples[0]["training_example_id"], normal[0]["training_example_id"])
        self.assertEqual(examples[0]["feature_payload_sha256"], normal[0]["feature_payload_sha256"])
        changed=dict(row, feature_payload={"model_inputs":{"fixture_value":99},"vector_schema":"fixture-v1"})
        self.assertFalse(evaluator(changed))
        swapped=dict(row, feature_payload=examples[1]["feature_payload"])
        self.assertFalse(evaluator(swapped))
        reused=dict(row, account_id=examples[1]["account_id"])
        self.assertFalse(evaluator(reused))

    def test_v3_verified_sale_requires_two_signed_completion_evidences_and_stays_separate(self):
        observations, examples, manifest = self._write_lineage_fixture(verified_sales=True)
        self.assertEqual([], self.errors())
        evaluator = make_authorization_evaluator(self.root, *self.args())
        row = self._lineage_row(observations, examples, manifest)
        self.assertFalse(evaluator(row))
        authorized = dict(row, history_id="history_verified_sale_0001", observed_at="2026-08-01", base_account_type="unknown",
            market_data_authorization=dict(row["market_data_authorization"], status="authorized_model_training", allowed_uses=["model_training", "comparable_estimation"], source_snapshot={"replayable":True,"sha256":"A"*64}, replay_evidence=[{"source_locator":"fixture","content_sha256":"A"*64}], license_evidence={"verified":True,"kind":"explicit_data_license"}))
        self.assertIn("market_data_external_authorization_evaluator_required", model_training_authorization_reasons(authorized, evaluator))
        normal, urgent, sales, exclusions = clean_authorized_with_verified_sales([authorized], self.root, *self.args())
        self.assertEqual(([], [], []), (normal, urgent, sales))
        self.assertTrue(any("market_data_external_authorization_evaluator_required" in row["reason_codes"] for row in exclusions))
        validator = OfflineSchemaValidator(REPO_ROOT / "schemas")
        self.assertEqual([], validator.validate(exclusions[0], REPO_ROOT / "schemas/modeling/price-exclusion.schema.json"))
        self.assertEqual([], clean_authorized([authorized], self.root, *self.args())[0])

    def test_v3_verified_sale_rejects_tamper_asking_claim_single_evidence_uncompleted_and_reuse(self):
        observations, examples, manifest = self._write_lineage_fixture(verified_sales=True)
        evaluator = make_authorization_evaluator(self.root, *self.args())
        row = self._lineage_row(observations, examples, manifest)
        self.assertFalse(evaluator(row))
        self.assertFalse(evaluator(dict(row, price_type="asking")))
        self.assertFalse(evaluator(dict(row, completed_sale_verified=False)))
        self.assertFalse(evaluator(dict(row, independent_evidence_ids=["evidence_fixture_a"])))
        self.assertFalse(evaluator(dict(row, completion_evidence_digest="B" * 64)))
        self.assertFalse(evaluator(dict(row, account_id=examples[1]["account_id"])))
        observations_path = self.root / manifest["observations_path"]
        tampered = [dict(value) for value in observations]
        tampered[0]["price_twd"] = 999
        observations_path.write_bytes(b"".join(canonical_bytes(value) for value in tampered))
        self.assertTrue(any("digests" in error or "does not bind" in error for error in self.errors()))

    def test_v2_registry_dynamically_declares_every_dataset_schema(self):
        _observations, _examples, manifest = self._write_lineage_fixture()
        jsonl_files, json_files = authorized_market_schema_files(self.root)
        self.assertEqual(
            "schemas/market/authorized-market-manifest.schema.json",
            json_files[self.dataset["manifest_path"]],
        )
        self.assertEqual(
            "schemas/market/authorized-market-observation.schema.json",
            jsonl_files[manifest["observations_path"]],
        )
        self.assertEqual(
            "schemas/market/authorized-market-training-example.schema.json",
            jsonl_files[manifest["training_examples_path"]],
        )

    def test_arbitrary_callable_and_direct_constructor_are_not_authorities(self):
        observations, examples, manifest=self._write_lineage_fixture()
        row=self._lineage_row(observations,examples,manifest)
        authorized=dict(row, history_id="history_fixture_0001", observed_at="2026-08-01", base_account_type="unknown", market_data_authorization=dict(row["market_data_authorization"], status="authorized_model_training", allowed_uses=["model_training","comparable_estimation"], source_snapshot={"replayable":True,"sha256":"A"*64}, replay_evidence=[{"source_locator":"fixture","content_sha256":"A"*64}], license_evidence={"verified":True,"kind":"explicit_data_license"}))
        self.assertIn("market_data_external_authorization_evaluator_required", model_training_authorization_reasons(authorized, lambda _row: True))
        forged=AuthorizedMarketEvaluator(tuple(),tuple(),True)
        self.assertFalse(forged.factory_verified)
        self.assertIn("market_data_external_authorization_evaluator_required", model_training_authorization_reasons(authorized, forged))
        with self.assertRaises(TypeError):
            clean_prices([authorized], lambda _row: True)

    def test_v2_rejects_duplicate_commitment_pii_and_catalog_drift(self):
        observations, examples, manifest=self._write_lineage_fixture()
        tp=self.root/manifest["training_examples_path"]
        duplicate=[dict(example) for example in examples]; duplicate[1]["account_id"]=duplicate[0]["account_id"]
        tp.write_bytes(b"".join(canonical_bytes(row) for row in duplicate))
        self.assertTrue(any("training example commitments" in error for error in self.errors()))
        self._write_lineage_fixture()
        pii=[dict(example) for example in examples]; pii[0]["feature_payload"]={"email":"person@example.com"}
        tp.write_bytes(b"".join(canonical_bytes(row) for row in pii))
        self.assertTrue(any("PII" in error for error in self.errors()))
        self._write_lineage_fixture()
        (self.root/"knowledge/items/items.jsonl").write_text('{"item_id":"item_drift"}\n',encoding="utf-8")
        self.assertTrue(any("stale catalog provenance" in error for error in self.errors()))
