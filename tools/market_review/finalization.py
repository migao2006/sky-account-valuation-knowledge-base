#!/usr/bin/env python3
"""Fail-closed replay and import for an externally keyed market review.

The private resolution map never enters the release.  This module only accepts
it from an externally rooted custodian, rebuilds every result from the signed
ledgers, and uses exclusive creates plus owned-file rollback for the two public
artifacts it writes.
"""
from __future__ import annotations

import hashlib, json, os, subprocess, tempfile
from datetime import date
from pathlib import Path
from typing import Any

from tools.market_review.keyed_custodian import (ASSIGNMENT_SIZE, QUEUE_SIZE,
    ROLES, _outside, _read_assignments, canonical_bytes, digest,
    load_authorities, validate_contract)

ROOT = Path(__file__).resolve().parents[2]
DECISION_NAMESPACE = "sky-market-keyed-decision-v1"
ADJUDICATION_NAMESPACE = "sky-market-keyed-adjudication-v1"
FINALIZATION_NAMESPACE = "sky-market-keyed-finalization-v1"
BINDING_NAMESPACE = "sky-market-keyed-replay-binding-v1"
REVIEW_AUTHORITY_VERSION = "sky-market-keyed-review-authority-bundle-v1"
REVIEW_ROLES = {"annotator_a", "annotator_b", "adjudicator"}

def _read(path: Path) -> list[dict[str, Any]]:
    try: rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, json.JSONDecodeError) as exc: raise ValueError("external keyed market JSONL is invalid") from exc
    if any(not isinstance(row, dict) for row in rows): raise ValueError("external keyed market JSONL rows must be objects")
    return rows

def _payload(value: dict[str, Any], *omit: str) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k not in omit}

def _verify(payload: dict[str, Any], authority: dict[str, Any], signature: Path, identity: str, namespace: str) -> None:
    if not signature.is_file(): raise ValueError("detached signature is missing")
    with tempfile.TemporaryDirectory(prefix="market-keyed-final-") as temp:
        allowed = Path(temp) / "allowed"; allowed.write_text(f"{identity} {authority['public_key'].strip()}\n", encoding="utf-8")
        ok = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", identity, "-n", namespace, "-s", str(signature)], input=canonical_bytes(payload), capture_output=True, check=False).returncode == 0
    if not ok: raise ValueError("detached signature verification failed")

def load_review_authorities(path_value: str | Path, expected_sha: str, root: Path) -> dict[str, dict[str, Any]]:
    path = _outside(path_value, root, "keyed market review authority bundle")
    if not path.is_file() or digest(path.read_bytes()) != expected_sha.upper(): raise ValueError("review authority bundle digest does not match")
    try: bundle = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc: raise ValueError("review authority bundle is not JSON") from exc
    if not isinstance(bundle, dict) or set(bundle) != {"schema_version", "authorities", "revoked_fingerprints"} or bundle["schema_version"] != REVIEW_AUTHORITY_VERSION: raise ValueError("review authority bundle is unsupported")
    revoked, out = bundle["revoked_fingerprints"], {}
    from tools.market_review.keyed_custodian import _fingerprint
    if not isinstance(revoked, list) or not isinstance(bundle["authorities"], list): raise ValueError("review authority bundle is malformed")
    for row in bundle["authorities"]:
        if not isinstance(row, dict) or set(row) != {"authority_id", "public_key", "fingerprint", "roles"}: raise ValueError("review authority has unsupported fields")
        if (not isinstance(row["authority_id"], str) or row["authority_id"] in out or _fingerprint(row["public_key"]) != row["fingerprint"] or row["fingerprint"] in revoked or not isinstance(row["roles"], list) or not set(row["roles"]).issubset(REVIEW_ROLES)):
            raise ValueError("review authority identity, role, or key is invalid")
        out[row["authority_id"]] = row
    if not out: raise ValueError("review authority bundle has no active authorities")
    return out

