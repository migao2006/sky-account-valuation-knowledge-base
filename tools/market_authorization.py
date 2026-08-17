"""Fail-closed authorization checks for market-model use."""
from __future__ import annotations
import hashlib, json, os, re, subprocess, tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

_FACTORY_CAPABILITY = object()

NAMESPACE = "sky-authorized-market-v1"
AUTHORITY_ENV, AUTHORITY_SHA_ENV = "SKY_AUTHORIZED_MARKET_AUTHORITY_BUNDLE", "SKY_AUTHORIZED_MARKET_AUTHORITY_BUNDLE_SHA256"
STATEMENT_ENV, STATEMENT_SHA_ENV = "SKY_AUTHORIZED_MARKET_STATEMENT", "SKY_AUTHORIZED_MARKET_STATEMENT_SHA256"
REGISTRY_REL = Path("data/review/market-authorization/registry.jsonl")
ATTESTATIONS_REL, SIGNATURES_REL = Path("data/review/market-authorization/attestations.jsonl"), Path("data/review/market-authorization/signatures")
ROLES = ("data_steward", "privacy_reviewer", "method_reviewer")
OBSERVATION_FIELDS = {"observation_id", "source_snapshot_sha256", "dedup_cluster_id", "post_date", "date_verified", "currency", "currency_verified", "server", "server_verified", "offer_kind", "entity_kind", "price_line", "price_twd"}
VERIFIED_SALE_OBSERVATION_FIELDS = OBSERVATION_FIELDS | {"completed_sale_verified", "sale_verified", "completed_sale_date", "completion_evidence", "completion_evidence_digest", "independent_evidence_ids"}
TRAINING_EXAMPLE_FIELDS = {"training_example_id", "observation_id", "source_snapshot_sha256", "account_id", "feature_payload", "feature_payload_sha256", "catalog_provenance", "catalog_provenance_sha256", "dedup_cluster_id", "dedup_cluster_digest", "training_example_digest"}
VERIFIED_SALE_TRAINING_EXAMPLE_FIELDS = TRAINING_EXAMPLE_FIELDS | {"observation_row_digest", "price_line", "completed_sale_verified", "sale_verified", "completion_evidence_digest", "independent_evidence_ids"}
PII_KEY = re.compile(r"(?:name|user|handle|social|uid|email|mail|phone|mobile|contact|login|payment|address|url|link)", re.I)
EMAIL, PHONE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b"), re.compile(r"(?:\+\d[\d .()-]{6,}\d|\(?\d{2,4}\)?[ .-]\d{3,4}[ .-]\d{3,4})")

def canonical_bytes(v: Any) -> bytes: return (json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))+"\n").encode()
def sha256_bytes(v: bytes) -> str: return hashlib.sha256(v).hexdigest().upper()
def _valid_iso_date(value: Any) -> bool:
    if not isinstance(value,str): return False
    try: date.fromisoformat(value); return True
    except ValueError: return False

def _sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Fa-f0-9]{64}", value))

def _valid_observation(row: dict[str, Any], version: str) -> bool:
    """Keep a verified sale a distinct signed event, never a listing label."""
    sale = row.get("price_line") == "verified_sale"
    expected_fields = VERIFIED_SALE_OBSERVATION_FIELDS if sale else OBSERVATION_FIELDS
    if set(row) != expected_fields or (sale and version != "authorized-market-manifest-v3"):
        return False
    return bool(
        isinstance(row.get("observation_id"), str) and row["observation_id"].startswith("observation_")
        and _sha256(row.get("source_snapshot_sha256"))
        and isinstance(row.get("dedup_cluster_id"), str) and row["dedup_cluster_id"].startswith("cluster_")
        and isinstance(row.get("price_twd"), int) and not isinstance(row["price_twd"], bool) and row["price_twd"] >= 1
        and row.get("date_verified") is True and row.get("currency") == "TWD" and row.get("currency_verified") is True
        and row.get("server") == "international" and row.get("server_verified") is True
        and row.get("offer_kind") == "seller_listing" and row.get("entity_kind") == "single_account"
        and row.get("price_line") in {"asking", "reduced", "urgent_sale", "verified_sale"}
        and _valid_iso_date(row.get("post_date"))
        and (not sale or (
            row.get("completed_sale_verified") is True and row.get("sale_verified") is True
            and row.get("completed_sale_date") == row.get("post_date") and _valid_iso_date(row.get("completed_sale_date"))
            and isinstance(row.get("completion_evidence"), list) and len(row["completion_evidence"]) >= 2
            and all(isinstance(value, dict) and set(value) == {"evidence_id", "source_lineage_id", "evidence_sha256"}
                    and isinstance(value["evidence_id"], str) and value["evidence_id"].startswith("evidence_")
                    and isinstance(value["source_lineage_id"], str) and value["source_lineage_id"].startswith("lineage_")
                    and _sha256(value["evidence_sha256"]) for value in row["completion_evidence"])
            and len({value["source_lineage_id"] for value in row["completion_evidence"]}) == len(row["completion_evidence"])
            and row.get("completion_evidence_digest", "").upper() == sha256_bytes(canonical_bytes(row["completion_evidence"]))
            and isinstance(row.get("independent_evidence_ids"), list) and len(row["independent_evidence_ids"]) >= 2
            and len(row["independent_evidence_ids"]) == len(set(row["independent_evidence_ids"]))
            and all(isinstance(value, str) and value.startswith("evidence_") for value in row["independent_evidence_ids"])
            and row["independent_evidence_ids"] == [value["evidence_id"] for value in row["completion_evidence"]]
        ))
    )

