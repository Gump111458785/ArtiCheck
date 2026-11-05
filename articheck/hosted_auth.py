"""Username/password accounts with durable Redis records and opaque cookie sessions.

Accounts identify reports; they do not bypass the separately budgeted review access code.
No passwords, raw session tokens, model keys or uploaded materials enter responses.
"""
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid

from .review_api import ReviewError, now

COOKIE = 'articheck_session'
SESSION_TTL = 30 * 86400
ITERATIONS = 600_000


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return {'salt':salt, 'digest':hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()}


class Accounts:
    def __init__(self, app, env, store):
        self.env, self.store = env, store
        self.prefix = 'articheck:accounts:' + env.get('ARTICHECK_BUDGET_ID','') + ':'
        self.register(app)

    def key(self, kind, value):
        return self.prefix + kind + ':' + hashlib.sha256(value.encode()).hexdigest()

    def read(self, kind, value):
        raw = self.store.command('GET',self.key(kind,value))
        return json.loads(raw) if raw else None

    def write(self, kind, value, record, ttl=None):
        args = ['SET',self.key(kind,value),json.dumps(record,ensure_ascii=False)]
        if ttl:args += ['EX',str(ttl)]
        self.store.command(*args)

    def guard(self):
        from flask import request
        origin = request.headers.get('Origin')
        expected = (self.env.get('ARTICHECK_PUBLIC_ORIGIN') or request.host_url).rstrip('/')
        if request.headers.get('X-ArtiCheck-Client')!='review-api' or origin and origin.rstrip('/')!=expected:
            raise ReviewError('origin_forbidden','请从本站操作账户。',403)

    def limit(self, kind, subject, cap, seconds):
        script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"
        used = self.store.command('EVAL',script,'1',self.key('rate-'+kind,subject),str(seconds))
        if type(used) is not int or used>cap:
            raise ReviewError('auth_rate_limited','尝试次数较多，请稍后重试。',429)

    def current(self):
        from flask import request
        token = request.cookies.get(COOKIE,'')
        if not token:return None
        if not re.fullmatch(r'[a-f0-9]{64}',token):return None
        session = self.read('session',token)
        if not session or session.get('expires_at',0)<=time.time():return None
        user = self.read('user',session['user_id'])
        if not user or user.get('epoch')!=session.get('epoch'):return None
        return user

    def owner(self):
        user = self.current()
        if not user:return None
        # A shared website access code is not a private account secret. Every
        # account gets a random report capability stored only on the server.
        owner=user.get('report_owner','')
        if not re.fullmatch(r'[a-f0-9]{64}',owner):
            raise ReviewError('account_upgrade_required','账户记录需要升级，请联系管理员。',503)
        return owner

    @staticmethod
    def public(user):
        return {key:user[key] for key in ('id','username','name','created_at')}

    def session_response(self, user):
        from flask import jsonify
        token = secrets.token_hex(32)
        self.write('session',token,{'user_id':user['id'],'epoch':user['epoch'],'expires_at':time.time()+SESSION_TTL},SESSION_TTL)
        response = jsonify(user=self.public(user))
        self.cookie(response,token,SESSION_TTL)
        return response

    def cookie(self, response, token, max_age):
        from urllib.parse import urlparse
        # HTTP is permitted only for the explicitly configured loopback preview.
        origin = urlparse(self.env.get('ARTICHECK_PUBLIC_ORIGIN',''))
        local = origin.scheme=='http' and origin.hostname in {'127.0.0.1','localhost','::1'}
        response.set_cookie(COOKIE,token,max_age=max_age,httponly=True,secure=not local,samesite='Strict',path='/')
        response.headers['Cache-Control']='no-store'

    @staticmethod
    def fields():
        from flask import request
        body = request.get_json(silent=True)
        if not isinstance(body,dict):raise ReviewError('invalid_request','请提交有效的账户信息。')
        return body

    @staticmethod
    def username(value):
        if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9_]{3,32}',value):
            raise ReviewError('invalid_username','用户名需为 3–32 位字母、数字或下划线。')
        return value.lower()

    @staticmethod
    def password(value):
        if not isinstance(value,str) or not 12<=len(value)<=128:
            raise ReviewError('invalid_password','密码需为 12–128 个字符。')
        return value

    @staticmethod
    def name(value):
        if not isinstance(value,str) or not 1<=len(value.strip())<=40 or any(ord(c)<32 for c in value):
            raise ReviewError('invalid_name','显示名称需为 1–40 个字符。')
        return value.strip()

    def require(self):
        self.guard()
        user = self.current()
        if not user:raise ReviewError('login_required','请先登录账户。',401)
        return user

    def register(self, app):
        from flask import jsonify,request

        @app.get('/auth/me')
        def account_me():
            self.guard()
            user = self.current()
            response = jsonify(user=self.public(user) if user else None)
            response.headers['Cache-Control']='no-store'
            return response

        @app.post('/auth/register')
        def account_register():
            self.guard();body=self.fields()
            username=self.username(body.get('username'));password=self.password(body.get('password'));name=self.name(body.get('name'))
            self.limit('register',request.remote_addr or 'unknown',5,3600)
            user={'id':uuid.uuid4().hex,'username':username,'name':name,'created_at':now(),
                  'epoch':uuid.uuid4().hex,'password':password_hash(password),
                  'report_owner':secrets.token_hex(32)}
            # The unique name and account record are created together, without a race.
            script="if redis.call('EXISTS',KEYS[1])==1 then return 0 end; redis.call('SET',KEYS[1],ARGV[1]); redis.call('SET',KEYS[2],ARGV[2]); return 1"
            created=self.store.command('EVAL',script,'2',self.key('username',username),self.key('user',user['id']),user['id'],json.dumps(user,ensure_ascii=False))
            if created!=1:raise ReviewError('username_taken','该用户名已被使用，请换一个。',409)
            return self.session_response(user),201

        @app.post('/auth/login')
        def account_login():
            self.guard();body=self.fields()
            username=self.username(body.get('username'));password=self.password(body.get('password'))
            self.limit('login-ip',request.remote_addr or 'unknown',30,900)
            self.limit('login-name',username,10,900)
            user_id=self.store.command('GET',self.key('username',username))
            user=self.read('user',user_id) if user_id else None
            # An unknown username takes the same password work as a known username.
            expected=user['password'] if user else {'salt':'0'*32,'digest':'0'*64}
            actual=password_hash(password,expected['salt'])
            if not hmac.compare_digest(actual['digest'],expected['digest']):
                raise ReviewError('invalid_credentials','用户名或密码不正确。',401)
            return self.session_response(user)

        @app.post('/auth/logout')
        def account_logout():
            self.guard();token=request.cookies.get(COOKIE,'')
            if re.fullmatch(r'[a-f0-9]{64}',token):self.store.command('DEL',self.key('session',token))
            response=jsonify(user=None);self.cookie(response,'',0)
            return response

        @app.post('/auth/profile')
        def account_profile():
            user=self.require();name=self.name(self.fields().get('name'))
            # Updating a name must never restore a password from a concurrent stale read.
            script="local raw=redis.call('GET',KEYS[1]); if not raw then return false end; local u=cjson.decode(raw); u.name=ARGV[1]; local updated=cjson.encode(u); redis.call('SET',KEYS[1],updated); return updated"
            updated=self.store.command('EVAL',script,'1',self.key('user',user['id']),name)
            if not updated:raise ReviewError('login_required','账户已变更，请重新登录。',401)
            return jsonify(user=self.public(json.loads(updated)))

        @app.post('/auth/password')
        def account_password():
            user=self.require();body=self.fields()
            self.limit('password',user['id'],10,900)
            old=self.password(body.get('current_password'));new=self.password(body.get('new_password'))
            if not hmac.compare_digest(password_hash(old,user['password']['salt'])['digest'],user['password']['digest']):
                raise ReviewError('invalid_credentials','当前密码不正确。',401)
            old_epoch=user['epoch']
            user['password']=password_hash(new);user['epoch']=uuid.uuid4().hex
            script="local raw=redis.call('GET',KEYS[1]); if not raw then return 0 end; local u=cjson.decode(raw); if u.epoch~=ARGV[1] then return 0 end; u.password=cjson.decode(ARGV[2]); u.epoch=ARGV[3]; redis.call('SET',KEYS[1],cjson.encode(u)); return 1"
            if self.store.command('EVAL',script,'1',self.key('user',user['id']),old_epoch,json.dumps(user['password']),user['epoch'])!=1:
                raise ReviewError('login_required','账户状态已变化，请重新登录后操作。',401)
            # Rotate the session; the epoch invalidates every previous login.
            return self.session_response(user)
