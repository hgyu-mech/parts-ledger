import base64
import copy
import json
import os
import random
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from http.server import ThreadingHTTPServer
from fixtures import DEMO_BOM, DEMO_RECEIPT
from ledger import LedgerError, LedgerStore, invoice_payload, new_state, read_csv, split_cents, totals
from model import PartsClassifier
from paypal_adapter import FixturePayPal, NoRedirect, PayPalError, PayPalSandbox, SANDBOX_BASE, configured_adapter, safe_error_detail, safe_payment_url
from server import make_handler


def reviewed_project(store, sid):
    state = store.get(sid)
    for pid, category, owners, excluded, reason in [
        ('L08','fastener',{'alex':1,'mina':1,'jules':1},True,'Repeated purchase row; original receipt has one screw pack.'),
        ('L02','drive',{'alex':1},False,'Two installed belts and one spare; approved for the motion build.'),
        ('L07','consumables',{'alex':1,'mina':1,'jules':1},False,'Shared bench-cleaning supplies used by all three builders.'),
    ]:
        state = store.mutate(sid,'review',{'revision':state['revision'],'item_id':pid,'category':category,'weights':owners,'excluded':excluded,'reason':reason})
    return store.mutate(sid,'approve_clear',{'revision':state['revision']})


class MoneyAndParsingTests(unittest.TestCase):
    def test_cent_conservation_for_1500_distinct_splits(self):
        rng=random.Random(17)
        for _ in range(1500):
            amount=rng.randrange(0,10_000_000)
            weights={str(i):rng.randrange(1,1001) for i in range(rng.randrange(1,8))}
            result=split_cents(amount,weights)
            self.assertEqual(sum(result.values()),amount)
            self.assertTrue(all(x>=0 for x in result.values()))

    def test_odd_cent_tie_break_is_reproducible(self):
        self.assertEqual(split_cents(280,{'mina':1,'alex':1,'jules':1}),{'mina':93,'alex':94,'jules':93})
        self.assertEqual(split_cents(1,{'z':1,'a':1}),{'z':0,'a':1})

    def test_invalid_weights_and_non_integer_amounts_rejected(self):
        for total,weights in [(1,{}),(1,{'a':0}),(1,{'a':True}),(1,{'a':1.5}),(-1,{'a':1}),(1.1,{'a':1})]:
            with self.assertRaises(LedgerError): split_cents(total,weights)

    def test_amounts_are_preserved_not_model_generated(self):
        rows=read_csv(DEMO_RECEIPT)
        self.assertEqual(rows[0]['amount_cents'],3694)
        self.assertEqual(sum(x['amount_cents'] for x in rows),11295)

    def test_precision_negative_nan_and_zero_inputs_rejected(self):
        for price in ['0.001','-4.10','NaN','Infinity','0','2e3']:
            with self.assertRaises(LedgerError):read_csv('description,quantity,unit_price\npart,1,'+price)

    def test_csv_missing_header_or_description_rejected(self):
        for text in ['name,price\nMotor,2','description,quantity,unit_price\n,1,2.00','description,quantity,unit_price\nMotor,0,2.00']:
            with self.assertRaises(LedgerError):read_csv(text)

    def test_quoted_commas_are_parsed_without_shifting_money(self):
        row=read_csv('description,quantity,unit_price\n"Bolt, stainless",4,0.13')[0]
        self.assertEqual(row['description'],'Bolt, stainless')
        self.assertEqual(row['amount_cents'],52)

    def test_multiline_descriptions_rejected_to_preserve_source_row_links(self):
        with self.assertRaises(LedgerError):read_csv('description,quantity,unit_price\n"two\nlines",1,1.00')


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=PartsClassifier()

    def test_model_fits_original_dataset_and_scores_separate_holdout(self):
        info=self.model.information()
        self.assertEqual(info['training_examples'],100)
        self.assertEqual(info['holdout_examples'],20)
        self.assertGreaterEqual(info['holdout_correct'],17)
        train={s for rows in self.model.dataset['training'].values() for s in rows}
        self.assertTrue(all(x['description'] not in train for x in self.model.dataset['holdout']))

    def test_novel_ambiguous_description_is_not_auto_approved(self):
        result=self.model.predict('Bench tidy kit')
        self.assertTrue(result['needs_review'])
        self.assertLess(result['confidence'],.72)

    def test_unseen_description_has_no_invented_evidence(self):
        result=self.model.predict('qzxv blorpy')
        self.assertTrue(result['needs_review'])
        self.assertEqual(result['evidence_terms'],[])
        self.assertEqual(result['coverage'],0)

    def test_training_labels_change_learned_prediction(self):
        dataset=copy.deepcopy(self.model.dataset)
        dataset['training']['electronics'].append('qzxv blorpy electronics')
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'training.json';p.write_text(json.dumps(dataset),encoding='utf-8')
            learned=PartsClassifier(p).predict('qzxv blorpy')
            self.assertEqual(learned['category'],'electronics')
            self.assertNotEqual(learned['evidence_terms'],[])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=LedgerStore(Path(self.temp.name),PartsClassifier(),FixturePayPal())
        self.sid='a'*32

    def test_unreviewed_items_block_invoice_creation(self):
        state=self.store.get(self.sid)
        with self.assertRaises(LedgerError):self.store.mutate(self.sid,'create_invoices',{'revision':state['revision'],'confirmed':True})
        self.assertEqual(self.store.get(self.sid)['invoices'],[])

    def test_clear_confirmation_never_accepts_flags(self):
        state=self.store.get(self.sid)
        state=self.store.mutate(self.sid,'approve_clear',{'revision':state['revision']})
        self.assertEqual(state['totals']['pending'],4)
        self.assertTrue(all(not x['reviewed'] for x in state['items'] if x['flags']))

    def test_duplicate_exclusion_updates_bom_counts_and_retains_source(self):
        state=self.store.get(self.sid);original=state['sources']['receipt']
        state=self.store.mutate(self.sid,'review',{'revision':state['revision'],'item_id':'L08','excluded':True,'reason':'Repeated row from the same screw-pack purchase.'})
        self.assertEqual(state['totals']['billable_cents'],11015)
        self.assertEqual(state['sources']['receipt'],original)
        self.assertEqual(next(x for x in state['items'] if x['id']=='L03')['flags'],[])
        self.assertTrue(state['audit'][-1]['detail']['after']['excluded'])

    def test_manual_category_correction_preserves_original_model_and_reason(self):
        state=reviewed_project(self.store,self.sid)
        item=next(x for x in state['items'] if x['id']=='L07')
        self.assertEqual(item['category'],'consumables')
        self.assertEqual(item['model']['category'],'electronics')
        self.assertIn('Shared bench',item['reason'])

    def test_invoice_amounts_conserve_reviewed_receipt_exactly(self):
        state=reviewed_project(self.store,self.sid)
        self.assertTrue(state['totals']['ready'])
        amounts={x['member']['id']:x['amount_cents'] for x in state['totals']['members']}
        self.assertEqual(amounts,{'alex':5258,'mina':3269,'jules':2488})
        self.assertEqual(sum(amounts.values()),11015)
        for share in state['totals']['members']:
            payload=invoice_payload(state,share)
            self.assertLessEqual(len(payload['detail']['invoice_number']),25)
            self.assertNotIn('L08',json.dumps(payload))
            cents=sum(round(float(x['unit_amount']['value'])*100) for x in payload['items'])
            self.assertEqual(cents,share['amount_cents'])

    def test_explicit_invoice_confirmation_is_required(self):
        state=reviewed_project(self.store,self.sid)
        with self.assertRaises(LedgerError):self.store.mutate(self.sid,'create_invoices',{'revision':state['revision']})

    def test_draft_is_not_sent_or_paid_automatically(self):
        state=reviewed_project(self.store,self.sid)
        state=self.store.mutate(self.sid,'create_invoices',{'revision':state['revision'],'confirmed':True})
        self.assertTrue(all(i['status']=='DRAFT' and i['mode']=='fixture' for i in state['invoices']))
        with self.assertRaises(LedgerError):self.store.mutate(self.sid,'simulate_payment',{'revision':state['revision'],'invoice_id':'alex'})
        with self.assertRaises(LedgerError):self.store.mutate(self.sid,'send_invoice',{'revision':state['revision'],'invoice_id':'alex'})

    def test_fixture_issue_payment_and_audit_are_explicit(self):
        state=reviewed_project(self.store,self.sid)
        state=self.store.mutate(self.sid,'create_invoices',{'revision':state['revision'],'confirmed':True})
        state=self.store.mutate(self.sid,'send_invoice',{'revision':state['revision'],'invoice_id':'alex','confirmed':True})
        self.assertEqual(state['invoices'][0]['status'],'SENT')
        state=self.store.mutate(self.sid,'simulate_payment',{'revision':state['revision'],'invoice_id':'alex'})
        self.assertEqual(state['invoices'][0]['status'],'PAID')
        self.assertEqual(state['audit'][-1]['detail']['source'],'offline simulation')

    def test_created_invoices_lock_costs_and_member_details(self):
        state=reviewed_project(self.store,self.sid)
        state=self.store.mutate(self.sid,'create_invoices',{'revision':state['revision'],'confirmed':True})
        for action in ['import','review','members','approve_clear']:
            with self.assertRaises(LedgerError):self.store.mutate(self.sid,action,{'revision':state['revision']})

    def test_old_revision_cannot_overwrite_newer_decisions(self):
        old=self.store.get(self.sid)
        self.store.mutate(self.sid,'approve_clear',{'revision':old['revision']})
        with self.assertRaises(LedgerError) as exc:self.store.mutate(self.sid,'reset',{'revision':old['revision']})
        self.assertEqual(exc.exception.status,409)

    def test_session_paths_reject_traversal_and_workspaces_are_isolated(self):
        with self.assertRaises(LedgerError):self.store.get('../private')
        a=self.store.get(self.sid);b=self.store.get('b'*32)
        self.assertNotEqual(a['project_id'],b['project_id'])

    def test_reset_archives_old_project_without_cancelling_invoices(self):
        state=reviewed_project(self.store,self.sid)
        pid=state['project_id']
        fresh=self.store.mutate(self.sid,'reset',{'revision':state['revision']})
        old=json.loads((Path(self.temp.name)/'archive'/(pid+'.json')).read_text())
        self.assertEqual(old['project_id'],pid)
        self.assertNotEqual(fresh['project_id'],pid)
        self.assertEqual(old['totals']['billable_cents'] if 'totals' in old else totals(old)['billable_cents'],11015)

    def test_failed_creation_keeps_request_id_and_retry_does_not_duplicate_successes(self):
        class FailOnce(FixturePayPal):
            def __init__(self):self.calls=[];self.failed=False
            def create(self,payload,rid):
                self.calls.append(rid)
                if not self.failed:self.failed=True;raise PayPalError('Simulated response loss')
                return super().create(payload,rid)
        adapter=FailOnce();self.store.adapter=adapter
        state=reviewed_project(self.store,self.sid)
        state=self.store.mutate(self.sid,'create_invoices',{'revision':state['revision'],'confirmed':True})
        request_id=state['invoices'][0]['request_id']
        self.assertIsNone(state['invoices'][0]['provider_id'])
        state=self.store.mutate(self.sid,'create_invoices',{'revision':state['revision'],'confirmed':True})
        self.assertTrue(all(x['provider_id'] for x in state['invoices']))
        self.assertEqual(adapter.calls.count(request_id),2)
        self.assertEqual(len(adapter.calls),4)

    def test_sandbox_missing_credentials_never_silently_uses_fixture(self):
        self.store.adapter=PayPalSandbox()
        state=reviewed_project(self.store,self.sid)
        with self.assertRaises(LedgerError):self.store.mutate(self.sid,'create_invoices',{'revision':state['revision'],'confirmed':True})
        self.assertEqual(self.store.get(self.sid)['invoices'],[])