def _valid_feature_payload(value: Any, root: Path | None = None) -> bool:
    try:
        from tools.market_intake.onboarding import feature_payload_errors
        return not feature_payload_errors(value, root or Path(__file__).resolve().parents[1])
    except Exception:
        return False
def _inside(p: Path, parent: Path) -> bool:
    try: p.resolve().relative_to(parent.resolve()); return True
    except ValueError: return False
def _jsonl(p: Path) -> list[dict[str, Any]]:
    if not p.exists(): return []
    out=[]
    for n,line in enumerate(p.read_text(encoding="utf-8").splitlines(),1):
        if line.strip():
            x=json.loads(line)
            if not isinstance(x,dict): raise ValueError(f"{p}:{n}: row is not object")
            out.append(x)
    return out
def _pii(v: Any, path: str="$") -> list[str]:
    found=[]
    if isinstance(v,dict):
        for k,x in v.items():
            q=f"{path}.{k}"
            if PII_KEY.search(str(k)): found.append(q)
            found.extend(_pii(x,q))
    elif isinstance(v,list):
        for i,x in enumerate(v): found.extend(_pii(x,f"{path}[{i}]"))
    elif isinstance(v,str) and (EMAIL.search(v) or PHONE.search(v) or v.startswith(("http://","https://"))): found.append(path)
    return found
def _fingerprint(key: str) -> str|None:
    x=subprocess.run(["ssh-keygen","-lf","-"],input=key+"\n",text=True,capture_output=True,check=False).stdout.strip().split()
    return x[1] if len(x)>=2 else None
def _external(pathv: str|Path|None, digest: str|None, root: Path, label: str) -> tuple[dict[str,Any]|None,list[str]]:
    if not pathv or not digest: return None,[f"{label} path and SHA-256 must be injected"]
    p=Path(pathv).expanduser().resolve()
    if _inside(p,root): return None,[f"{label} must be outside the release root"]
    if not p.is_file(): return None,[f"{label} is missing"]
    if sha256_bytes(p.read_bytes())!=str(digest).upper(): return None,[f"{label} SHA-256 does not match injected digest"]
    try: x=json.loads(p.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError): return None,[f"{label} is not valid JSON"]
    return (x if isinstance(x,dict) else None),([] if isinstance(x,dict) else [f"{label} is not an object"])

def attestation_payload(dataset: dict[str,Any], manifest: dict[str,Any], statement: dict[str,Any], attestation: dict[str,Any]) -> bytes:
    return canonical_bytes({"contract":NAMESPACE,"dataset":dataset,"manifest":manifest,"statement":statement,"attestation":{k:v for k,v in attestation.items() if k!="payload_sha256"}})


def training_example_commitment(row: dict[str, Any]) -> dict[str, Any]:
    """The signed, PII-free join between one sale and one model input."""
    commitment = {
        "training_example_id": row.get("training_example_id"),
        "observation_id": row.get("observation_id"),
        "source_snapshot_sha256": row.get("source_snapshot_sha256"),
        "account_id": row.get("account_id"),
        "feature_payload_sha256": row.get("feature_payload_sha256"),
        "catalog_provenance_sha256": row.get("catalog_provenance_sha256"),
        "dedup_cluster_id": row.get("dedup_cluster_id"),
        "dedup_cluster_digest": row.get("dedup_cluster_digest"),
    }
    # v3 adds the completed-sale proof to the signed feature join itself.
    if row.get("price_line") == "verified_sale":
        commitment.update({key: row.get(key) for key in (
            "observation_row_digest", "price_line", "completed_sale_verified", "sale_verified",
            "completion_evidence_digest", "independent_evidence_ids",
        )})
    return commitment


