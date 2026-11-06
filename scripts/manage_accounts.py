"""Operator-side invitation provisioning; Redis credentials come from the environment."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from flask import Flask
from articheck.hosted_auth import Accounts,password_hash
from articheck.hosted_store import HostedStore
import uuid

def main():
    p=argparse.ArgumentParser(description='管理 ArtiCheck 受邀账户，不提供公开注册')
    p.add_argument('action',choices=['create','list','reset','disable','enable'])
    p.add_argument('--username');p.add_argument('--name');p.add_argument('--role',choices=['admin','user'],default='user')
    p.add_argument('--password-file',type=Path)
    a=p.parse_args();accounts=Accounts(Flask('operator'),os.environ,HostedStore(os.environ))
    if a.action=='list':
        users=[accounts.read('user',uid) for uid in accounts.store.command('SMEMBERS',accounts.prefix+'users') or []]
        print(json.dumps([{**accounts.public(u),'disabled':bool(u.get('disabled'))} for u in users if u],ensure_ascii=False,indent=2));return
    username=accounts.username(a.username)
    if a.action in {'create','reset'}:
        if a.password_file:
            if a.password_file.stat().st_mode&0o077:p.error('密码文件必须仅当前用户可读（权限 600）')
            password=accounts.password(a.password_file.read_text().strip())
        else:password=accounts.password(getpass.getpass('密码（不回显）：'))
    if a.action=='create':
        user=accounts.create_user(username,password,a.name or username,role=a.role)
    else:
        uid=accounts.store.command('GET',accounts.key('username',username));user=accounts.read('user',uid) if uid else None
        if not user:p.error('账户不存在')
        update={'epoch':uuid.uuid4().hex}
        if a.action=='reset':update['password']=password_hash(password)
        else:update.update(invited=True,disabled=a.action=='disable')
        script="local u=cjson.decode(redis.call('GET',KEYS[1])); local p=cjson.decode(ARGV[1]); for k,v in pairs(p) do u[k]=v end; redis.call('SET',KEYS[1],cjson.encode(u)); return 1"
        accounts.store.command('EVAL',script,'1',accounts.key('user',user['id']),json.dumps(update))
        user.update(update)
    print(json.dumps(accounts.public(user),ensure_ascii=False))
if __name__=='__main__':main()
