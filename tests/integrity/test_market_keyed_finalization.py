from __future__ import annotations
import json, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from tools.market_review.keyed_custodian import CONTRACT_NAMESPACE, _contract_payload, _fingerprint, canonical_bytes, digest
from tools.market_review.finalization import (BINDING_NAMESPACE, DECISION_NAMESPACE, ADJUDICATION_NAMESPACE, FINALIZATION_NAMESPACE, _payload, build_candidate_bundle, import_signed_candidate, verify_finalization)
from tools.modeling.market_gold_evaluator import build as build_market_gold_evaluation

class MarketKeyedFinalizationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp(prefix="market-final-"));self.addCleanup(shutil.rmtree,self.tmp,True);self.root=self.tmp/'release';(self.root/'data/review').mkdir(parents=True);self.ext=self.tmp/'external';self.ext.mkdir(); src=Path(__file__).resolve().parents[2]/'data/review/market-claim-review.jsonl';shutil.copyfile(src,self.root/'data/review/market-claim-review.jsonl')
 def key(self,name):
  p=self.ext/name;subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(p)],check=True);return p,p.with_suffix('.pub').read_text().strip(),_fingerprint(p.with_suffix('.pub').read_text().strip())
 def sign(self,key,namespace,path,payload):
  raw=path.with_suffix('.payload');raw.write_bytes(canonical_bytes(payload));subprocess.run(['ssh-keygen','-Y','sign','-q','-f',str(key),'-n',namespace,str(raw)],check=True);shutil.move(raw.with_name(raw.name+'.sig'),path)
 def fixture(self):
  cust,cpub,cfp=self.key('custodian'); a,apub,afp=self.key('a'); b,bpub,bfp=self.key('b'); j,jpub,jfp=self.key('j')
  ca=self.ext/'custodian-authority.json';ca.write_bytes(canonical_bytes({'schema_version':'sky-market-keyed-custodian-authority-bundle-v1','authorities':[{'authority_id':'market_custodian_authority_fixture','public_key':cpub,'fingerprint':cfp,'roles':['keyed_market_custodian_contract']}],'revoked_fingerprints':[]}))
  ra=self.ext/'review-authority.json';ra.write_bytes(canonical_bytes({'schema_version':'sky-market-keyed-review-authority-bundle-v1','authorities':[{'authority_id':'review_a','public_key':apub,'fingerprint':afp,'roles':['annotator_a']},{'authority_id':'review_b','public_key':bpub,'fingerprint':bfp,'roles':['annotator_b']},{'authority_id':'review_j','public_key':jpub,'fingerprint':jfp,'roles':['adjudicator']}],'revoked_fingerprints':[]}))
  assignments=[]
  for role in ('annotator_a','annotator_b'):
   assignments += [{'assignment_id':f'market_assignment_{role}_{i:032x}','reviewer':role} for i in range(200)]
  ledger=self.ext/'assignments.jsonl';ledger.write_bytes(b''.join(canonical_bytes(x) for x in assignments))
  queue=[json.loads(x) for x in (self.root/'data/review/market-claim-review.jsonl').read_text().splitlines() if x.strip()]
  maps=[]
  for i,q in enumerate(queue): maps.append({'cohort_assignment_suffix':f'{i:032x}','review_id':q['review_id'],'listing_id':q['listing_id'],'listing_text_sha256':q['listing_text_sha256'],'keyed_commitment':f'{i:064X}','bucket':i//10,'split':'development' if i%10<5 else 'heldout'})
  contract={'schema_version':'1.0-p4.1','contract_type':'market_review_keyed_custodian_contract','cohort_id':'market_keyed_fixture_20260817','keyed_protocol':'sky-market-review-keyed-custodian-v1','queue_size':200,'assignment_count':400,'packet_counts':{'annotator_a':200,'annotator_b':200},'commitment_merkle_root':digest(canonical_bytes(sorted(x['keyed_commitment'] for x in maps))),'split_commitment':digest(canonical_bytes(sorted((x['keyed_commitment'],x['split']) for x in maps))),'packet_sha256':{'annotator_a':'A'*64,'annotator_b':'B'*64},'assignment_ledger_sha256':digest(ledger.read_bytes()),'custodian_id':'market_custodian_fixture','authority_id':'market_custodian_authority_fixture','fingerprint':cfp,'signature_file':'contract.sig'};contract['contract_sha256']=digest(canonical_bytes(_contract_payload(contract)));cp=self.ext/'contract.json';cp.write_bytes(canonical_bytes(contract));self.sign(cust,CONTRACT_NAMESPACE,self.ext/'contract.sig',_contract_payload(contract))
  labels={'offer_kind':'seller_listing','entity_kind':'single_account','server':'international','currency':'TWD','price_type':'asking','price_twd':1,'status':'active','date_verified':True,'verified_sale':False}
  paths=[]
  for role,key,aid in [('annotator_a',a,'review_a'),('annotator_b',b,'review_b')]:
   rows=[]
   for i in range(200):
    row={'decision_id':f'{role}_{i}','assignment_id':f'market_assignment_{role}_{i:032x}','reviewer':role,'annotator_id':'human_'+role,'annotated_at':'2026-08-17','labels':labels,'decision_commitment_sha256':''};row['decision_commitment_sha256']=digest(canonical_bytes(_payload(row,'decision_commitment_sha256')));rows.append(row)
   p=self.ext/(role+'.jsonl');p.write_bytes(b''.join(canonical_bytes(x) for x in rows));side={'schema_version':'1.0-p4.2','role':role,'authority_id':aid,'fingerprint':afp if role=='annotator_a' else bfp,'custodian_contract_sha256':contract['contract_sha256'],'ledger_sha256':digest(p.read_bytes()),'signature_file':role+'.sig'};p.with_suffix(p.suffix+'.commitment.json').write_bytes(canonical_bytes(side));self.sign(key,DECISION_NAMESPACE,self.ext/(role+'.sig'),_payload(side,'signature_file'));paths.append(p)
  adj=self.ext/'adj.jsonl';adj.write_bytes(b'');side={'schema_version':'1.0-p4.2','role':'adjudicator','authority_id':'review_j','fingerprint':jfp,'custodian_contract_sha256':contract['contract_sha256'],'ledger_sha256':digest(b''),'signature_file':'adj.sig'};adj.with_suffix(adj.suffix+'.commitment.json').write_bytes(canonical_bytes(side));self.sign(j,ADJUDICATION_NAMESPACE,self.ext/'adj.sig',_payload(side,'signature_file'))
  return cp,ledger,*paths,adj,ca,digest(ca.read_bytes()),ra,digest(ra.read_bytes()),maps,cust
 def test_200_row_openssh_end_to_end_and_import(self):
  cp,ledger,a,b,adj,ca,csha,ra,rsha,maps,cust=self.fixture();v=verify_finalization(cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root);self.assertEqual(v['agreement_count'],200);c=build_candidate_bundle(v,maps,json.loads(cp.read_text()),self.root);candidate=self.ext/'candidate.json';candidate.write_bytes(canonical_bytes(c));self.sign(cust,FINALIZATION_NAMESPACE,self.ext/'candidate.sig',c);self.sign(cust,BINDING_NAMESPACE,self.ext/'binding.sig',c['binding_payload']);(self.root/'data/review/market-claim-gold.jsonl').write_bytes(b'');receipt=import_signed_candidate(candidate,self.ext/'candidate.sig',self.ext/'binding.sig',maps,cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root);self.assertTrue(receipt['formal_gold_written']);self.assertEqual(len((self.root/'data/review/market-claim-gold.jsonl').read_text().splitlines()),200);self.assertNotIn('listing_id',json.dumps(receipt));self.assertEqual(receipt,import_signed_candidate(candidate,self.ext/'candidate.sig',self.ext/'binding.sig',maps,cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root));resolution=self.ext/'resolution.jsonl';resolution.write_bytes(b''.join(canonical_bytes(x) for x in maps));report=build_market_gold_evaluation(self.root,None,None,ca,csha,ra,rsha,cp,ledger,a,b,adj,resolution,candidate,self.ext/'candidate.sig',self.ext/'binding.sig');self.assertEqual(report['partition_method'],'keyed_signed_binding_v1');self.assertEqual(report['metrics']['development']['row_count'],100);self.assertEqual(report['metrics']['heldout']['row_count'],100);self.assertTrue(report['publication_ready'])
 def test_tamper_key_reuse_and_no_partial_import(self):
  cp,ledger,a,b,adj,ca,csha,ra,rsha,maps,cust=self.fixture();rows=[json.loads(x) for x in a.read_text().splitlines()];rows[0]['labels']['price_twd']=9;a.write_bytes(b''.join(canonical_bytes(x) for x in rows));
  with self.assertRaises(ValueError): verify_finalization(cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root)
  # A custodian key cannot be reused for a human reviewer even with a valid ledger sidecar.
  bundle=json.loads(ra.read_text());bundle['authorities'][0]['fingerprint']=json.loads(ca.read_text())['authorities'][0]['fingerprint'];ra.write_bytes(canonical_bytes(bundle))
  with self.assertRaises(ValueError): verify_finalization(cp,ledger,a,b,adj,ca,csha,ra,digest(ra.read_bytes()),self.root)
  self.assertFalse((self.root/'data/review/market-keyed-finalization-receipt.json').exists())
 def test_candidate_binding_tamper_and_import_fault_roll_back(self):
  cp,ledger,a,b,adj,ca,csha,ra,rsha,maps,cust=self.fixture();v=verify_finalization(cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root);c=build_candidate_bundle(v,maps,json.loads(cp.read_text()),self.root);candidate=self.ext/'candidate.json';candidate.write_bytes(canonical_bytes(c));self.sign(cust,FINALIZATION_NAMESPACE,self.ext/'candidate.sig',c);self.sign(cust,BINDING_NAMESPACE,self.ext/'binding.sig',c['binding_payload'])
  changed=json.loads(candidate.read_text());changed['public_gold'][0]['annotator_a']['labels']['price_twd']=999;candidate.write_bytes(canonical_bytes(changed))
  with self.assertRaisesRegex(ValueError,'reproduce'): import_signed_candidate(candidate,self.ext/'candidate.sig',self.ext/'binding.sig',maps,cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root)
  candidate.write_bytes(canonical_bytes(c));changed=json.loads(candidate.read_text());changed['binding_payload']['binding_rows'][0]['split']='heldout';candidate.write_bytes(canonical_bytes(changed))
  with self.assertRaisesRegex(ValueError,'reproduce'): import_signed_candidate(candidate,self.ext/'candidate.sig',self.ext/'binding.sig',maps,cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root)
  candidate.write_bytes(canonical_bytes(c));(self.root/'data/review/market-claim-gold.jsonl').write_bytes(b'')
  original_fsync = __import__('os').fsync
  calls = {'count': 0}
  def fail_gold_fsync(fd):
   calls['count'] += 1
   if calls['count'] == 2: raise OSError('fault')
   return original_fsync(fd)
  with patch('tools.market_review.finalization.os.fsync',side_effect=fail_gold_fsync):
   with self.assertRaises(OSError): import_signed_candidate(candidate,self.ext/'candidate.sig',self.ext/'binding.sig',maps,cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root)
  self.assertEqual((self.root/'data/review/market-claim-gold.jsonl').read_bytes(),b'');self.assertFalse((self.root/'data/review/market-keyed-finalization-receipt.json').exists())
 def test_exact_receipt_resumes_prefix_but_foreign_prefix_is_rejected(self):
  cp,ledger,a,b,adj,ca,csha,ra,rsha,maps,cust=self.fixture();v=verify_finalization(cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root);c=build_candidate_bundle(v,maps,json.loads(cp.read_text()),self.root);candidate=self.ext/'candidate.json';candidate.write_bytes(canonical_bytes(c));self.sign(cust,FINALIZATION_NAMESPACE,self.ext/'candidate.sig',c);self.sign(cust,BINDING_NAMESPACE,self.ext/'binding.sig',c['binding_payload'])
  claims=self.root/'data/review/market-claim-gold.jsonl';claims.write_bytes(b'');receipt=import_signed_candidate(candidate,self.ext/'candidate.sig',self.ext/'binding.sig',maps,cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root);complete=claims.read_bytes();claims.write_bytes(complete[:127])
  self.assertEqual(receipt,import_signed_candidate(candidate,self.ext/'candidate.sig',self.ext/'binding.sig',maps,cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root));self.assertEqual(claims.read_bytes(),complete)
  (self.root/'data/review/market-keyed-finalization-receipt.json').unlink();claims.write_bytes(b'foreign-prefix')
  with self.assertRaisesRegex(ValueError,'must not overwrite'): import_signed_candidate(candidate,self.ext/'candidate.sig',self.ext/'binding.sig',maps,cp,ledger,a,b,adj,ca,csha,ra,rsha,self.root)
  self.assertEqual(claims.read_bytes(),b'foreign-prefix')

if __name__=='__main__': unittest.main()