class SafeErrorDetailTests(unittest.TestCase):
    def test_error_diagnostic_removes_addresses_tokens_and_sensitive_values(self):
        token = 'synthetic-token-placeholder-0123456789abcdef'
        field_token = 'synthetic-field-token-0123456789abcdef'
        diagnostic = safe_error_detail({
            'message': 'Request rejected for person@example.test token ' + token,
            'details': [
                {'field': 'other@example.test', 'issue': 'lowercase-not-a-protocol-code',
                 'value': 'sensitive-value-placeholder', 'description': 'sensitive-description-placeholder'},
                {'field': field_token},
            ],
        })
        for private_value in ('person@example.test', 'other@example.test', token, field_token,
                              'sensitive-value-placeholder', 'sensitive-description-placeholder',
                              'lowercase-not-a-protocol-code'):
            self.assertNotIn(private_value, diagnostic)
        self.assertEqual(diagnostic.count('[address omitted]'), 2)
        self.assertEqual(diagnostic.count('[token omitted]'), 2)
        self.assertIn('Request rejected', diagnostic)
        self.assertLessEqual(len(diagnostic), 300)

    def test_korean_merchant_payer_restriction_keeps_protocol_code_and_field(self):
        issue = 'KOREAN_MERCHANT_KOREAN_PAYER_RESTRICTED'
        diagnostic = safe_error_detail({
            'message': 'The requested media type is not acceptable.',
            'details': [{'field': 'invoiceId', 'issue': issue,
                         'value': 'private-invoice-value-placeholder'}],
        })
        self.assertIn('invoiceId', diagnostic)
        self.assertIn(issue, diagnostic)
        self.assertNotIn('[token omitted]', diagnostic)
        self.assertNotIn('private-invoice-value-placeholder', diagnostic)


class SandboxAdapterTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        def transport(method,path,body,headers):
            self.calls.append((method,path,body,headers))
            if path=='/v1/oauth2/token':return {'access_token':'test-token-placeholder','expires_in':3600}
            if path.endswith('/send'):return {}
            return {'id':'INV2-TEST-TEST-TEST-TEST','status':'DRAFT' if method=='POST' else 'PAID','detail':{'metadata':{'recipient_view_url':'https://www.sandbox.paypal.com/invoice/p/test'}}}
        self.adapter=PayPalSandbox('test-client-placeholder','not-a-real-secret','sb-test@business.example.com',transport)
        state=new_state(PartsClassifier());share=totals(state)['members'][0]
        share['member']['email']='sb-buyer@personal.example.com';self.payload=invoice_payload(state,share)

    def test_oauth_headers_and_server_only_token_for_invoice_post(self):
        result=self.adapter.create(self.payload,'test-idempotency-id')
        self.assertEqual(self.calls[0][:2],('POST','/v1/oauth2/token'))
        self.assertTrue(self.calls[0][3]['Authorization'].startswith('Basic '))
        self.assertEqual(self.calls[1][1],'/v2/invoicing/invoices')
        self.assertEqual(self.calls[1][3]['Authorization'],'Bearer test-token-placeholder')
        self.assertEqual(self.calls[1][3]['PayPal-Request-Id'],'test-idempotency-id')
        self.assertEqual(self.calls[1][3]['Prefer'],'return=representation')
        self.assertNotIn('secret',json.dumps(result))
        self.assertEqual(result['mode'],'sandbox')

    def test_token_cache_and_get_status_are_real_adapter_protocol(self):
        created=self.adapter.create(self.payload,'same-id')
        refreshed=self.adapter.get(created['provider_id'])
        self.assertEqual(refreshed['status'],'PAID')
        self.assertEqual(sum(path=='/v1/oauth2/token' for _,path,_,_ in self.calls),1)
        self.assertNotIn('Prefer',self.calls[-1][3])

    def test_send_uses_json_without_create_prefer_and_keeps_followup_get_status(self):
        invoice_id='INV2-TEST-TEST-TEST-TEST'
        def send_protocol(method,path,body,headers):
            self.calls.append((method,path,body,headers))
            if path=='/v1/oauth2/token':return {'access_token':'test-token-placeholder','expires_in':3600}
            if path.endswith('/send'):
                self.assertEqual(method,'POST')
                self.assertEqual(headers['Authorization'],'Bearer test-token-placeholder')
                self.assertEqual(headers['Content-Type'],'application/json')
                self.assertEqual(headers['Accept'],'application/json')
                self.assertNotIn('Prefer',headers)
                self.assertEqual(json.loads(body),{'send_to_recipient':True,'send_to_invoicer':False})
                return {}
            self.assertEqual((method,path),('GET','/v2/invoicing/invoices/'+invoice_id))
            self.assertNotIn('Prefer',headers)
            self.assertEqual(headers['Accept'],'application/json')
            return {'id':invoice_id,'status':'UNPAID'}
        self.adapter._transport=send_protocol
        result=self.adapter.send(invoice_id,'stable-send-request-id')
        self.assertEqual([method for method,_,_,_ in self.calls],['POST','POST','GET'])
        self.assertEqual(self.calls[1][1],'/v2/invoicing/invoices/'+invoice_id+'/send')
        self.assertEqual(result['status'],'UNPAID')
        self.assertNotEqual(result['status'],'PAID')

    def test_normal_personal_email_is_blocked_before_network_call(self):
        self.payload['primary_recipients'][0]['billing_info']['email_address']='person@example.test'
        with self.assertRaises(PayPalError):self.adapter.create(self.payload,'id')
        self.assertEqual(self.calls,[])

    def test_no_live_mode_or_live_payment_links(self):
        with patch.dict(os.environ,{'PAYPAL_MODE':'live'}):
            with self.assertRaises(ValueError):configured_adapter()
        self.assertEqual(SANDBOX_BASE,'https://api-m.sandbox.paypal.com')
        self.assertIsNone(safe_payment_url('https://www.paypal.com/invoice/p/test'))
        self.assertIsNone(safe_payment_url('javascript:alert(1)'))
        self.assertIsNone(safe_payment_url('https://someone@sandbox.paypal.com/invoice/p/test'))
        self.assertIsNone(safe_payment_url('https://sandbox.paypal.com:8443/invoice/p/test'))
        self.assertIsNone(safe_payment_url('https://sandbox.paypal.com:bad/invoice/p/test'))
        self.assertEqual(safe_payment_url('https://www.sandbox.paypal.com/invoice/p/test'), 'https://www.sandbox.paypal.com/invoice/p/test')

    def test_redirect_cannot_forward_credentials_to_another_host(self):
        request=urllib.request.Request(SANDBOX_BASE+'/v1/oauth2/token')
        with self.assertRaises(urllib.error.HTTPError):NoRedirect().redirect_request(request,None,302,'Moved',{},'https://api-m.paypal.com')

    def test_missing_provider_id_never_fabricates_a_draft(self):
        self.adapter._transport=lambda method,path,body,headers: {'access_token':'test-token','expires_in':3600} if path.endswith('/token') else {}
        with self.assertRaises(PayPalError):self.adapter.create(self.payload,'id')

    def test_lost_create_response_reconciles_exact_matching_invoice(self):
        amount=sum(float(x['unit_amount']['value']) for x in self.payload['items'])
        def lost(method,path,body,headers):
            if path.endswith('/token'):return {'access_token':'test-token','expires_in':3600}
            if path=='/v2/invoicing/invoices':raise PayPalError('response lost')
            return {'items':[{'id':'INV2-TEST-TEST-TEST-TEST','status':'DRAFT','detail':self.payload['detail'],'amount':{'currency_code':'USD','value':f'{amount:.2f}'},'primary_recipients':self.payload['primary_recipients']}]}
        self.adapter._transport=lost
        result=self.adapter.create(self.payload,'same-id')
        self.assertEqual(result['provider_id'],'INV2-TEST-TEST-TEST-TEST')