def _sidecar(path_value: Path, role: str, authorities: dict[str, dict[str, Any]], root: Path, contract_sha: str) -> tuple[list[dict[str, Any]], str]:
    path = _outside(path_value, root, f"{role} decision ledger"); rows = _read(path); sidecar = path.with_suffix(path.suffix + ".commitment.json")
    try: record = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValueError(f"{role} signed ledger sidecar is invalid") from exc
    required = {"schema_version", "role", "authority_id", "fingerprint", "custodian_contract_sha256", "ledger_sha256", "signature_file"}
    if not isinstance(record, dict) or set(record) != required or record.get("schema_version") != "1.0-p4.2" or record.get("role") != role or record.get("custodian_contract_sha256") != contract_sha or record.get("ledger_sha256") != digest(b"".join(canonical_bytes(x) for x in rows)):
        raise ValueError(f"{role} signed ledger does not bind contents")
    authority = authorities.get(record.get("authority_id"))
    if authority is None or authority["fingerprint"] != record.get("fingerprint") or role not in authority["roles"]: raise ValueError(f"{role} authority is unauthorized")
    name = record.get("signature_file")
    if not isinstance(name, str) or Path(name).name != name: raise ValueError(f"{role} signature path is invalid")
    _verify(_payload(record, "signature_file"), authority, path.parent / name, record["authority_id"], ADJUDICATION_NAMESPACE if role == "adjudicator" else DECISION_NAMESPACE)
    return rows, authority["fingerprint"]

def _labels(value: Any) -> dict[str, Any]:
    required = {"offer_kind", "entity_kind", "server", "currency", "price_type", "price_twd", "status", "date_verified", "verified_sale"}
    choices = {"offer_kind":{"seller_listing","buyer_budget","service","exchange","risk_report","unknown"}, "entity_kind":{"single_account","multi_account","service","product","unknown"}, "server":{"international","china","unknown"}, "currency":{"TWD","HKD","RM","CNY","unknown"}, "price_type":{"asking","reduced","instant","instant_price","quick_sale","buyout","direct","auction","auction_floor","buyer_budget","buyer_demand","buyer_offer","exchange","exchange_only","non_cash_exchange","multi_account","multi_price","multi_currency","foreign_currency","currency_unknown","sold_explicit","sold_last_ask","market_claim","unknown"}, "status":{"active","wanted","sold","sold_claimed","reported_sold","unknown"}}
    if (not isinstance(value, dict) or set(value) != required or value.get("verified_sale") is not False or any(value.get(k) not in allowed for k,allowed in choices.items()) or not isinstance(value.get("date_verified"), bool) or (value["price_twd"] is not None and (not isinstance(value["price_twd"], int) or isinstance(value["price_twd"], bool) or value["price_twd"] < 0))): raise ValueError("market decision labels are malformed")
    return value

def _iso_date(value: Any) -> bool:
    if not isinstance(value, str): return False
    try: return date.fromisoformat(value).isoformat() == value
    except ValueError: return False

def _decision(row: dict[str, Any], role: str) -> tuple[str, dict[str, Any]]:
    required = {"decision_id", "assignment_id", "reviewer", "annotator_id", "annotated_at", "labels", "decision_commitment_sha256"}
    if not isinstance(row, dict) or set(row) != required or row.get("reviewer") != role or not isinstance(row.get("assignment_id"), str) or not isinstance(row.get("annotator_id"), str) or not row["annotator_id"].startswith("human_") or not _iso_date(row.get("annotated_at")): raise ValueError(f"{role} decision has unsupported fields")
    payload = _payload(row, "decision_commitment_sha256")
    if row.get("decision_commitment_sha256") != digest(canonical_bytes(payload)): raise ValueError(f"{role} decision commitment is invalid")
    return row["assignment_id"], {"annotator_id": row["annotator_id"], "annotator_kind": "human", "annotated_at": row["annotated_at"], "labels": _labels(row["labels"])}

