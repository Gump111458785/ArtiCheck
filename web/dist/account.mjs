import {passwordButton,bindPasswordToggles} from './ui-icons.mjs';

export const PRESET_AVATARS={
 'preset:atom':{label:'原子科研',bg:'linear-gradient(135deg,#2563eb,#06b6d4)',svg:'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="2.2"/><ellipse cx="12" cy="12" rx="9" ry="3.8" transform="rotate(30 12 12)"/><ellipse cx="12" cy="12" rx="9" ry="3.8" transform="rotate(-30 12 12)"/></svg>'},
 'preset:flask':{label:'实验探索',bg:'linear-gradient(135deg,#7c3aed,#ec4899)',svg:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3h6M10 3v5.5L5 18a2 2 0 0 0 1.7 3h10.6A2 2 0 0 0 19 18l-5-9.5V3M7.5 14h9"/></svg>'},
 'preset:chip':{label:'算力芯片',bg:'linear-gradient(135deg,#0f172a,#3b82f6)',svg:'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/></svg>'},
 'preset:leaf':{label:'常青学者',bg:'linear-gradient(135deg,#059669,#34d399)',svg:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 3c3 0 4 2 4 5 0 6-5 11-11 11-2 0-4-1-5-2 1-6 6-14 12-14zM5 19l8-8"/></svg>'},
 'preset:orbit':{label:'星轨洞察',bg:'linear-gradient(135deg,#d97706,#f59e0b)',svg:'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="5"/><path d="M3 12c2.5-4 15.5-4 18 0-2.5 4-15.5 4-18 0z"/><circle cx="18.5" cy="9" r="1.5"/></svg>'},
 'preset:book':{label:'文献典藏',bg:'linear-gradient(135deg,#dc2626,#fb7185)',svg:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19v16H6.5a2.5 2.5 0 0 0-2.5 2.5z"/><path d="M6.5 17H19M8 7h7M8 11h5"/></svg>'}
};

function compressAvatarImage(file){
 return new Promise((resolve,reject)=>{
  if(!/^image\/(png|jpeg|webp)$/i.test(file.type||'')){reject(Error('请选择 PNG、JPG 或 WebP 格式的图片。'));return;}
  if(file.size>8*1024*1024){reject(Error('图片不能超过 8 MB。'));return;}
  const reader=new FileReader();
  reader.onerror=()=>reject(Error('读取图片失败。'));
  reader.onload=()=>{
   const dataUrl=String(reader.result||'');
   if(typeof Image==='undefined'||typeof document==='undefined'){
    if(dataUrl.length>220000){reject(Error('图片体积过大，请选择更小的图片。'));return;}
    resolve(dataUrl);return;
   }
   const img=new Image();
   img.onerror=()=>reject(Error('图片格式无法解析。'));
   img.onload=()=>{
    try{
     const size=160,canvas=document.createElement('canvas');
     canvas.width=size;canvas.height=size;
     const ctx=canvas.getContext('2d');
     const scale=Math.max(size/img.width,size/img.height);
     const w=img.width*scale,h=img.height*scale;
     ctx.fillStyle='#ffffff';ctx.fillRect(0,0,size,size);
     ctx.drawImage(img,(size-w)/2,(size-h)/2,w,h);
     let out=canvas.toDataURL('image/jpeg',0.85);
     if(!out.startsWith('data:image/'))out=dataUrl;
     if(out.length>220000){reject(Error('压缩后图片仍过大，请更换图片。'));return;}
     resolve(out);
    }catch{
     if(dataUrl.length<=220000)resolve(dataUrl);
     else reject(Error('无法处理该图片。'));
    }
   };
   img.src=dataUrl;
  };
  reader.readAsDataURL(file);
 });
}

export class AccountWorkspace{
 constructor(h){this.h=h;this.user=null;this.menu=false;this.available=false;this.busy=false;this.editingName=false;this.users=[];}
 async request(path,body){const r=await fetch('/v1/auth/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',redirect:'error',headers:{'X-ArtiCheck-Client':'review-api',...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(15000)});let v;try{v=await r.json();}catch{throw Error('账户服务暂不可用，请稍后重试。');}if(!r.ok)throw Error(v.error?.message||'账户操作未完成。');return v;}
 async init(identity=null){try{this.user=identity||(await this.request('me')).user;this.available=true;}catch{}this.bind();}
 afterRender(){if(this.user?.role==='admin'&&document.querySelector('.account-management')&&!this.usersLoaded&&!this.usersPending){this.usersPending=true;this.loadUsers().then(()=>this.h.render()).catch(e=>this.h.toast(e.message)).finally(()=>{this.usersPending=false;});}}
 async loadUsers(){this.users=(await this.request('admin/users')).users;this.usersLoaded=true;}
 avatarNode(u,cls=''){
  const e=this.h.esc,av=u?.avatar||'';
  if(PRESET_AVATARS[av]){
   const p=PRESET_AVATARS[av];
   return `<span class="account-avatar preset ${cls}" style="background:${p.bg}" title="${e(p.label)}">${p.svg}</span>`;
  }
  if(/^data:image\/(png|jpeg|webp);base64,/i.test(av)){
   return `<span class="account-avatar has-img ${cls}"><img src="${e(av)}" alt="${e(u.name||'头像')}"></span>`;
  }
  const initial=[...(u?.name||'?')][0]?.toUpperCase()||'?';
  return `<span class="account-avatar ${cls}">${e(initial)}</span>`;
 }
 openAvatarModal(){
  if(!this.user)return;
  const e=this.h.esc,cur=this.user.avatar||'';
  this.h.modal('更换账户头像',`<div class="avatar-picker-modal"><div class="avatar-picker-current">${this.avatarNode(this.user,'large')}<div><strong>${e(this.user.name)}</strong><p>可选择预设科研图标，或上传本地图片（自动裁剪为方形头像）。</p></div></div><div class="avatar-preset-grid" role="group" aria-label="预设头像">${Object.entries(PRESET_AVATARS).map(([id,p])=>`<button type="button" class="avatar-preset-option ${cur===id?'selected':''}" data-account-avatar="${id}"><span class="account-avatar preset" style="background:${p.bg}">${p.svg}</span><span>${e(p.label)}</span></button>`).join('')}</div><div class="avatar-picker-actions"><label class="btn primary" for="account-avatar-upload">上传本地图片<input id="account-avatar-upload" type="file" accept="image/png,image/jpeg,image/webp" data-account-avatar-file hidden></label><button type="button" class="btn" data-account-avatar="" ${!cur?'disabled':''}>恢复默认字母头像</button></div><p class="account-result" data-avatar-status role="status"></p></div>`);
 }
 async saveAvatar(avatar){
  if(this.busy||!this.user)return;
  this.busy=true;
  const statusNode=document.querySelector('[data-avatar-status]');
  if(statusNode){statusNode.textContent='正在保存头像…';statusNode.classList.remove('failed');}
  try{
   this.user=(await this.request('profile',{name:this.user.name,avatar})).user;
   this.h.closeModal?.();
   this.h.toast('头像已更新');
   this.h.render();
  }catch(e){
   if(statusNode){statusNode.textContent=e.message;statusNode.classList.add('failed');}
   else this.h.toast(e.message);
  }finally{this.busy=false;}
 }
 topbar(){const e=this.h.esc;if(!this.user)return '<a class="btn account-login" href="./login.html">登录</a>';return `<div class="account-control"><button class="account-trigger" data-account="menu" aria-haspopup="menu" aria-expanded="${this.menu}" aria-label="${e(this.user.name)}的账户菜单">${this.avatarNode(this.user)}<span>${e(this.user.name)}</span>${this.h.icon('down')}</button>${this.menu?`<div class="account-menu" role="menu"><div><strong>${e(this.user.name)}</strong><small>@${e(this.user.username)}${this.user.role==='admin'?' · 管理员':''}</small></div><button role="menuitem" data-account="center">${this.h.icon('settings')}个人中心</button>${this.user.role==='admin'?'<button role="menuitem" data-account="admin">账户管理</button>':''}<button role="menuitem" data-account="new">${this.h.icon('plus')}新建审查</button><button role="menuitem" data-account="logout">${this.h.icon('logout')}退出登录</button></div>`:''}</div>`;}
 open(){location.assign('./login.html');}
 projects(){return this.h.projects().filter(p=>(p.online_account||null)===(this.user?.id||null));}
 center(){const e=this.h.esc,u=this.user;if(!u)return '<section class="online-empty"><h2>请先登录工作空间</h2><a class="btn primary" href="./login.html">登录</a></section>';const projects=this.projects(),reports=projects.filter(p=>p.online_report?.review),executed=reports.filter(p=>p.online_report?.execution?.execution_performed);
 return `<div class="account-center"><section class="account-overview"><div class="account-avatar-box"><button type="button" class="account-avatar-trigger" data-account="avatar" title="点击更换头像" aria-label="更换头像">${this.avatarNode(u,'large')}<span class="account-avatar-edit">更换头像</span></button></div><div class="account-overview-main">${this.editingName?`<form data-account-form="profile" class="account-inline-name-form"><input id="inline-profile-name" name="name" value="${e(u.name)}" maxlength="40" placeholder="输入自定义名称" aria-label="自定义名称" required><button class="btn primary small" type="submit">保存</button><button class="btn small" type="button" data-account="cancel-edit-name">取消</button><p role="status" class="account-result"></p></form>`:`<div class="account-name-row"><h2>${e(u.name)}</h2><button type="button" class="btn small account-edit-name-btn" data-account="edit-name">修改名字</button></div>`}<p>@${e(u.username)} · ${u.role==='admin'?'管理员':'受邀用户'}</p></div><button class="btn" data-account="new">${this.h.icon('plus')}新建审查</button></section><div class="account-counts"><div><span>当前浏览器项目</span><strong>${projects.length}</strong></div><div><span>已有审查报告</span><strong>${reports.length}</strong></div><div><span>包含实际执行</span><strong>${executed.length}</strong></div></div><div class="account-settings"><div class="account-card"><div class="account-card-head"><h2>个人资料</h2><p>显示名称用于头像与研究工作空间。</p></div><form data-account-form="profile"><label for="profile-name">显示名称</label><input id="profile-name" name="name" value="${e(u.name)}" maxlength="40" required><label>用户名</label><p class="account-readonly">@${e(u.username)}</p><p role="status" class="account-result"></p><button class="btn" type="submit">保存资料</button></form></div><div class="account-card"><div class="account-card-head"><h2>账户访问</h2><p>邀请制账户由管理员创建与维护。</p></div><div class="account-access-note"><strong>仅受邀用户可登录</strong><p>如需重置密码或更改访问权限，请联系管理员。所有审查支持持续运行至完成并可随时手动中断。</p></div></div></div>${u.role==='admin'?this.management():''}<section class="account-projects"><div class="online-section-heading"><h2>最近审查</h2><span>当前浏览器 · ${projects.length} 项</span></div>${projects.slice(0,6).map(p=>`<button data-account-project="${e(p.id)}"><span><strong>${e(p.title||'未命名审查')}</strong><small>${p.online_report?.review?'已有报告':p.online_pending_request?'审查处理中':'材料准备中'}</small></span>${this.h.icon('chevron')}</button>`).join('')||'<p class="online-notice">还没有项目，从新建审查开始。</p>'}<p class="online-footnote">材料和项目列表保存在当前浏览器，不自动跨设备同步；服务器报告保留 7 天。</p></section></div>`;
 }
 management(){const e=this.h.esc;return `<section id="account-management" class="account-management"><div class="online-section-heading"><h2>邀请与账户管理</h2><button class="btn" data-account="refresh-users">刷新账户</button></div><p>由管理员设置用户名和密码，再自行分发给指定用户。网站不开放注册。</p><form data-account-form="invite" class="invite-form"><div><label for="invite-username">用户名</label><input id="invite-username" name="username" pattern="[a-zA-Z0-9_]{3,32}" minlength="3" maxlength="32" required></div><div><label for="invite-name">显示名称</label><input id="invite-name" name="name" maxlength="40" required></div><div><label for="invite-password">初始密码</label><div class="account-password"><input id="invite-password" name="password" type="password" minlength="12" maxlength="128" autocomplete="new-password" required>${passwordButton('invite-password')}</div><small>12–128 个字符</small></div><p role="alert" class="account-result"></p><button class="btn primary" type="submit">创建受邀账户</button></form><div class="online-table-wrap"><table class="online-table"><thead><tr><th>用户</th><th>权限</th><th>状态</th><th>管理</th></tr></thead><tbody>${this.users.map(u=>`<tr><td><strong>${e(u.name)}</strong><span>@${e(u.username)}</span></td><td>${u.role==='admin'?'管理员':'受邀用户'}</td><td><span class="online-status ${u.disabled?'missing':'documented'}">${u.disabled?'已停用':'可登录'}</span></td><td class="account-row-actions"><button class="btn" data-account="reset-user" data-user="${e(u.id)}">重置密码</button>${u.id===this.user.id?'':`<button class="btn" data-account="toggle-user" data-user="${e(u.id)}">${u.disabled?'启用':'停用'}</button>`}</td></tr>`).join('')}</tbody></table></div></section>`;}
 async changed(user){this.user=user;this.menu=false;await this.h.changed?.();this.h.render();}
 bind(){bindPasswordToggles();
 document.addEventListener('click',async event=>{const avBtn=event.target.closest('[data-account-avatar]');if(avBtn){await this.saveAvatar(avBtn.dataset.accountAvatar);return;}const t=event.target.closest('[data-account]');if(!t){if(this.menu&&!event.target.closest('.account-control')){this.menu=false;this.h.render();}const p=event.target.closest('[data-account-project]');if(p)this.h.openProject(p.dataset.accountProject);return;}const a=t.dataset.account;
 if(this.h.canSwitch?.()===false&&['logout','new'].includes(a)){this.h.toast('请等待当前操作结束。');return;}
 try{
 if(a==='avatar'){this.openAvatarModal();return;}
 if(a==='edit-name'){this.editingName=true;this.h.render();document.querySelector('#inline-profile-name')?.focus();document.querySelector('#inline-profile-name')?.select?.();return;}
 if(a==='cancel-edit-name'){this.editingName=false;this.h.render();return;}
 if(a==='menu'){this.menu=!this.menu;this.h.render();if(this.menu)document.querySelector('.account-menu button')?.focus();}
 if(a==='center'||a==='admin'){this.menu=false;this.h.navigate('account');if(a==='admin')document.querySelector('#account-management')?.scrollIntoView({block:'start'});}
 if(a==='new'){this.menu=false;await this.h.newReview();}
 if(a==='logout'){t.disabled=true;await this.request('logout',{});location.replace('./login.html');}
 if(a==='refresh-users'){await this.loadUsers();this.h.render();}
 if(a==='reset-user'||a==='toggle-user'){
  const u=this.users.find(x=>x.id===t.dataset.user);if(!u)return;const e=this.h.esc;
  this.h.modal(a==='reset-user'?'重置账户密码':'更改账户状态',`<form data-account-form="manage" data-user="${e(u.id)}"><p>账户：${e(u.name)}（@${e(u.username)}）</p><input type="hidden" name="action" value="${a==='reset-user'?'reset_password':u.disabled?'enable':'disable'}">${a==='reset-user'?`<div class="online-field"><label for="reset-user-password">新密码</label><div class="account-password"><input id="reset-user-password" name="password" type="password" minlength="12" maxlength="128" autocomplete="new-password" required>${passwordButton('reset-user-password')}</div><small>12–128 个字符；保存后原登录会话失效。</small></div>`:'<p>确认后立即更新此账户的登录权限，已有材料和报告保留。</p>'}<p class="account-result" role="alert"></p><button class="btn primary" type="submit">确认${a==='reset-user'?'重置密码':u.disabled?'启用':'停用'}</button></form>`);
 }
 }catch(e){this.h.toast(e.message);t.disabled=false;}});
 document.addEventListener('change',async event=>{const f=event.target;if(!f.matches?.('[data-account-avatar-file]')||!f.files?.[0])return;const statusNode=document.querySelector('[data-avatar-status]');try{if(statusNode){statusNode.textContent='正在处理图片…';statusNode.classList.remove('failed');}const dataUrl=await compressAvatarImage(f.files[0]);await this.saveAvatar(dataUrl);}catch(e){if(statusNode){statusNode.textContent=e.message;statusNode.classList.add('failed');}else this.h.toast(e.message);}finally{f.value='';}});
 document.addEventListener('keydown',e=>{if(this.menu&&e.key==='Escape'){this.menu=false;this.h.render();document.querySelector('.account-trigger')?.focus();}if(this.menu&&['ArrowDown','ArrowUp'].includes(e.key)){const b=[...document.querySelectorAll('.account-menu button')],i=b.indexOf(document.activeElement);b[(i+(e.key==='ArrowDown'?1:-1)+b.length)%b.length]?.focus();e.preventDefault();}});
 document.addEventListener('submit',async event=>{const f=event.target;if(!f.matches('[data-account-form]'))return;event.preventDefault();if(this.busy||!f.reportValidity())return;this.busy=true;const button=f.querySelector('[type=submit]'),error=f.querySelector('.account-result'),data=Object.fromEntries(new FormData(f));button.disabled=true;error.textContent='';try{
  if(f.dataset.accountForm==='profile'){this.user=(await this.request('profile',data)).user;this.editingName=false;this.h.toast('资料已保存');}
  if(f.dataset.accountForm==='invite'){await this.request('admin/users',data);await this.loadUsers();this.h.toast('受邀账户已创建，请将账号密码分发给指定用户。');}
  if(f.dataset.accountForm==='manage'){await this.request('admin/users/'+f.dataset.user,data);this.h.closeModal();await this.loadUsers();this.h.toast('账户已更新');}
  this.h.render();
 }catch(e){error.textContent=e.message;error.classList.add('failed');}finally{this.busy=false;button.disabled=false;}});
 }
}
