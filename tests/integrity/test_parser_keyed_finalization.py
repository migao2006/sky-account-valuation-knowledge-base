"""P3.8 external keyed finalization end-to-end tests (temporary keys only)."""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from tools.parser_review.onboarding import canonical_bytes, digest, _fingerprint, _keyed_contract_payload, keyed_commitment_merkle_root, keyed_split_commitment, KEYED_CONTRACT_NAMESPACE
from tools.parser_review.finalization import verify_finalization, build_candidate_bundle, import_signed_candidate, DECISION_NAMESPACE, ADJUDICATION_NAMESPACE, NAMESPACE
from tools.modeling.parser_gold_evaluator import audit_gold, evaluate, read_jsonl, _verified_binding_rows, input_sha256, gold_ledger_sha256, parser_source_sha256, parser_config_sha256, manifest_payload, sha256_bytes


class KeyedFinalizationE2E(unittest.TestCase):
 def setUp(self):
  self.temp=Path(tempfile.mkdtemp(prefix='p38-final-')); self.addCleanup(shutil.rmtree,self.temp,True); self.root=self.temp/'release'; self.root.mkdir(); self.ext=self.temp/'external'; self.ext.mkdir(); self.run=0; (self.root/'tools/modeling').mkdir(parents=True); shutil.copyfile(ROOT/'tools/modeling/parse_item_vectors.py',self.root/'tools/modeling/parse_item_vectors.py')
 def key(self,name):
  p=self.ext/name; subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(p)],check=True); pub=p.with_suffix('.pub').read_text().strip(); return p,pub,_fingerprint(pub)
 def sign(self,key,namespace,payload,path):
  raw=self.ext/(path.name+'.payload'); raw.write_bytes(canonical_bytes(payload)); subprocess.run(['ssh-keygen','-Y','sign','-f',str(key),'-n',namespace,str(raw)],check=True,capture_output=True); shutil.copyfile(raw.with_name(raw.name+'.sig'),path)
 def fixture(self):
  self.run+=1; self.ext=self.temp/f'external-{self.run}'; self.ext.mkdir()
  ck,cpub,cfp=self.key('custodian'); reviewers=[self.key(x) for x in ('a','b','j')]
  cb=self.ext/'cust.json'; cb.write_bytes(canonical_bytes({'schema_version':'sky-parser-keyed-custodian-authority-bundle-v1','authorities':[{'authority_id':'parser_custodian_authority_fixture','public_key':cpub,'fingerprint':cfp,'roles':['keyed_custodian_contract']}],'revoked_fingerprints':[]}))
  rb=self.ext/'review.json'; rb.write_bytes(canonical_bytes({'schema_version':'sky-parser-keyed-review-authority-bundle-v2','authorities':[{'authority_id':f'parser_review_{n}','public_key':p,'fingerprint':f,'roles':[r]} for n,(k,p,f),r in zip(('a','b','j'),reviewers,('keyed_annotator_a','keyed_annotator_b','keyed_adjudicator'))],'revoked_fingerprints':[]}))
  commits=[f'{i:064X}' for i in range(1,201)]; assignments=[{'assignment_id':f'assignment_{role}_{i:032x}','reviewer':role} for role in ('annotator_a','annotator_b') for i in range(200)]; ledger=self.ext/'assign.jsonl'; ledger.write_bytes(b''.join(canonical_bytes(x) for x in assignments))
  splits=[{'gold_id':f'parser_gold_{i+1:04d}','input_sha256':'A'*64,'keyed_commitment':commits[i],'split':'development' if i<100 else 'heldout'} for i in range(200)]
  contract={'schema_version':'1.0-p3.7','contract_type':'parser_review_keyed_custodian_contract','cohort_id':'parser_keyed_fixture_20260817','keyed_protocol':'sky-parser-review-keyed-hmac-v1','queue_size':200,'split_counts':{'development':100,'heldout':100},'required_strata':['account_type','era','season','collaboration','set_context'],'strata_distinct_value_counts':{x:2 for x in ['account_type','era','season','collaboration','set_context']},'commitment_merkle_root':keyed_commitment_merkle_root(commits),'split_commitment':keyed_split_commitment(splits),'packet_sha256':{'annotator_a':'B'*64,'annotator_b':'C'*64},'assignment_ledger_sha256':digest(ledger.read_bytes()),'custodian_id':'parser_custodian_fixture','authority_id':'parser_custodian_authority_fixture','fingerprint':cfp,'signature_file':'contract.sig'}; contract['contract_sha256']=digest(canonical_bytes(_keyed_contract_payload(contract))); cp=self.ext/'contract.json'; cp.write_bytes(canonical_bytes(contract)); self.sign(ck,KEYED_CONTRACT_NAMESPACE,_keyed_contract_payload(contract),self.ext/'contract.sig')
  def decisions(role,other=False):
   rows=[]
   for i in range(200):
    row={'decision_id':f'keyed_receipt_{role}_{i:04d}','assignment_id':f'assignment_{role}_{i:032x}','reviewer':role,'expected_canonical_item_ids':['item_test'],'expected_polarity':'confirmed_missing' if other and i==0 else 'owned'}; row['decision_commitment_sha256']=digest(canonical_bytes(row)); rows.append(row)
   path=self.ext/(role+'.jsonl'); path.write_bytes(b''.join(canonical_bytes(x) for x in rows)); return path,rows
  a,ar=decisions('annotator_a'); b,br=decisions('annotator_b',True)
  def side(path,role,key,fp,aid,ns):
   data={'schema_version':'2.0-p3.8','role':role,'authority_id':aid,'fingerprint':fp,'custodian_contract_sha256':contract['contract_sha256'],'ledger_sha256':digest(path.read_bytes()),'signature_file':path.name+'.sig'}; (path.with_suffix(path.suffix+'.commitment.json')).write_bytes(canonical_bytes(data)); self.sign(key,ns,{k:v for k,v in data.items() if k!='signature_file'},path.parent/data['signature_file'])
  side(a,'annotator_a',reviewers[0][0],reviewers[0][2],'parser_review_a',DECISION_NAMESPACE); side(b,'annotator_b',reviewers[1][0],reviewers[1][2],'parser_review_b',DECISION_NAMESPACE)
  adjrow={'adjudication_id':'adjudication_0','cohort_assignment_suffix':f'{0:032x}','annotator_a_decision_commitment_sha256':ar[0]['decision_commitment_sha256'],'annotator_b_decision_commitment_sha256':br[0]['decision_commitment_sha256'],'final_canonical_item_ids':['item_test'],'final_polarity':'owned'}; adjrow['adjudication_commitment_sha256']=digest(canonical_bytes(adjrow)); adj=self.ext/'adj.jsonl'; adj.write_bytes(canonical_bytes(adjrow)); side(adj,'adjudicator',reviewers[2][0],reviewers[2][2],'parser_review_j',ADJUDICATION_NAMESPACE)
  resolution=[]; replay=[]
  for i in range(200):
   profile={'claim':'owned','nonce':i}; listing={'offer_kind':'seller_listing'}; replay.append({'profile':profile,'listing':listing})
   resolution.append({'cohort_assignment_suffix':f'{i:032x}','input_sha256':input_sha256(profile,listing),'keyed_commitment':commits[i],'split':'development' if i<100 else 'heldout','strata':{x:('a' if i%2 else 'b') for x in ['account_type','era','season','collaboration','set_context']}})
  return ck,cb,rb,cp,ledger,a,b,adj,contract,resolution,replay
  return ck,cb,rb,cp,ledger,a,b,adj,contract
 def test_200_row_signed_finalization_and_import(self):
  ck,cb,rb,cp,ledger,a,b,adj,contract,resolution,replay=self.fixture()
  verified=verify_finalization(cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root); self.assertEqual(verified['disagreement_count'],1)
  candidate=build_candidate_bundle(verified,resolution,contract,self.root); candidate_path=self.ext/'candidate.json'; candidate_path.write_bytes(canonical_bytes(candidate)); candidate_sig=self.ext/'candidate.sig'; binding_sig=self.ext/'binding.sig'; self.sign(ck,NAMESPACE,candidate,candidate_sig); self.sign(ck,'sky-parser-keyed-replay-binding-v2',candidate['binding_payload'],binding_sig)
  import_signed_candidate(candidate_path,candidate_sig,binding_sig,resolution,cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root)
  self.assertEqual(len((self.root/'data/review/parser-gold/claims.jsonl').read_text().splitlines()),200)
  # Replaying the same fully verified import is exact-idempotent.
  import_signed_candidate(candidate_path,candidate_sig,binding_sig,resolution,cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root)
  # The binding stays external and is replayed by the evaluator.
  binding=candidate['binding_payload']|{'signature_file':'binding.sig','binding_sha256':digest(canonical_bytes(candidate['binding_payload']))}; bp=self.ext/'binding.json'; bp.write_bytes(canonical_bytes(binding)); replay_path=self.ext/'replay.jsonl'; replay_path.write_bytes(b''.join(canonical_bytes(x) for x in replay))
  queue={'schema_version':'1.0-p3.7','status':'keyed_frozen_pending_external_decisions','cohort_id':contract['cohort_id'],'keyed_protocol':contract['keyed_protocol'],'queue_size':200,'split_counts':contract['split_counts'],'required_strata':contract['required_strata'],'strata_distinct_value_counts':contract['strata_distinct_value_counts'],'commitment_merkle_root':contract['commitment_merkle_root'],'split_commitment':contract['split_commitment'],'packet_sha256':contract['packet_sha256'],'assignment_ledger_sha256':contract['assignment_ledger_sha256'],'custodian_id':contract['custodian_id'],'custodian_authority_id':contract['authority_id'],'custodian_fingerprint':contract['fingerprint'],'custodian_contract_sha256':contract['contract_sha256']}; queue['manifest_sha256']=digest(canonical_bytes(queue)); q=self.root/'data/review/parser-gold/review-queue-manifest.json'; q.write_bytes(canonical_bytes(queue))
  gold=read_jsonl(self.root/'data/review/parser-gold/claims.jsonl'); self.assertEqual(audit_gold(self.root,gold,None,None,cb,digest(cb.read_bytes()),cp,digest(cp.read_bytes()),bp,digest(bp.read_bytes())),[])
  report=evaluate(self.root,gold,replay,resolved_rows=_verified_binding_rows(self.root,bp,digest(bp.read_bytes())),parser=lambda *_:{'item_states':[{'item_id':'item_test','state':'owned'}]}); self.assertEqual(report['development']['row_count'],100); self.assertEqual(report['heldout']['row_count'],100)
  gold[0]['expected_polarity']='unknown'; (self.root/'data/review/parser-gold/claims.jsonl').write_bytes(b''.join(canonical_bytes(x) for x in gold)); self.assertTrue(audit_gold(self.root,gold,None,None,cb,digest(cb.read_bytes()),cp,digest(cp.read_bytes()),bp,digest(bp.read_bytes())))
 def test_same_key_wrong_reference_and_candidate_tamper_fail(self):
  ck,cb,rb,cp,ledger,a,b,adj,contract,resolution,_=self.fixture(); rdata=json.loads(rb.read_text()); rdata['authorities'][1]['public_key']=rdata['authorities'][0]['public_key']; rdata['authorities'][1]['fingerprint']=rdata['authorities'][0]['fingerprint']; rb.write_bytes(canonical_bytes(rdata))
  with self.assertRaises(ValueError): verify_finalization(cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root)
  # Restore a clean fixture, then alter the signed A/B link inside the only adjudication.
  ck,cb,rb,cp,ledger,a,b,adj,contract,resolution,_=self.fixture(); data=json.loads(adj.read_text()); data['annotator_a_decision_commitment_sha256']='0'*64; data['adjudication_commitment_sha256']=digest(canonical_bytes({k:v for k,v in data.items() if k!='adjudication_commitment_sha256'})); adj.write_bytes(canonical_bytes(data))
  with self.assertRaises(ValueError): verify_finalization(cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root)
  # A candidate alteration is rejected before any formal claims are written.
  ck,cb,rb,cp,ledger,a,b,adj,contract,resolution,_=self.fixture(); verified=verify_finalization(cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root); candidate=build_candidate_bundle(verified,resolution,contract,self.root); p=self.ext/'candidate.json'; p.write_bytes(canonical_bytes(candidate)); cs=self.ext/'candidate.sig'; bs=self.ext/'binding.sig'; self.sign(ck,NAMESPACE,candidate,cs); self.sign(ck,'sky-parser-keyed-replay-binding-v2',candidate['binding_payload'],bs); candidate['public_gold'][0]['expected_polarity']='unknown'; p.write_bytes(canonical_bytes(candidate))
  with self.assertRaises(ValueError): import_signed_candidate(p,cs,bs,resolution,cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root)
  self.assertFalse((self.root/'data/review/parser-gold/claims.jsonl').exists())
 def test_import_interrupt_rolls_back_owned_files_and_preserves_racing_sentinel(self):
  ck,cb,rb,cp,ledger,a,b,adj,contract,resolution,_=self.fixture()
  verified=verify_finalization(cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root); candidate=build_candidate_bundle(verified,resolution,contract,self.root)
  candidate_path=self.ext/'candidate.json'; candidate_path.write_bytes(canonical_bytes(candidate)); candidate_sig=self.ext/'candidate.sig'; binding_sig=self.ext/'binding.sig'
  self.sign(ck,NAMESPACE,candidate,candidate_sig); self.sign(ck,'sky-parser-keyed-replay-binding-v2',candidate['binding_payload'],binding_sig)
  foreign=self.root/'data/review/parser-gold/rule-development-manifest.json'; original_open=Path.open
  def race_open(path, mode='r', *args, **kwargs):
   if path == foreign and mode == 'xb':
    foreign.parent.mkdir(parents=True,exist_ok=True)
    with original_open(path,'wb') as handle: handle.write(b'foreign-sentinel')
    raise FileExistsError('racing foreign sentinel')
   return original_open(path,mode,*args,**kwargs)
  with mock.patch.object(Path,'open',new=race_open):
   with self.assertRaises(FileExistsError):
    import_signed_candidate(candidate_path,candidate_sig,binding_sig,resolution,cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root)
  self.assertEqual(foreign.read_bytes(),b'foreign-sentinel')
  self.assertFalse((self.root/'data/review/parser-gold/claims.jsonl').exists())
  self.assertFalse((self.root/'data/review/parser-gold/attestations.jsonl').exists())
  self.assertFalse((self.root/'data/review/parser-gold/.finalization-import.lock').exists())
 def test_import_keyboard_interrupt_rolls_back_all_owned_outputs(self):
  ck,cb,rb,cp,ledger,a,b,adj,contract,resolution,_=self.fixture()
  verified=verify_finalization(cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root); candidate=build_candidate_bundle(verified,resolution,contract,self.root)
  candidate_path=self.ext/'candidate.json'; candidate_path.write_bytes(canonical_bytes(candidate)); candidate_sig=self.ext/'candidate.sig'; binding_sig=self.ext/'binding.sig'
  self.sign(ck,NAMESPACE,candidate,candidate_sig); self.sign(ck,'sky-parser-keyed-replay-binding-v2',candidate['binding_payload'],binding_sig)
  original_copy=shutil.copyfileobj; calls=0
  def interrupt_copy(*args, **kwargs):
   nonlocal calls
   calls+=1
   if calls == 2: raise KeyboardInterrupt('fault injection')
   return original_copy(*args,**kwargs)
  with mock.patch('tools.parser_review.finalization.shutil.copyfileobj',side_effect=interrupt_copy):
   with self.assertRaises(KeyboardInterrupt):
    import_signed_candidate(candidate_path,candidate_sig,binding_sig,resolution,cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root)
  for name in ('claims.jsonl','rule-development-manifest.json','attestations.jsonl','.finalization-import.lock'):
   self.assertFalse((self.root/'data/review/parser-gold'/name).exists())
 def test_journal_resumes_exact_prefix_but_foreign_prefix_is_rejected(self):
  ck,cb,rb,cp,ledger,a,b,adj,contract,resolution,_=self.fixture(); verified=verify_finalization(cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root); candidate=build_candidate_bundle(verified,resolution,contract,self.root)
  candidate_path=self.ext/'candidate.json'; candidate_path.write_bytes(canonical_bytes(candidate)); candidate_sig=self.ext/'candidate.sig'; binding_sig=self.ext/'binding.sig'; self.sign(ck,NAMESPACE,candidate,candidate_sig); self.sign(ck,'sky-parser-keyed-replay-binding-v2',candidate['binding_payload'],binding_sig)
  import_signed_candidate(candidate_path,candidate_sig,binding_sig,resolution,cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root)
  target=self.root/'data/review/parser-gold'; complete=(target/'claims.jsonl').read_bytes(); (target/'claims.jsonl').write_bytes(complete[:101]); (target/'rule-development-manifest.json').unlink(); (target/'attestations.jsonl').unlink()
  stem=f"sky-parser-gold-{digest(str(self.root.resolve()).encode('utf-8'))[:24]}"; journal=Path(tempfile.gettempdir())/f'{stem}.journal.json'; expected={'claims.jsonl':complete,'rule-development-manifest.json':canonical_bytes(candidate['rule_manifest']),'attestations.jsonl':b''}; journal.write_bytes(canonical_bytes({'candidate_sha256':candidate['candidate_sha256'],'expected_sha256':{name:digest(value) for name,value in expected.items()}})); self.addCleanup(journal.unlink,missing_ok=True)
  import_signed_candidate(candidate_path,candidate_sig,binding_sig,resolution,cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root); self.assertEqual((target/'claims.jsonl').read_bytes(),complete); self.assertFalse(journal.exists())
  (target/'claims.jsonl').write_bytes(b'foreign-prefix'); (target/'rule-development-manifest.json').unlink(); (target/'attestations.jsonl').unlink()
  with self.assertRaisesRegex(ValueError,'not this exact signed import'): import_signed_candidate(candidate_path,candidate_sig,binding_sig,resolution,cp,ledger,a,b,adj,cb,digest(cb.read_bytes()),rb,digest(rb.read_bytes()),self.root)
  self.assertEqual((target/'claims.jsonl').read_bytes(),b'foreign-prefix')
 def test_v2_confirmed_missing_false_positive_blocks_50_over_51(self):
  rows=[]; private=[]; replay=[]
  for i in range(200):
   profile={'nonce':i}; listing={'kind':'x'}; polarity='confirmed_missing' if 100<=i<150 else 'owned'; rows.append({'gold_id':f'parser_gold_{i+1:04d}','keyed_commitment':f'{i+1:064X}','expected_canonical_item_ids':['item_test'],'expected_polarity':polarity,'strata':{x:('a' if i%2 else 'b') for x in ['account_type','era','season','collaboration','set_context']}}); private.append({'gold_id':f'parser_gold_{i+1:04d}','input_sha256':input_sha256(profile,listing),'keyed_commitment':f'{i+1:064X}','split':'development' if i<100 else 'heldout'}); replay.append({'profile':profile,'listing':listing})
  manifest={'schema_version':'2.0-p3.8','gold_ledger_sha256':gold_ledger_sha256(rows),'parser_source_sha256':parser_source_sha256(self.root),'parser_config_sha256':parser_config_sha256(),'development_keyed_commitments':sorted(x['keyed_commitment'] for x in private[:100]),'required_strata':['account_type','era','season','collaboration','set_context'],'minimum_distinct_values_per_required_stratum':2}; manifest['manifest_sha256']=sha256_bytes(manifest_payload(manifest)); p=self.root/'data/review/parser-gold'; p.mkdir(parents=True,exist_ok=True); (p/'rule-development-manifest.json').write_bytes(canonical_bytes(manifest))
  def parser(profile,*_): return {'item_states':[{'item_id':'item_test','state':'confirmed_missing' if 100<=int(profile['nonce'])<150 or int(profile['nonce'])==150 else 'owned'}]}
  result=evaluate(self.root,rows,replay,resolved_rows=private,parser=parser); self.assertAlmostEqual(result['heldout']['confirmed_missing']['precision'],50/51); self.assertFalse(result['publication_ready'])