def verify_finalization(contract_path: Path, assignment_ledger: Path, decisions_a: Path, decisions_b: Path, adjudications: Path, custodian_authority_bundle: Path, custodian_authority_sha256: str, review_authority_bundle: Path, review_authority_sha256: str, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve(); contract_path = _outside(contract_path, root, "keyed market custodian contract")
    contract = validate_contract(json.loads(contract_path.read_text(encoding="utf-8")), contract_path, root, custodian_authority_bundle, custodian_authority_sha256)
    assigned = _read_assignments(assignment_ledger, contract, root); authorities = load_review_authorities(review_authority_bundle, review_authority_sha256, root)
    arows, afp = _sidecar(decisions_a, "annotator_a", authorities, root, contract["contract_sha256"]); brows, bfp = _sidecar(decisions_b, "annotator_b", authorities, root, contract["contract_sha256"]); jrows, jfp = _sidecar(adjudications, "adjudicator", authorities, root, contract["contract_sha256"])
    if len({afp, bfp, jfp, contract["fingerprint"]}) != 4: raise ValueError("A/B/adjudicator/custodian require four distinct fingerprints")
    parsed: dict[str, dict[str, tuple[dict[str, Any], str]]] = {}
    for role, rows in (("annotator_a", arows), ("annotator_b", brows)):
        values = {}; decision_ids = set()
        for row in rows:
            assignment, annotation = _decision(row, role)
            decision_id = row.get("decision_id")
            if assignment in values or not isinstance(decision_id, str) or not decision_id or decision_id in decision_ids: raise ValueError(f"{role} assignment or decision ID is duplicated")
            decision_ids.add(decision_id)
            values[assignment] = (annotation, row["decision_commitment_sha256"])
        if set(values) != assigned[role]: raise ValueError(f"{role} decisions must cover exactly 200 assignments")
        parsed[role] = values
    suffix = lambda x: x.rsplit("_", 1)[-1]
    am, bm = {suffix(x): v for x, v in parsed["annotator_a"].items()}, {suffix(x): v for x, v in parsed["annotator_b"].items()}
    if set(am) != set(bm) or len(am) != QUEUE_SIZE: raise ValueError("A/B assignments do not form paired 200-row cohort")
    conflicts = {x for x in am if am[x][0]["labels"] != bm[x][0]["labels"]}; resolved = {}; adjudication_ids = set()
    for row in jrows:
        required = {"adjudication_id", "cohort_assignment_suffix", "annotator_a_decision_commitment_sha256", "annotator_b_decision_commitment_sha256", "adjudicator_id", "adjudicated_at", "final_labels", "adjudication_commitment_sha256"}
        key = row.get("cohort_assignment_suffix") if isinstance(row, dict) else None
        adjudication_id = row.get("adjudication_id") if isinstance(row, dict) else None
        if (not isinstance(row, dict) or set(row) != required or key not in conflicts or key in resolved
                or not isinstance(adjudication_id, str) or not adjudication_id or adjudication_id in adjudication_ids
                or not isinstance(row.get("adjudicator_id"), str) or not row["adjudicator_id"].startswith("human_")
                or not _iso_date(row.get("adjudicated_at"))): raise ValueError("adjudication is missing, duplicate, or not limited to disagreement")
        adjudication_ids.add(adjudication_id)
        if row["adjudication_commitment_sha256"] != digest(canonical_bytes(_payload(row, "adjudication_commitment_sha256"))) or row["annotator_a_decision_commitment_sha256"] != am[key][1] or row["annotator_b_decision_commitment_sha256"] != bm[key][1]: raise ValueError("adjudication commitment does not bind A/B decisions")
        resolved[key] = {"adjudicator_id": row["adjudicator_id"], "adjudicator_kind": "human", "adjudicated_at": row["adjudicated_at"], "decision": "resolved_disagreement", "final_labels": _labels(row["final_labels"])}
    if set(resolved) != conflicts: raise ValueError("every and only A/B disagreements require adjudication")
    final = {x: (am[x][0], bm[x][0], resolved.get(x, {"adjudicator_id":"human_agreement", "adjudicator_kind":"human", "adjudicated_at":am[x][0]["annotated_at"], "decision":"agreement", "final_labels":am[x][0]["labels"]})) for x in am}
    return {"schema_version":"1.0-p4.2", "status":"external_keyed_finalization_verified", "cohort_id":contract["cohort_id"], "custodian_contract_sha256":contract["contract_sha256"], "annotator_a_ledger_sha256":digest(b"".join(canonical_bytes(x) for x in arows)), "annotator_b_ledger_sha256":digest(b"".join(canonical_bytes(x) for x in brows)), "adjudication_ledger_sha256":digest(b"".join(canonical_bytes(x) for x in jrows)), "agreement_count":QUEUE_SIZE-len(conflicts), "disagreement_count":len(conflicts), "formal_gold_written":False, "_final":final}

def _queue(root: Path) -> dict[str, dict[str, Any]]:
    rows = _read(root / "data/review/market-claim-review.jsonl")
    if len(rows) != QUEUE_SIZE or len({x.get("review_id") for x in rows}) != QUEUE_SIZE: raise ValueError("committed market queue is not exactly 200 rows")
    return {x["review_id"]: x for x in rows}

def build_candidate_bundle(verified: dict[str, Any], resolution_rows: list[dict[str, Any]], contract: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    final, queue = verified.get("_final"), _queue(root)
    required = {"cohort_assignment_suffix", "review_id", "listing_id", "listing_text_sha256", "keyed_commitment", "bucket", "split"}
    if not isinstance(final, dict) or len(final) != QUEUE_SIZE or len(resolution_rows) != QUEUE_SIZE or any(not isinstance(x, dict) or set(x) != required for x in resolution_rows): raise ValueError("private resolution map must contain exactly 200 rows")
    seen_s, seen_r, commitments, gold, binding = set(), set(), [], [], []
    for index, row in enumerate(sorted(resolution_rows, key=lambda x: x["keyed_commitment"]), 1):
        suffix, rid = row["cohort_assignment_suffix"], row["review_id"]
        if suffix not in final or suffix in seen_s or rid not in queue or rid in seen_r or row["split"] not in {"development", "heldout"} or not isinstance(row["bucket"], int) or not 0 <= row["bucket"] < 20 or not isinstance(row["keyed_commitment"], str) or len(row["keyed_commitment"]) != 64: raise ValueError("private resolution map is not a valid bijection")
        q = queue[rid]
        expected_bucket = f"market_claim_bucket_{row['bucket'] + 1:02d}"
        if (row["listing_id"] != q.get("listing_id") or row["listing_text_sha256"] != q.get("listing_text_sha256")
                or q.get("selection_bucket") != expected_bucket): raise ValueError("private resolution map does not bind committed queue and bucket")
        seen_s.add(suffix); seen_r.add(rid); commitments.append(row["keyed_commitment"]); a,b,j = final[suffix]
        gold.append({"gold_id":f"market_claim_gold_{index:04d}", "review_id":rid, "listing_id":row["listing_id"], "listing_text_sha256":row["listing_text_sha256"], "annotation_protocol":"double_independent_human_annotation", "annotator_a":a, "annotator_b":b, "adjudication":j, "review_status":"approved_human_gold"})
        binding.append(row)
    if seen_s != set(final) or seen_r != set(queue) or any(sum(x["bucket"] == b and x["split"] == s for x in binding) != 5 for b in range(20) for s in ("development", "heldout")): raise ValueError("private map lacks exact 20 bucket 5/5 split")
    if digest(canonical_bytes(sorted(commitments))) != contract["commitment_merkle_root"] or digest(canonical_bytes(sorted((x["keyed_commitment"], x["split"]) for x in binding))) != contract["split_commitment"]: raise ValueError("private map does not reproduce custodian commitments")
    finalization = {k:v for k,v in verified.items() if not k.startswith("_")}; finalization["public_gold_sha256"] = digest(b"".join(canonical_bytes(x) for x in gold)); finalization["finalization_sha256"] = digest(canonical_bytes(finalization))
    binding_payload = {"schema_version":"1.0-p4.2", "contract_type":"market_review_keyed_replay_binding", "cohort_id":contract["cohort_id"], "custodian_contract_sha256":contract["contract_sha256"], "commitment_merkle_root":contract["commitment_merkle_root"], "split_commitment":contract["split_commitment"], "authority_id":contract["authority_id"], "fingerprint":contract["fingerprint"], "binding_rows":binding, "finalization_sha256":finalization["finalization_sha256"], "public_gold_sha256":finalization["public_gold_sha256"]}
    candidate = {"schema_version":"1.0-p4.2", "status":"external_candidate_bundle_unsigned", "public_gold":gold, "binding_payload":binding_payload, "finalization":finalization, "formal_gold_written":False}; candidate["candidate_sha256"] = digest(canonical_bytes(candidate)); return candidate

def import_signed_candidate(candidate_path: Path, candidate_signature: Path, binding_signature: Path, resolution_rows: list[dict[str, Any]], contract_path: Path, assignment_ledger: Path, decisions_a: Path, decisions_b: Path, adjudications: Path, custodian_authority_bundle: Path, custodian_authority_sha256: str, review_authority_bundle: Path, review_authority_sha256: str, root: Path = ROOT) -> dict[str, Any]:
    root=root.resolve(); candidate_path=_outside(candidate_path,root,"external candidate"); contract_path=_outside(contract_path,root,"custodian contract")
    candidate=json.loads(candidate_path.read_text(encoding="utf-8")); contract=json.loads(contract_path.read_text(encoding="utf-8")); verified=verify_finalization(contract_path,assignment_ledger,decisions_a,decisions_b,adjudications,custodian_authority_bundle,custodian_authority_sha256,review_authority_bundle,review_authority_sha256,root); rebuilt=build_candidate_bundle(verified,resolution_rows,contract,root)
    if candidate != rebuilt: raise ValueError("candidate does not exactly reproduce signed provenance")
    authority=load_authorities(custodian_authority_bundle,custodian_authority_sha256,root).get(contract.get("authority_id"))
    if authority is None: raise ValueError("contracted custodian authority unavailable")
    _verify(candidate,authority,_outside(candidate_signature,root,"candidate signature"),contract["authority_id"],FINALIZATION_NAMESPACE); _verify(candidate["binding_payload"],authority,_outside(binding_signature,root,"binding signature"),contract["authority_id"],BINDING_NAMESPACE)
    target=root/"data/review"; claims=target/"market-claim-gold.jsonl"; receipt=target/"market-keyed-finalization-receipt.json"
    gold_bytes=b"".join(canonical_bytes(x) for x in rebuilt["public_gold"]); binding_sha=digest(canonical_bytes(rebuilt["binding_payload"]))
    receipt_value={"schema_version":"1.0-p4.2", "status":"keyed_market_gold_imported", "cohort_id":contract["cohort_id"], "custodian_contract_sha256":contract["contract_sha256"], "public_gold_sha256":rebuilt["finalization"]["public_gold_sha256"], "finalization_sha256":rebuilt["finalization"]["finalization_sha256"], "candidate_sha256":rebuilt["candidate_sha256"], "binding_payload_sha256":binding_sha, "candidate_signature_sha256":digest(Path(candidate_signature).read_bytes()), "binding_signature_sha256":digest(Path(binding_signature).read_bytes()), "formal_gold_written":True}; receipt_value["receipt_sha256"]=digest(canonical_bytes(receipt_value))
    # The repository deliberately tracks an empty placeholder.  It is the sole
    # replaceable baseline; a nonempty ledger is immutable.  Repeating the same
    # signed import is idempotent and never rewrites either artifact.
    resume_receipt = False
    if receipt.exists():
        try: existing=json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError): raise ValueError("formal market gold receipt already exists")
        if existing == receipt_value and claims.is_file() and claims.read_bytes() == gold_bytes: return receipt_value
        if existing == receipt_value and claims.is_file() and gold_bytes.startswith(claims.read_bytes()): resume_receipt = True
        else: raise ValueError("formal market gold import must not overwrite existing artifact")
    claims_bytes = claims.read_bytes() if claims.exists() else None
    resume_gold = not receipt.exists() and claims_bytes == gold_bytes
    if claims_bytes not in (None, b"", gold_bytes) and not (resume_receipt and gold_bytes.startswith(claims_bytes)): raise ValueError("formal market gold import must not overwrite nonempty ledger")
    created=[]; prior_empty=claims.exists(); baseline_identity=None; baseline_bytes=claims_bytes
    if prior_empty:
        stat=claims.stat(); baseline_identity=(stat.st_dev,stat.st_ino)
    try:
        target.mkdir(parents=True,exist_ok=True)
        # Reserve receipt first; an exact receipt-only crash residue may resume.
        if not resume_receipt:
            with receipt.open("xb") as f:
                identity=(os.fstat(f.fileno()).st_dev,os.fstat(f.fileno()).st_ino)
                created.append((receipt,identity))
                f.write(canonical_bytes(receipt_value)); f.flush(); os.fsync(f.fileno())
        if resume_gold:
            if not claims.is_file() or claims.read_bytes() != gold_bytes:
                raise ValueError("formal market gold changed during crash recovery")
            return receipt_value
        if prior_empty:
            # Write through the same handle whose inode and empty pre-state we
            # verified.  A racing pathname replacement is never overwritten:
            # it is detected after the write and this owned inode is restored.
            with claims.open("r+b") as f:
                identity=(os.fstat(f.fileno()).st_dev,os.fstat(f.fileno()).st_ino)
                if identity != baseline_identity or f.read() != baseline_bytes or not gold_bytes.startswith(baseline_bytes or b""):
                    raise ValueError("formal market gold placeholder changed during import")
                try:
                    f.seek(0); f.write(gold_bytes); f.truncate(); f.flush(); os.fsync(f.fileno())
                    stat=claims.stat()
                    if (stat.st_dev,stat.st_ino) != identity:
                        raise ValueError("formal market gold destination changed during import")
                except BaseException:
                    f.seek(0); f.write(baseline_bytes or b""); f.truncate(); f.flush(); os.fsync(f.fileno())
                    raise
        else:
            with claims.open("xb") as f:
                identity=(os.fstat(f.fileno()).st_dev,os.fstat(f.fileno()).st_ino)
                created.append((claims,identity))
                f.write(gold_bytes); f.flush(); os.fsync(f.fileno())
    except BaseException:
        for path,identity in reversed(created):
            try:
                st=path.stat()
                if (st.st_dev,st.st_ino)==identity: path.unlink()
            except OSError: pass
        raise
    return receipt_value
