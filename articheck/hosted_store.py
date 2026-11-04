"""Small durable reports and atomic launch locks, scoped to browser capabilities.

Raw PDF/ZIP bytes are never stored in Redis. Reports expire after seven days.
"""
import hashlib
import json
import re
import urllib.request

from .review_api import ReviewError

TTL = 7 * 86400


class HostedStore:
    def __init__(self, env):
        self.url = env.get('UPSTASH_REDIS_REST_URL', '').rstrip('/')
        self.token = env.get('UPSTASH_REDIS_REST_TOKEN', '')
        self.namespace = env.get('ARTICHECK_BUDGET_ID', '')

    def command(self, *args):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError('Redirect disabled')
        request = urllib.request.Request(self.url, data=json.dumps(list(args)).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=8) as response:
                value = json.loads(response.read(1_000_001))
            if 'error' in value or 'result' not in value:
                raise ValueError('Redis error')
            return value['result']
        except Exception as exc:
            raise ReviewError('storage_unavailable', '任务存储暂不可用，请稍后重试。未启动新的执行。', 503) from exc

    def key(self, owner, job):
        if not re.fullmatch(r'[a-f0-9]{32}', job):
            raise ReviewError('not_found', '未找到该审查记录。', 404)
        if not re.fullmatch(r'[a-f0-9]{64}', owner or ''):
            raise ReviewError('invalid_session', '当前浏览器身份无效，请刷新页面。', 401)
        return 'articheck:online:' + self.namespace + ':' + hashlib.sha256(owner.encode()).hexdigest() + ':' + job

    def get(self, owner, job):
        value = self.command('GET', self.key(owner, job))
        if value is None:
            raise ReviewError('not_found', '记录不存在、已过期，或不属于当前浏览器。', 404)
        return json.loads(value)

    def save(self, owner, value):
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded.encode()) > 500_000:
            raise ReviewError('report_size', '审查报告超出保存上限。', 413)
        self.command('SET', self.key(owner, value['id']), encoded, 'EX', TTL)

    def claim(self, owner, value):
        return self.command('SET', self.key(owner, value['id']), json.dumps(value, ensure_ascii=False), 'NX', 'EX', TTL) == 'OK'

    def replace(self, owner, previous, value):
        # A late poll must never overwrite a cancellation or newer result.
        script="if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end; redis.call('SET',KEYS[1],ARGV[2],'EX',ARGV[3]); return 1"
        return self.command('EVAL', script, '1', self.key(owner, value['id']),
                            json.dumps(previous, ensure_ascii=False), json.dumps(value, ensure_ascii=False), str(TTL)) == 1

    def lock(self, owner, job, attempt=1):
        # The record itself contains the authoritative state. A permanent-in-TTL
        # launch latch prevents a timed-out request from creating a second VM.
        return self.command('SET', self.key(owner, job) + ':launch:'+str(attempt), '1', 'NX', 'EX', TTL) == 'OK'

    def unlock_before_launch(self, owner, job, attempt=1):
        self.command('DEL', self.key(owner, job) + ':launch:'+str(attempt))

    def reserve_compute(self):
        script = "local n=tonumber(redis.call('GET',KEYS[1]) or '0'); if n>=20 then return -1 end; return redis.call('INCR',KEYS[1])"
        result = self.command('EVAL', script, '1', 'articheck:compute-budget:' + self.namespace)
        if type(result) is not int or not 1 <= result <= 20:
            raise ReviewError('compute_budget_exhausted', '本轮云端执行额度已用完，仍可查看和导出已有报告。', 429)
        return result

    def repository_ref(self, name, value=None):
        key='articheck:github-ref:'+self.namespace+':'+hashlib.sha256(name.encode()).hexdigest()
        if value is None:
            raw=self.command('GET',key)
            return json.loads(raw) if raw else None
        # Only public commit metadata, never the source archive.
        self.command('SET',key,json.dumps(value),'EX','1800')
