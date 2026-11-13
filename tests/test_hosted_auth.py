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
        if op=='SADD':
            self.redis.setdefault(args[1],set()).add(args[2]);return 1
        if op=='SMEMBERS':return list(self.redis.get(args[1],set()))
        if op=='DEL':return int(self.redis.pop(args[1],None) is not None)
        if op=='EVAL':
            script,n=args[1],int(args[2]);keys=args[3:3+n];values=args[3+n:]
            if "redis.call('INCR'" in script:
                count=int(self.command('GET',keys[0]) or 0)+1;self.redis[keys[0]]=str(count)
                if count==1:self.expiry[keys[0]]=time.time()+int(values[0])
                return count
            if 'u.name=ARGV[1]' in script:
                user=json.loads(self.redis[keys[0]]);user['name']=values[0]
                if len(values)>2 and values[1]=='set':user['avatar']=values[2]
                if len(values)>2 and values[1]=='clear':user.pop('avatar',None)
                self.redis[keys[0]]=json.dumps(user);return self.redis[keys[0]]
            if 'u.epoch~=ARGV[1]' in script:
                user=json.loads(self.redis[keys[0]])
                if user['epoch']!=values[0]:return 0
                user.update(password=json.loads(values[1]),epoch=values[2]);self.redis[keys[0]]=json.dumps(user);return 1
            if 'for k,v in pairs(p)' in script:
                user=json.loads(self.redis[keys[0]]);user.update(json.loads(values[0]));self.redis[keys[0]]=json.dumps(user);return self.redis[keys[0]] if 'return updated' in script else 1
            if n==3:
                if self.command('GET',keys[0]):return 0
                self.redis[keys[0]],self.redis[keys[1]]=values;self.command('SADD',keys[2],values[0]);return 1
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
        self.accounts=self.app.extensions['articheck_accounts']
        self.headers={'X-ArtiCheck-Client':'review-api','Origin':'https://articheck.example'}
        self.data={'username':'researcher','name':'研究者','password':'correct-password-long'}
    def post(self,path,data=None,client=None,headers=None):return (client or self.client).post('/auth/'+path,json=data or {},headers=headers or self.headers)
    def invite(self,data=None,client=None,role='user'):
        d=data or self.data;self.accounts.create_user(d['username'],d['password'],d['name'],role=role)
        return self.post('login',d,client=client)
    def test_invited_login_profile_logout_and_opaque_cookie(self):
        r=self.invite();self.assertEqual(r.status_code,200)
        self.assertEqual(set(r.json['user']),{'id','username','name','created_at','role'})
        cookie=r.headers['Set-Cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('Secure',cookie);self.assertIn('SameSite=Strict',cookie)
        self.assertNotIn(self.data['password'],str(self.store.redis));self.assertNotIn('report_owner',str(r.json))
        self.assertEqual(self.post('profile',{'name':'新名称'}).json['user']['name'],'新名称')
        self.post('logout');self.assertIsNone(self.client.get('/auth/me',headers=self.headers).json['user'])
        self.assertEqual(self.post('login',self.data).status_code,200)

    def test_only_authenticated_admin_bypasses_model_quota(self):
        @self.app.get('/test-model-budget')
        def model_budget():
            self.app.extensions['articheck_authorize']()
            return jsonify(attempt=self.app.extensions['articheck_reserve_model']())

        self.assertEqual(self.client.get('/test-model-budget', headers=self.headers).status_code, 401)
        self.invite()
        self.assertEqual(self.client.get('/test-model-budget', headers=self.headers).json['attempt'], 1)
        admin = self.app.test_client()
        self.invite({**self.data, 'username': 'operator'}, client=admin, role='admin')
        self.assertIsNone(admin.get('/test-model-budget', headers=self.headers).json['attempt'])

    def test_admin_can_create_upload_and_launch_after_compute_quota_is_exhausted(self):
        self.invite(role='admin')
        job = 'd' * 32
        with patch.object(self.store, 'reserve_compute', side_effect=ReviewError('compute_budget_exhausted', 'full', 429)) as reserve:
            with patch('articheck.hosted_api.HostedUploads.create', return_value={'id': job}) as create:
                self.assertEqual(self.client.post('/uploads', json={}, headers=self.headers).status_code, 200)
                self.assertTrue(create.call_args.kwargs['unlimited'])
            report = self.client.post('/assessments', json={**materials(), 'request_id': job}, headers=self.headers)
            self.assertEqual(report.status_code, 200)
            plan = report.json['review']['plan_sha256']
            result = self.client.post('/assessments/'+job+'/execute',
                json={'code': materials()['code'], 'plan_sha256': plan}, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['execution']['status'], 'running')
            reserve.assert_not_called()
    def test_avatar_accepts_presets_and_small_inline_images_only(self):
        self.invite()
        self.assertEqual(self.post('profile',{'name':'甲','avatar':'preset:atom'}).json['user']['avatar'],'preset:atom')
        # Name-only updates keep the avatar; an empty string clears it.
        self.assertEqual(self.post('profile',{'name':'乙'}).json['user']['avatar'],'preset:atom')
        img='data:image/png;base64,'+'A'*400
        self.assertEqual(self.post('profile',{'name':'乙','avatar':img}).json['user']['avatar'],img)
        for bad in ['https://evil.example/a.png','data:image/svg+xml;base64,PHN2Zz4=','data:image/png;base64,'+'A'*230000]:
            self.assertEqual(self.post('profile',{'name':'乙','avatar':bad}).status_code,400)
        self.assertNotIn('avatar',self.post('profile',{'name':'乙','avatar':''}).json['user'])
    def test_public_signup_is_closed_and_access_code_does_not_replace_login(self):
        self.assertEqual(self.post('register',self.data).status_code,403);self.assertEqual(self.store.redis,{})
        for path in ['/capabilities','/assessments/'+'a'*32]:self.assertEqual(self.client.get(path,headers=HEADERS).status_code,401)
        self.assertEqual(self.client.post('/repositories',json={'url':'https://github.com/a/b'},headers=HEADERS).status_code,401)
        self.assertEqual(self.client.post('/assessments',json={},headers=HEADERS).status_code,401)
    def test_unknown_and_wrong_password_have_generic_error(self):
        self.invite()
        for change in [{'password':'wrong-password-long'},{'username':'unknown_name'}]:
            self.assertEqual(self.post('login',{**self.data,**change}).json['error']['code'],'invalid_credentials')
    def test_origin_guard_and_operator_validation(self):
        self.assertEqual(self.post('login',self.data,headers={'X-ArtiCheck-Client':'review-api','Origin':'https://evil.example'}).status_code,403)
        with self.assertRaises(ReviewError):self.accounts.create_user('bad<name>','correct-password-long','Name')
        with self.assertRaises(ReviewError):self.accounts.create_user('valid_name','short','Name')
        self.assertEqual(self.store.redis,{})
    def test_login_rate_limit(self):
        for _ in range(10):self.post('login',{**self.data,'password':'wrong-password-long'})
        self.assertEqual(self.post('login',self.data).status_code,429)
    def test_admin_provisions_resets_and_disables_members(self):
        self.invite(role='admin')
        member={**self.data,'username':'invited_member'}
        created=self.post('admin/users',member);self.assertEqual(created.status_code,201);uid=created.json['user']['id']
        other=self.app.test_client();self.assertEqual(self.post('login',member,client=other).status_code,200)
        self.assertEqual(self.post('admin/users',member,client=other).status_code,403)
        self.assertEqual(self.post('password',{'current_password':member['password'],'new_password':'not-allowed-password'},client=other).status_code,403)
        self.assertEqual(self.post('admin/users/'+uid,{'action':'disable'}).status_code,200)
        self.assertIsNone(other.get('/auth/me',headers=self.headers).json['user'])
        self.assertEqual(self.post('login',member,client=other).status_code,401)
        self.post('admin/users/'+uid,{'action':'enable'})
        self.post('admin/users/'+uid,{'action':'reset_password','password':'replacement-password-123'})
        self.assertEqual(self.post('login',member,client=other).status_code,401)
        self.assertEqual(self.post('login',{**member,'password':'replacement-password-123'},client=other).status_code,200)
        listed=self.client.get('/auth/admin/users',headers=self.headers);self.assertEqual(len(listed.json['users']),2)
        self.assertNotIn('report_owner',str(listed.json));self.assertNotIn('salt',str(listed.json))
    def test_admin_password_change_invalidates_other_sessions(self):
        self.invite(role='admin');second=self.app.test_client();self.post('login',self.data,client=second)
        r=self.post('password',{'current_password':self.data['password'],'new_password':'new-password-long-enough'});self.assertEqual(r.status_code,200)
        self.assertIsNone(second.get('/auth/me',headers=self.headers).json['user'])
        self.assertIsNotNone(self.client.get('/auth/me',headers=self.headers).json['user'])
    def test_account_owner_isolated_and_cookie_alone_authorizes_review(self):
        job='b'*32;self.store.save(OWNER,{'id':job,'status':'completed'})
        self.invite();self.assertEqual(self.client.get('/assessments/'+job,headers=self.headers).status_code,404)
        with patch('articheck.hosted_api.prepare_assessment',side_effect=prepare_assessment):
            r=self.client.post('/assessments',json={'code':materials()['code'],'request_id':'c'*32},headers=self.headers)
        self.assertEqual(r.status_code,200)
        other=self.app.test_client();self.invite({**self.data,'username':'other_user'},client=other)
        self.assertEqual(other.get('/assessments/'+r.json['id'],headers=self.headers).status_code,404)
        self.assertEqual(self.client.get('/assessments/'+r.json['id'],headers=self.headers).status_code,200)
        self.assertEqual(self.app.test_client().get('/assessments/'+r.json['id'],headers=HEADERS).status_code,401)
    def test_old_public_accounts_are_not_automatically_invited(self):
        user=self.accounts.create_user('old_user',self.data['password'],'Old');user.pop('invited');self.accounts.write('user',user['id'],user)
        self.assertEqual(self.post('login',{**self.data,'username':'old_user'}).status_code,401)


class ComputeCapacityTests(unittest.TestCase):
    def test_model_receives_configured_capacity_and_capabilities_match(self):
        class FourGExecutor(Executor):
            capacity={'provider':'e2b','cpu_count':2,'memory_mb':4096,'gpu':False}
        class CapacityReviewer(Reviewer):
            def post(inner,body):
                content=body['messages'][1]['content'];context=json.loads(content[0]['text'] if isinstance(content,list) else content)['materials']
                self.assertEqual(context['execution_environment']['memory_mb'],4096)
                return super(CapacityReviewer,inner).post(body)
        app=Flask('capacity');register(app,{'ARTICHECK_REVIEW_TOKEN':TOKEN,'ARTICHECK_AUTH_MODE':'legacy'},CapacityReviewer(),Budget(),store=MemoryStore(),executor=FourGExecutor())
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
        register(app,{'ARTICHECK_REVIEW_TOKEN':TOKEN,'ARTICHECK_AUTH_MODE':'legacy'},BlockedReviewer(),Budget(),store=store,executor=executor)
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