def _catalog_digest(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))

def _verify_sig(authority: dict[str,Any], entry: dict[str,Any], payload: bytes, root: Path) -> bool:
    sp=root/str(entry.get("signature_file",""))
    if not _inside(sp,root/SIGNATURES_REL) or not sp.is_file(): return False
    with tempfile.TemporaryDirectory(prefix="sky-authorized-market-") as t:
        allowed=Path(t)/"allowed"; allowed.write_text(f"{entry['authority_id']} {authority['public_key'].strip()}\n",encoding="utf-8",newline="\n")
        c=subprocess.run(["ssh-keygen","-Y","verify","-f",str(allowed),"-I",entry["authority_id"],"-n",NAMESPACE,"-s",str(sp)],input=payload,capture_output=True,check=False)
    return c.returncode==0

def verify_authorized_market_intake(root: Path, authority_bundle: str|Path|None=None, authority_bundle_sha256: str|None=None, statement: str|Path|None=None, statement_sha256: str|None=None) -> list[str]:
    """Verify every byte and approval. Empty formal registry passes offline."""
    root=root.resolve()
    try: datasets,attestations=_jsonl(root/REGISTRY_REL),_jsonl(root/ATTESTATIONS_REL)
    except (OSError,ValueError,json.JSONDecodeError) as e: return [f"authorized market registry is unreadable: {e}"]
    if not datasets: return [] if not attestations else ["authorized market attestations exist without a dataset registry"]
    bundle,errors=_external(authority_bundle or os.environ.get(AUTHORITY_ENV),authority_bundle_sha256 or os.environ.get(AUTHORITY_SHA_ENV),root,"external authority bundle")
    st,se=_external(statement or os.environ.get(STATEMENT_ENV),statement_sha256 or os.environ.get(STATEMENT_SHA_ENV),root,"external authorization statement"); errors.extend(se)
    if not bundle or not st: return errors
    if bundle.get("schema_version")!="authorized-market-authority-bundle-v1": errors.append("external authority bundle has unsupported schema_version")
    if st.get("schema_version")!="authorized-market-statement-v1": errors.append("external authorization statement has unsupported schema_version")
    auth={}; revoked=set(bundle.get("revoked_fingerprints",[]))
    for x in bundle.get("authorities",[]) if isinstance(bundle.get("authorities"),list) else []:
        if not isinstance(x,dict): errors.append("external authority record is not an object"); continue
        aid,key=x.get("authority_id"),x.get("public_key"); fp=_fingerprint(key) if isinstance(key,str) else None
        if not isinstance(aid,str) or aid in auth or not isinstance(x.get("roles"),list) or not fp or x.get("fingerprint")!=fp: errors.append("external authority record has invalid identity, roles, or fingerprint"); continue
        if fp in revoked: errors.append(f"external authority {aid} fingerprint is revoked"); continue
        auth[aid]=x
    if not isinstance(bundle.get("authorities"),list): errors.append("external authority bundle has no authorities array")
    by={}
    for x in attestations: by.setdefault(str(x.get("dataset_id")),[]).append(x)
    seen=set(); statement_digest=sha256_bytes(Path(statement or os.environ.get(STATEMENT_ENV)).expanduser().resolve().read_bytes())
    mappings: dict[str, set[tuple[str,str,str,str]]] = {}
    committed_training_clusters: set[str] = set()
    for ds in datasets:
        did=ds.get("dataset_id")
        if not isinstance(did,str) or did in seen: errors.append("authorized market dataset_id is missing or duplicated"); continue
        seen.add(did)
        if not isinstance(ds.get("authorization_record_id"), str) or not str(ds["authorization_record_id"]).startswith("authorization_record_"):
            errors.append(f"{did}: authorization record ID is invalid")
        if _pii(ds): errors.append(f"{did}: PII-like data in registry")
        mp=root/str(ds.get("manifest_path",""))
        if not _inside(mp,root/"data/review/market-authorization/datasets") or not mp.is_file(): errors.append(f"{did}: manifest path missing or escapes datasets"); continue
        try: m=json.loads(mp.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError): errors.append(f"{did}: manifest is invalid JSON"); continue
        version = m.get("schema_version") if isinstance(m, dict) else None
        if not isinstance(m,dict) or version not in {"authorized-market-manifest-v1", "authorized-market-manifest-v2", "authorized-market-manifest-v3"} or m.get("dataset_id")!=did: errors.append(f"{did}: manifest identity/schema is invalid"); continue
        if _pii(m): errors.append(f"{did}: PII-like data in manifest")
        msh=sha256_bytes(mp.read_bytes()); op=root/str(m.get("observations_path",""))
        if ds.get("manifest_sha256", "").upper() != msh: errors.append(f"{did}: registry manifest SHA-256 does not bind bytes")
        if not _inside(op,mp.parent) or not op.is_file(): errors.append(f"{did}: observations path missing or escapes dataset"); continue
        ob=op.read_bytes(); osh=sha256_bytes(ob)
        try: rows=_jsonl(op)
        except (ValueError,json.JSONDecodeError): errors.append(f"{did}: observations JSONL invalid"); continue
        rd=[sha256_bytes(canonical_bytes(x)) for x in rows]; cd=[sha256_bytes(canonical_bytes(x.get("dedup_cluster_id"))) for x in rows]
        expected=[{"observation_id": x.get("observation_id"), "row_digest": r, "dedup_cluster_digest": c} for x,r,c in zip(rows,rd,cd)]
        manifest_map=m.get("observation_digests")
        if osh!=str(m.get("observations_sha256","")).upper() or not rows or len(rd)!=len(set(rd)) or len(cd)!=len(set(cd)) or not isinstance(manifest_map,list) or len(manifest_map)!=len(rows) or len({x.get("observation_id") for x in rows})!=len(rows) or {canonical_bytes(x) for x in expected}!={canonical_bytes(x) for x in manifest_map}: errors.append(f"{did}: manifest/observation row or cluster digests do not bind bytes")
        if any(not _valid_observation(x, str(version)) for x in rows): errors.append(f"{did}: observation violates exact anonymous allowlist")
        if any(_pii(x) for x in rows): errors.append(f"{did}: nested PII-like data in observations")
        if version in {"authorized-market-manifest-v2", "authorized-market-manifest-v3"}:
            tp=root/str(m.get("training_examples_path", ""))
            if not _inside(tp, mp.parent) or not tp.is_file():
                errors.append(f"{did}: training examples path missing or escapes dataset")
            else:
                examples_bytes=tp.read_bytes()
                try: examples=_jsonl(tp)
                except (ValueError,json.JSONDecodeError):
                    examples=[]; errors.append(f"{did}: training examples JSONL invalid")
                expected_catalog=None
                try:
                    from tools.modeling.catalog_provenance import catalog_provenance
                    expected_catalog=catalog_provenance(root)
                except Exception as exc: errors.append(f"{did}: current catalog provenance is unavailable: {exc}")
                observation_by_id={str(row.get("observation_id")): row for row in rows}
                example_digests=[]
                for example in examples:
                    feature=example.get("feature_payload")
                    catalog=example.get("catalog_provenance")
                    commitment=training_example_commitment(example)
                    example_digests.append({
                        "training_example_id": example.get("training_example_id"),
                        "training_example_digest": sha256_bytes(canonical_bytes(commitment)),
                        "observation_id": example.get("observation_id"),
                        "account_id": example.get("account_id"),
                        "feature_payload_sha256": _catalog_digest(feature),
                        "catalog_provenance_sha256": _catalog_digest(catalog),
                        "dedup_cluster_digest": sha256_bytes(canonical_bytes(example.get("dedup_cluster_id"))),
                    })
                manifest_examples=m.get("training_example_digests")
                expected_example_fields = VERIFIED_SALE_TRAINING_EXAMPLE_FIELDS if version == "authorized-market-manifest-v3" else TRAINING_EXAMPLE_FIELDS
                exact_fields = all(set(example) == expected_example_fields for example in examples)
                identifiers = [str(example.get("training_example_id")) for example in examples]
                observations = [str(example.get("observation_id")) for example in examples]
                accounts = [str(example.get("account_id")) for example in examples]
                clusters = [str(example.get("dedup_cluster_id")) for example in examples]
                reused_across_datasets = set(clusters) & committed_training_clusters
                committed_training_clusters.update(clusters)
                hashes_ok=all(
                    _valid_feature_payload(example.get("feature_payload"), root)
                    and
                    example.get("feature_payload_sha256", "").upper()==_catalog_digest(example.get("feature_payload"))
                    and example.get("catalog_provenance_sha256", "").upper()==_catalog_digest(example.get("catalog_provenance"))
                    and example.get("dedup_cluster_digest", "").upper()==sha256_bytes(canonical_bytes(example.get("dedup_cluster_id")))
                    and example.get("training_example_digest", "").upper()==sha256_bytes(canonical_bytes(training_example_commitment(example)))
                    for example in examples
                )
                linked_ok=all(
                    example.get("observation_id") in observation_by_id
                    and example.get("dedup_cluster_id")==observation_by_id[str(example.get("observation_id"))].get("dedup_cluster_id")
                    and str(example.get("source_snapshot_sha256", "")).upper() == str(observation_by_id[str(example.get("observation_id"))].get("source_snapshot_sha256", "")).upper()
                    and (version != "authorized-market-manifest-v3" or (
                        observation_by_id[str(example.get("observation_id"))].get("price_line") == "verified_sale"
                        and example.get("observation_row_digest", "").upper() == sha256_bytes(canonical_bytes(observation_by_id[str(example.get("observation_id"))]))
                        and example.get("price_line") == "verified_sale"
                        and example.get("completed_sale_verified") is True
                        and example.get("sale_verified") is True
                        and example.get("completion_evidence_digest", "").upper() == observation_by_id[str(example.get("observation_id"))].get("completion_evidence_digest", "").upper()
                        and example.get("independent_evidence_ids") == observation_by_id[str(example.get("observation_id"))].get("independent_evidence_ids")
                    ))
                    for example in examples
                )
                if (
                    m.get("training_examples_sha256", "").upper()!=sha256_bytes(examples_bytes)
                    or not examples or not exact_fields
                    or any(not value.startswith("training_example_") for value in identifiers)
                    or any(not value.startswith("account_") for value in accounts)
                    or len(identifiers)!=len(set(identifiers)) or len(observations)!=len(set(observations))
                    or len(accounts)!=len(set(accounts)) or len(clusters)!=len(set(clusters))
                    or not hashes_ok or not linked_ok
                    or not isinstance(manifest_examples, list) or len(manifest_examples)!=len(examples)
                    or {canonical_bytes(value) for value in example_digests}!={canonical_bytes(value) for value in manifest_examples}
                ):
                    errors.append(f"{did}: training example commitments do not bind exact price, feature, account, and cluster bytes")
                if any(_pii(example) for example in examples): errors.append(f"{did}: PII-like data in training examples")
                if expected_catalog is not None and any(example.get("catalog_provenance") != expected_catalog for example in examples):
                    errors.append(f"{did}: training examples have stale catalog provenance")
                if reused_across_datasets:
                    errors.append(f"{did}: dedup cluster commitment is reused across datasets")
        if ds.get("statement_sha256","").upper()!=statement_digest or st.get("dataset_id")!=did or st.get("manifest_sha256","").upper()!=msh or st.get("observations_sha256","").upper()!=osh: errors.append(f"{did}: external statement does not bind dataset bytes")
        try:
            expiry=str(ds.get("expires_at",""))
            if date.fromisoformat(expiry)<date.today() or st.get("expires_at")!=expiry: errors.append(f"{did}: authorization is expired or expiry does not bind")
        except ValueError: errors.append(f"{did}: authorization expiry is invalid")
        es=by.get(did,[])
        if len(es)!=3 or {x.get("role") for x in es}!=set(ROLES): errors.append(f"{did}: requires exactly one attestation for each role"); continue
        fps=set()
        for x in es:
            a=auth.get(x.get("authority_id")); role=x.get("role")
            if not a or role not in a.get("roles",[]) or a.get("fingerprint")!=x.get("fingerprint"): errors.append(f"{did}:{role}: authority does not hold role or fingerprint"); continue
            fps.add(str(x.get("fingerprint")))
            if x.get("statement_sha256","").upper()!=statement_digest or x.get("manifest_sha256","").upper()!=msh or x.get("observations_sha256","").upper()!=osh: errors.append(f"{did}:{role}: attestation bytes binding mismatch"); continue
            payload=attestation_payload(ds,m,st,x)
            if x.get("payload_sha256")!=sha256_bytes(payload) or not _verify_sig(a,x,payload,root): errors.append(f"{did}:{role}: detached signature does not verify")
        if len(fps)!=3: errors.append(f"{did}: three roles require distinct authority fingerprints")
        if not any(error.startswith(f"{did}:") for error in errors):
            mappings[str(ds.get("authorization_record_id"))] = {(did, str(x["observation_id"]), digest, msh) for x, digest in zip(rows, rd)}
    if set(by)-seen: errors.append("authorized market attestation references absent dataset")
    return errors