class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        store=LedgerStore(Path(self.temp.name),PartsClassifier(),FixturePayPal())
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(store))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.base=f'http://127.0.0.1:{self.server.server_port}';self.sid='e'*32

    def test_server_serves_functional_app_and_no_secrets(self):
        with urllib.request.urlopen(self.base+'/') as response:self.assertIn(b'Parts Ledger',response.read())
        request=urllib.request.Request(self.base+'/api/state',headers={'X-Ledger-Session':self.sid})
        with urllib.request.urlopen(request) as response:state=json.load(response)
        self.assertEqual(state['connection']['mode'],'fixture')
        self.assertNotIn('client_secret',json.dumps(state))
        self.assertEqual(state['totals']['pending'],8)

    def test_cross_origin_change_is_rejected(self):
        request=urllib.request.Request(self.base+'/api/action/reset',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://unrelated.example.test','X-Ledger-Session':self.sid},method='POST')
        with self.assertRaises(urllib.error.HTTPError) as exc:urllib.request.urlopen(request)
        self.assertEqual(exc.exception.code,403)

    def test_env_data_and_path_traversal_are_not_served(self):
        for path in ['/.env','/.data/ledger.json','/../server.py']:
            with self.assertRaises(urllib.error.HTTPError) as exc:urllib.request.urlopen(self.base+path)
            self.assertEqual(exc.exception.code,404)


if __name__=='__main__':unittest.main()
