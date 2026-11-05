import copy,json,time,unittest
from flask import Flask,jsonify
from articheck.hosted_api import register
from articheck.hosted_auth import Accounts,COOKIE,password_hash
from articheck.review_api import ReviewError
from test_hosted_review import MemoryStore,Reviewer,Budget,Executor,TOKEN,HEADERS,OWNER,materials,prepare_assessment
from unittest.mock import patch

class RedisMemory(MemoryStore):
    def __init__(self):super().__init__();self.redis={};self.expiry={}
    def command(self,*args):
        op=args[0]
        if op=='GET':
            key=args[1]
            return None if self.expiry.get(key,float('inf'))<=time.time() else self.redis.get(key)
        if op=='SET':
            self.redis[args[1]]=args[2]
            if 'EX' in args:self.expiry[args[1]]=time.time()+int(args[args.index('EX')+1])
            return 'OK'
        if op=='DEL':return int(self.redis.pop(args[1],None) is not None)
        if op=='EVAL':
            script,n=args[1],int(args[2]);keys=args[3:3+n];values=args[3+n:]
            if "redis.call('INCR'" in script:
                count=int(self.command('GET',keys[0]) or 0)+1;self.redis[keys[0]]=str(count)
                if count==1:self.expiry[keys[0]]=time.time()+int(values[0])
                return count
            if 'u.name=ARGV[1]' in script:
                user=json.loads(self.redis[keys[0]]);user['name']=values[0];self.redis[keys[0]]=json.dumps(user);return self.redis[keys[0]]
            if 'u.epoch~=ARGV[1]' in script:
                user=json.loads(self.redis[keys[0]])
                if user['epoch']!=values[0]:return 0
                user.update(password=json.loads(values[1]),epoch=values[2]);self.redis[keys[0]]=json.dumps(user);return 1
            if n==2:
                if self.command('GET',keys[0]):return 0
                self.redis[keys[0]],self.redis[keys[1]]=values;return 1
        raise AssertionError('Unexpected Redis operation')

class HostedAccountsTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__);self.store=RedisMemory()
        @self.app.errorhandler(ReviewError)
        def error(exc):return jsonify(error={'code':exc.code,'message':str(exc)}),exc.status
        self.env={'ARTICHECK_REVIEW_TOKEN':TOKEN,'ARTICHECK_PUBLIC_ORIGIN':'https://articheck.example','ARTICHECK_BUDGET_ID':'test-only-namespace'}
        register(self.app,self.env,Reviewer(),Budget(),store=self.store,executor=Executor());self.client=self.app.test_client()
        self.headers={'X-ArtiCheck-Client':'review-api','Origin':'https://articheck.example'}
        self.data={'username':'researcher','name':'研究者','password':'correct-password-long'}
    def post(self,path,data=None,client=None,headers=None):return (client or self.client).post('/auth/'+path,json=data or {},headers=headers or self.headers)
    def test_register_login_profile_logout_and_opaque_cookie(self):
        r=self.post('register',self.data);self.assertEqual(r.status_code,201)
        self.assertEqual(set(r.json['user']),{'id','username','name','created_at'})
        cookie=r.headers['Set-Cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('Secure',cookie);self.assertIn('SameSite=Strict',cookie)
        self.assertNotIn(self.data['password'],str(self.store.redis));self.assertNotIn(COOKIE,str(r.json))
        self.assertEqual(self.post('profile',{'name':'新名称'}).json['user']['name'],'新名称')
        self.post('logout');self.assertIsNone(self.client.get('/auth/me',headers=self.headers).json['user'])
        self.assertEqual(self.post('login',self.data).status_code,200)
    def test_duplicate_name_and_generic_invalid_credentials(self):
        self.post('register',self.data)
        self.assertEqual(self.post('register',{**self.data,'username':'RESEARCHER'}).status_code,409)
        self.assertEqual(self.post('login',{**self.data,'password':'wrong-password-long'}).json['error']['code'],'invalid_credentials')
        self.assertEqual(self.post('login',{**self.data,'username':'unknown_name'}).json['error']['code'],'invalid_credentials')
    def test_origin_guard_and_field_validation_precede_storage(self):
        self.assertEqual(self.post('register',self.data,headers={'X-ArtiCheck-Client':'review-api','Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.post('register',{**self.data,'password':'short'}).status_code,400)
        self.assertEqual(self.post('register',{**self.data,'username':'x<script>'}).status_code,400)
        self.assertEqual(self.store.redis,{})
    def test_login_rate_limit(self):
        for _ in range(10):self.post('login',{**self.data,'password':'wrong-password-long'})
        self.assertEqual(self.post('login',self.data).status_code,429)
    def test_password_change_invalidates_other_sessions(self):
        self.post('register',self.data);second=self.app.test_client();self.post('login',self.data,client=second)
        r=self.post('password',{'current_password':self.data['password'],'new_password':'new-password-long-enough'});self.assertEqual(r.status_code,200)
        self.assertIsNone(second.get('/auth/me',headers=self.headers).json['user'])
        self.assertIsNotNone(self.client.get('/auth/me',headers=self.headers).json['user'])
    def test_account_owner_cannot_read_anonymous_or_other_accounts_report(self):
        job='b'*32;self.store.save(OWNER,{'id':job,'status':'completed'})
        self.post('register',self.data)
        self.assertEqual(self.client.get('/assessments/'+job,headers=HEADERS).status_code,404)
        with patch('articheck.hosted_api.prepare_assessment',side_effect=prepare_assessment):
            r=self.client.post('/assessments',json={'code':materials()['code'],'request_id':'c'*32},headers=HEADERS)
        self.assertEqual(r.status_code,200)
        other=self.app.test_client();self.post('register',{**self.data,'username':'other_user'},client=other)
        self.assertEqual(other.get('/assessments/'+r.json['id'],headers=HEADERS).status_code,404)
        self.post('logout');self.post('login',self.data)
        self.assertEqual(self.client.get('/assessments/'+r.json['id'],headers=HEADERS).status_code,200)
        self.assertEqual(self.client.get('/assessments/'+r.json['id'],headers=self.headers).status_code,401)
        import hashlib,hmac
        public_guess=hmac.new(TOKEN.encode(),('account:'+self.client.get('/auth/me',headers=self.headers).json['user']['id']).encode(),hashlib.sha256).hexdigest()
        anonymous=self.app.test_client()
        self.assertEqual(anonymous.get('/assessments/'+r.json['id'],headers={**HEADERS,'X-ArtiCheck-Session':public_guess}).status_code,404)
    def test_progress_is_visible_during_model_request_and_persisted_after_completion(self):
        class SlowReviewer(Reviewer):
            def post(inner,body):
                record=self.store.get(OWNER,'d'*32)
                self.assertEqual(record['status'],'reviewing');self.assertEqual(record['activity'][-1]['status'],'running')
                self.assertIn('planner',record['activity'][-1]['roles'])
                return super(SlowReviewer,inner).post(body)
        app=Flask('activity');register(app,self.env,SlowReviewer(),Budget(),store=self.store,executor=Executor())
        with patch('articheck.hosted_api.prepare_assessment',side_effect=prepare_assessment):
            r=app.test_client().post('/assessments',json={'code':materials()['code'],'request_id':'d'*32},headers=HEADERS)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json['activity'][-1]['roles'],['reporter'])
        self.assertFalse(any(x['status']=='running' for x in r.json['activity']))


class ComputeCapacityTests(unittest.TestCase):
    def test_model_receives_configured_capacity_and_capabilities_match(self):
        class FourGExecutor(Executor):
            capacity={'provider':'e2b','cpu_count':2,'memory_mb':4096,'gpu':False}
        class CapacityReviewer(Reviewer):
            def post(inner,body):
                content=body['messages'][1]['content'];context=json.loads(content[0]['text'] if isinstance(content,list) else content)['materials']
                self.assertEqual(context['execution_environment']['memory_mb'],4096)
                return super(CapacityReviewer,inner).post(body)
        app=Flask('capacity');register(app,{'ARTICHECK_REVIEW_TOKEN':TOKEN},CapacityReviewer(),Budget(),store=MemoryStore(),executor=FourGExecutor())
        client=app.test_client()
        self.assertEqual(client.get('/capabilities').json['compute']['capacity']['memory_mb'],4096)
        self.assertEqual(client.get('/capabilities').json['compute']['gpu']['status'],'not_configured')
        with patch('articheck.hosted_api.prepare_assessment',side_effect=prepare_assessment):
            response=client.post('/assessments',json={'code':materials()['code']},headers=HEADERS)
        self.assertEqual(response.status_code,200)

    def test_template_with_insufficient_actual_memory_is_stopped_before_code_upload(self):
        from articheck.hosted_sandbox import E2BExecutor
        from unittest.mock import MagicMock
        context,_=prepare_assessment({'code':materials()['code']})
        sandbox=MagicMock();sandbox.get_info.return_value.memory_mb=512
        executor=E2BExecutor({'E2B_API_KEY':'test','ARTICHECK_E2B_TEMPLATE':'four-gib','ARTICHECK_CPU_MEMORY_MB':'4096'})
        assessment={'id':'a'*32,'materials':{'code':context['code']['sha256']},'review':{'plan':{'max_seconds':30},'metrics':[]}}
        with patch('e2b.Sandbox.create',return_value=sandbox) as create:
            with self.assertRaises(ReviewError) as caught:executor.launch(assessment,{'code':materials()['code']})
        self.assertEqual(caught.exception.code,'compute_capacity_changed');sandbox.kill.assert_called_once();sandbox.files.write.assert_not_called()
        self.assertEqual(create.call_args.kwargs['template'],'four-gib')


class ResourceDecisionTests(unittest.TestCase):
    def test_resource_answers_are_saved_without_creating_an_execution_or_scientific_pass(self):
        from test_hosted_review import output
        class BlockedReviewer(Reviewer):
            def post(inner,body):
                content=body['messages'][1]['content'];context=json.loads(content[0]['text'] if isinstance(content,list) else content)['materials']
                value=output(context);value['plan'].update(stages=[],blocked_reason='Requires CUDA GPU',needs=[{'name':'CUDA GPU','source':'README','required':True}])
                return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}
        app=Flask('resource-choice');store=MemoryStore();executor=Executor()
        @app.errorhandler(ReviewError)
        def error(exc):return jsonify(error={'code':exc.code,'message':str(exc)}),exc.status
        register(app,{'ARTICHECK_REVIEW_TOKEN':TOKEN},BlockedReviewer(),Budget(),store=store,executor=executor)
        client=app.test_client()
        for answer in ['can_provide','unavailable']:
            with patch('articheck.hosted_api.prepare_assessment',side_effect=prepare_assessment):
                r=client.post('/assessments',json={'code':materials()['code']},headers=HEADERS)
            self.assertEqual(r.status_code,200);self.assertTrue(r.json['review']['resource_preflight']['needs_user'])
            result=client.post('/assessments/'+r.json['id']+'/feedback',json={'answer':answer},headers=HEADERS)
            self.assertEqual(result.status_code,200);self.assertEqual(result.json['availability']['answer'],answer)
            self.assertFalse(result.json['scientific_validation']);self.assertIsNone(result.json['execution'])
        self.assertEqual(executor.launches,0);self.assertEqual(store.reservations,0)

if __name__=='__main__':unittest.main()