@dataclass(frozen=True)
class AuthorizedMarketEvaluator:
    authorized_observations: tuple[tuple[tuple[str,str,str,str,str], dict[str,Any]], ...]
    errors: tuple[str,...]=()
    feature_lineage_bound: bool=False
    cluster_independence_bound: bool=False
    receipt_bound_observation_ids: tuple[str, ...]=()
    _factory_capability: object|None=None
    @property
    def factory_verified(self) -> bool:
        """True only for an evaluator returned by the canonical verifier factory."""
        return self._factory_capability is _FACTORY_CAPABILITY
    def __call__(self,row: dict[str,Any]) -> bool:
        x=row.get("market_data_authorization")
        required=(x.get("authorization_record_id"),x.get("dataset_id"),x.get("observation_id"),x.get("row_digest"),x.get("manifest_sha256")) if isinstance(x,dict) else ()
        if self.errors:
            return False
        binding = next((value for key, value in self.authorized_observations if key == required), None)
        if binding is None:
            return False
        observation = binding["observation"] if "observation" in binding else binding
        price_type = str(row.get("price_type", row.get("normalized_price_type", ""))).lower()
        expected_line = observation["price_line"]
        # A signed metadata assertion is not a replayable receipt or
        # counterparty proof.  Keep verified-sale intake fail-closed until a
        # privacy-preserving completion-evidence archive/evaluator exists.
        if expected_line == "verified_sale" and observation["observation_id"] not in self.receipt_bound_observation_ids:
            return False
        line_matches = (
            (expected_line == "asking" and price_type in {"asking", "normal_listing"})
            or (expected_line == "reduced" and price_type == "reduced")
            or (expected_line == "urgent_sale" and price_type in {"urgent_sale", "quick_sale", "instant", "instant_price"})
            or (expected_line == "verified_sale" and price_type == "verified_sale")
        )
        price_matches = bool(
            line_matches
            and row.get("selected_price_twd") == observation["price_twd"]
            and row.get("post_date") == observation["post_date"]
            and row.get("date_verified") is observation["date_verified"]
            and row.get("currency") == observation["currency"]
            and row.get("currency_verified") is observation["currency_verified"]
            and row.get("server") == observation["server"]
            and row.get("server_verified") is observation["server_verified"]
            and row.get("offer_kind") == observation["offer_kind"]
            and row.get("entity_kind") == observation["entity_kind"]
        )
        if not price_matches:
            return False
        if not self.feature_lineage_bound:
            return True
        example = binding.get("training_example")
        lineage = row.get("feature_lineage")
        actual_cluster = row.get("dedup_cluster_id", row.get("cluster_id"))
        if not isinstance(example, dict) or not isinstance(lineage, dict):
            return False
        return bool(
            row.get("account_id") == example["account_id"]
            and actual_cluster == example["dedup_cluster_id"]
            and row.get("feature_payload") == example["feature_payload"]
            and row.get("catalog_provenance") == example["catalog_provenance"]
            and lineage.get("training_example_id") == example["training_example_id"]
            and lineage.get("training_example_digest", "").upper() == example["training_example_digest"]
            and lineage.get("feature_payload_sha256", "").upper() == example["feature_payload_sha256"]
            and lineage.get("catalog_provenance_sha256", "").upper() == example["catalog_provenance_sha256"]
            and lineage.get("dedup_cluster_digest", "").upper() == example["dedup_cluster_digest"]
            and (observation["price_line"] != "verified_sale" or (
                lineage.get("observation_row_digest", "").upper() == example["observation_row_digest"]
                and lineage.get("completion_evidence_digest", "").upper() == example["completion_evidence_digest"]
            ))
        )

    def bound_training_rows(self) -> list[dict[str, Any]]:
        """Project verified v2 intake into cleaner rows without listing lineage.

        The projection is available only on a factory-verified evaluator.  It
        deliberately bypasses the legacy comparable-account schema: authorized
        datasets contain opaque observations and signed feature commitments,
        not fabricated listing/history records.
        """
        if not self.factory_verified or self.errors or not self.feature_lineage_bound or not self.cluster_independence_bound:
            return []
        result: list[dict[str, Any]] = []
        for key, binding in self.authorized_observations:
            observation, example = binding.get("observation"), binding.get("training_example")
            dataset, manifest = binding.get("dataset"), binding.get("manifest")
            if not all(isinstance(value, dict) for value in (observation, example, dataset, manifest)):
                continue
            price_line = observation["price_line"]
            row = {
                "history_id": "history_authorized_" + str(dataset["dataset_id"]).removeprefix("authorized_market_") + "_" + str(observation["observation_id"]).removeprefix("observation_"),
                "account_id": example["account_id"], "dedup_cluster_id": example["dedup_cluster_id"],
                "selected_price_twd": observation["price_twd"], "price_type": price_line,
                "post_date": observation["post_date"], "date_verified": True, "observed_at": observation["post_date"],
                "currency": "TWD", "currency_verified": True, "server": "international", "server_verified": True,
                "offer_kind": "seller_listing", "entity_kind": "single_account", "base_account_type": "unknown",
                "feature_payload": example["feature_payload"], "catalog_provenance": example["catalog_provenance"],
                "feature_lineage": {name: example[name] for name in (
                    "training_example_id", "training_example_digest", "feature_payload_sha256",
                    "catalog_provenance_sha256", "dedup_cluster_digest",
                )},
                "market_data_authorization": {
                    "status": "authorized_model_training", "allowed_uses": ["model_training", "comparable_estimation"],
                    "source_snapshot": {"artifact_path": dataset["manifest_path"], "sha256": dataset["manifest_sha256"], "captured_at": observation["post_date"], "replayable": True},
                    "license_evidence": {"kind": "explicit_data_license", "evidence_id": dataset["authorization_record_id"], "verified": True},
                    "replay_evidence": [{"evidence_id": observation["observation_id"], "source_locator": manifest["observations_path"], "content_sha256": key[3], "reviewed_at": observation["post_date"]}],
                    "authorization_record_id": key[0], "dataset_id": key[1], "observation_id": key[2], "row_digest": key[3], "manifest_sha256": key[4],
                },
            }
            if price_line == "verified_sale":
                # Metadata-only sale claims remain unavailable to __call__
                # until replayable completion evidence is implemented.
                row.update({name: observation[name] for name in (
                    "completed_sale_verified", "sale_verified", "completed_sale_date",
                    "completion_evidence_digest", "independent_evidence_ids",
                )})
                row["feature_lineage"].update({name: example[name] for name in ("observation_row_digest", "completion_evidence_digest")})
            result.append(row)
        return result

def make_authorization_evaluator(
    root: Path, authority_bundle: str|Path|None=None, authority_bundle_sha256: str|None=None,
    statement: str|Path|None=None, statement_sha256: str|None=None,
    identity_authority_bundle: str|Path|None=None, identity_authority_bundle_sha256: str|None=None,
    identity_mapping: str|Path|None=None, identity_mapping_sha256: str|None=None,
    identity_statement: str|Path|None=None, identity_statement_sha256: str|None=None,
    receipt_archive: str|Path|None=None, receipt_archive_sha256: str|None=None,
    receipt_authority_bundle: str|Path|None=None, receipt_authority_bundle_sha256: str|None=None,
) -> AuthorizedMarketEvaluator:
    errors=verify_authorized_market_intake(root,authority_bundle,authority_bundle_sha256,statement,statement_sha256)
    mappings: list[tuple[tuple[str,str,str,str,str], dict[str,Any]]] = []
    feature_lineage_bound=False
    if not errors:
        for ds in _jsonl(root/REGISTRY_REL):
            mp=root/str(ds["manifest_path"]); manifest=json.loads(mp.read_text(encoding="utf-8")); rows=_jsonl(root/manifest["observations_path"])
            examples_by_observation={}
            if manifest.get("schema_version") in {"authorized-market-manifest-v2", "authorized-market-manifest-v3"}:
                examples=_jsonl(root/manifest["training_examples_path"])
                examples_by_observation={str(example["observation_id"]): example for example in examples}
                feature_lineage_bound=True
            mappings.extend(
                ((str(ds["authorization_record_id"]), str(ds["dataset_id"]), str(row["observation_id"]), sha256_bytes(canonical_bytes(row)), str(ds["manifest_sha256"]).upper()), {"observation": row, "training_example": examples_by_observation.get(str(row["observation_id"])), "dataset": ds, "manifest": manifest})
                for row in rows
            )
    # Supplier-derived opaque cluster digests are only labels.  They become an
    # independence boundary when a separate, externally held resolver mapping
    # has replayed every exact signed training-example binding.
    identity_args = (
        identity_authority_bundle, identity_authority_bundle_sha256,
        identity_mapping, identity_mapping_sha256, identity_statement, identity_statement_sha256,
    )
    cluster_independence_bound = False
    identity_index: dict[tuple[str, str], dict[str, Any]] = {}
    if not errors and feature_lineage_bound and any(value is not None for value in identity_args):
        from tools.market_identity.verifier import verify_identity_mapping
        identity_errors, identity_index = verify_identity_mapping(
            root, [binding for _key, binding in mappings],
            identity_authority_bundle, identity_authority_bundle_sha256,
            identity_mapping, identity_mapping_sha256,
            identity_statement, identity_statement_sha256,
        )
        errors.extend(identity_errors)
        cluster_independence_bound = not identity_errors
    receipt_bound: list[str] = []
    receipt_args = (receipt_archive, receipt_archive_sha256, receipt_authority_bundle, receipt_authority_bundle_sha256)
    sale_bindings = [binding for _key, binding in mappings if binding["observation"].get("price_line") == "verified_sale"]
    if not errors and sale_bindings and any(value is not None for value in receipt_args):
        from tools.market_receipts.verifier import disclosure_matches_authorized_sale, verify_receipt_archive
        replay = verify_receipt_archive(root, receipt_archive, receipt_archive_sha256, receipt_authority_bundle, receipt_authority_bundle_sha256)
        errors.extend(replay.errors)
        if not replay.errors:
            for binding in sale_bindings:
                observation, example = binding["observation"], binding.get("training_example") or {}
                identity = identity_index.get((str(binding["dataset"]["dataset_id"]), str(example.get("training_example_id"))), {})
                expected = {
                    **observation,
                    **{key: example.get(key) for key in ("training_example_id", "training_example_digest", "observation_row_digest")},
                    "identity_mapping_commitment_sha256": identity.get("identity_commitment"),
                }
                matches = [row for row in replay.disclosures if disclosure_matches_authorized_sale(row, expected)]
                if len(matches) != 1:
                    errors.append(f"{observation['observation_id']}: receipt archive does not bind exactly one authorized sale")
                else:
                    receipt_bound.append(str(observation["observation_id"]))
            expected_ids = {str(binding["observation"]["observation_id"]) for binding in sale_bindings}
            replay_ids = {str(row["observation_id"]) for row in replay.disclosures}
            if replay_ids != expected_ids:
                errors.append("receipt archive observations differ from formal verified-sale observations")
    return AuthorizedMarketEvaluator(
        tuple(mappings), tuple(errors), feature_lineage_bound, cluster_independence_bound,
        tuple(sorted(receipt_bound)) if not errors else (), _FACTORY_CAPABILITY,
    )

def model_training_authorization_reasons(row: dict[str,Any], external_evaluator: Callable[[dict[str,Any]],bool]|None=None) -> list[str]:
    x=row.get("market_data_authorization")
    if not isinstance(x,dict): return ["market_data_authorization_missing"]
    r=[]
    if x.get("status")!="authorized_model_training": r.append("market_data_not_authorized_for_model_training")
    if not isinstance(x.get("allowed_uses"),list) or not {"model_training","comparable_estimation"}.issubset(x["allowed_uses"]): r.append("market_data_authorized_uses_incomplete")
    s=x.get("source_snapshot")
    if not isinstance(s,dict) or s.get("replayable") is not True or not isinstance(s.get("sha256"),str) or len(s["sha256"])!=64: r.append("market_data_replay_evidence_missing")
    q=x.get("replay_evidence")
    if not isinstance(q,list) or not q or any(not isinstance(y,dict) or not y.get("source_locator") or not isinstance(y.get("content_sha256"),str) or len(y["content_sha256"])!=64 for y in q):
        if "market_data_replay_evidence_missing" not in r: r.append("market_data_replay_evidence_missing")
    l=x.get("license_evidence")
    if not isinstance(l,dict) or l.get("verified") is not True or l.get("kind") not in {"explicit_data_license","documented_data_consent"}: r.append("market_data_license_evidence_missing")
    if not x.get("authorization_record_id"): r.append("market_data_authorization_record_missing")
    if x.get("status")=="authorized_model_training":
        if not isinstance(external_evaluator, AuthorizedMarketEvaluator) or external_evaluator.factory_verified is not True:
            r.append("market_data_external_authorization_evaluator_required")
        elif external_evaluator.feature_lineage_bound is not True:
            r.append("market_data_feature_lineage_evaluator_required")
        elif external_evaluator.cluster_independence_bound is not True:
            r.append("market_data_cluster_independence_evaluator_required")
        elif external_evaluator(row) is not True:
            r.append("market_data_external_authorization_evaluator_required")
    return r
