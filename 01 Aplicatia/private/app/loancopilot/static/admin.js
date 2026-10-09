'use strict';
const csrf=document.querySelector('meta[name="csrf-token"]').content;
const currentUserId=Number(document.body.dataset.userId);
const isSuperadmin=document.body.dataset.superadmin==='1';
const ui=Object.freeze({
  companyForm:document.getElementById('companyForm'),
  companyName:document.getElementById('companyName'),
  companyCui:document.getElementById('companyCui'),
  companyAnafButton:document.getElementById('companyAnafButton'),
  companyAnafPreview:document.getElementById('companyAnafPreview'),
  companySlug:document.getElementById('companySlug'),
  companyReg:document.getElementById('companyReg'),
  companyAddress:document.getElementById('companyAddress'),
  companyAdministrator:document.getElementById('companyAdministrator'),
  userForm:document.getElementById('userForm'),
  userName:document.getElementById('userName'),
  userEmail:document.getElementById('userEmail'),
  userPassword:document.getElementById('userPassword'),
  userCompany:document.getElementById('userCompany'),
  userRole:document.getElementById('userRole'),
  companiesBody:document.getElementById('companiesBody'),
  usersBody:document.getElementById('usersBody'),
  companyEditDialog:document.getElementById('companyEditDialog'),
  companyEditForm:document.getElementById('companyEditForm'),
  companyEditStorage:document.getElementById('companyEditStorage'),
  editCompanyId:document.getElementById('editCompanyId'),
  editCompanyName:document.getElementById('editCompanyName'),
  editCompanyCui:document.getElementById('editCompanyCui'),
  editCompanyAnafButton:document.getElementById('editCompanyAnafButton'),
  editCompanyAnafPreview:document.getElementById('editCompanyAnafPreview'),
  editCompanyReg:document.getElementById('editCompanyReg'),
  editCompanyAddress:document.getElementById('editCompanyAddress'),
  editCompanyAdministrator:document.getElementById('editCompanyAdministrator'),
  editCompanyActive:document.getElementById('editCompanyActive'),
  editCompanySave:document.getElementById('editCompanySave'),
  toastBox:document.getElementById('toastBox'),
});
const {companyForm, companyName, companyCui, companyAnafButton, companyAnafPreview, companySlug, companyReg, companyAddress, companyAdministrator, userForm, userName, userEmail, userPassword, userCompany, userRole, companiesBody, usersBody, companyEditDialog, companyEditForm, companyEditStorage, editCompanyId, editCompanyName, editCompanyCui, editCompanyAnafButton, editCompanyAnafPreview, editCompanyReg, editCompanyAddress, editCompanyAdministrator, editCompanyActive, editCompanySave, toastBox}=ui;

let state={};

async function api(url,opt={}){
  const method=(opt.method||'GET').toUpperCase();
  const headers={'Content-Type':'application/json',...(opt.headers||{})};
  if(method!=='GET')headers['X-CSRF-Token']=csrf;
  const r=await fetch(url,{credentials:'same-origin',headers,...opt});
  const d=await r.json();
  if(!r.ok||d.ok===false)throw new Error(d.error||'Eroare');
  return d;
}
function esc(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function formatBytes(v){const n=Number(v||0);if(!n)return '0 B';if(n<1024)return n+' B';if(n<1048576)return (n/1024).toFixed(1)+' KB';return (n/1048576).toFixed(1)+' MB'}
function toast(m,b=false){const e=document.getElementById('toastBox');e.textContent=m;e.style.background=b?'#a53f3f':'#17202a';e.classList.add('show');clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove('show'),2800)}
function slugify(v){return String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,90)}
function anafSummary(i){const flags=[i.vat_registered?'TVA':'neplătitor TVA',i.vat_on_collection?'TVA la încasare':null,i.e_invoice?'RO e-Factura':null,i.inactive?'INACTIV FISCAL':'activ fiscal'].filter(Boolean);return `${i.registration_status||'stare necomunicată'} · ${flags.join(' · ')}${i.caen_code?' · CAEN '+i.caen_code:''} · verificat ${i.queried_date}`}
async function lookupAnaf(cui,button,preview){
  const value=String(cui.value||'').trim();
  if(!value){toast('Introduceți CUI-ul înainte de interogarea ANAF.',true);cui.focus();return null}
  button.disabled=true;const old=button.textContent;button.textContent='Se verifică…';preview.textContent='Interogare ANAF v9 în curs…';
  try{const d=await api('/api/anaf/company-lookup',{method:'POST',body:JSON.stringify({cui:value})});preview.textContent=anafSummary(d.item);return d.item}
  catch(x){preview.textContent=x.message;toast(x.message,true);return null}
  finally{button.disabled=false;button.textContent=old}
}
async function lookupAnafCreate(){const i=await lookupAnaf(companyCui,companyAnafButton,companyAnafPreview);if(!i)return;companyCui.value=i.cui;if(i.name)companyName.value=i.name;if(i.reg_com)companyReg.value=i.reg_com;if(i.address)companyAddress.value=i.address;if(!companySlug.value)companySlug.value=slugify(`${i.name}-${i.cui}`);toast('Datele publice ANAF au fost preluate. Verificați și salvați compania.')}
async function lookupAnafEdit(){const i=await lookupAnaf(editCompanyCui,editCompanyAnafButton,editCompanyAnafPreview);if(!i)return;editCompanyCui.value=i.cui;if(i.name)editCompanyName.value=i.name;if(i.reg_com)editCompanyReg.value=i.reg_com;if(i.address)editCompanyAddress.value=i.address;toast('Datele publice ANAF au fost preluate. Verificați și salvați modificările.')}

async function load(){
  state=await api('/api/admin/data');
  userCompany.innerHTML=state.companies.filter(c=>c.active).map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('');
  companiesBody.innerHTML=state.companies.map(c=>`<tr>
    <td><b>${esc(c.name)}</b><div class="note">${esc(c.slug)}</div></td>
    <td><b>${esc(c.cui)}</b><div class="note">${esc(c.reg_com||'Nr. RC necompletat')}</div></td>
    <td>${esc(c.address||'Sediu necompletat')}<div class="note">Administrator: ${esc(c.administrator||'necompletat')}</div></td>
    <td>
      <div class="mono">${esc(c.db_filename)}</div>
      <div class="note">${c.db_ok?`<span class="pill ok">SQLite OK</span> · ${formatBytes(c.db_size_bytes)}`:`<span class="pill">BAZĂ LIPSĂ / INVALIDĂ</span>`}</div>
      <div class="note mono" title="${esc(c.db_path||'')}">${esc(c.documents_subdir)}</div>
      ${c.db_error?`<div class="note">${esc(c.db_error)}</div>`:''}
    </td>
    <td><span class="pill ${c.active?'ok':''}">${c.active?'ACTIVĂ':'INACTIVĂ'}</span></td>
    <td>
      <button class="btn small" type="button" onclick="openCompanyEdit(${c.id})">Editează</button>
      ${isSuperadmin&&!c.db_ok?`<button class="btn small" type="button" onclick="repairCompanyStorage(${c.id})">Creează/Repară baza</button>`:''}
    </td>
  </tr>`).join('');
  usersBody.innerHTML=state.users.map(u=>{
    const m=state.memberships.filter(x=>x.user_id===u.id).map(x=>`${esc(x.company_name)} · <b>${esc(x.role)}</b>`).join('<br>')||'—';
    return `<tr><td><b>${esc(u.display_name)}</b><div class="note">${esc(u.email)}</div></td><td>${u.totp_enabled?'activ':'inactiv'}</td><td>${esc(u.last_login_at||'—')}</td><td>${m}</td><td>${isSuperadmin?`<button class="btn small" onclick="toggleUser(${u.id},${u.active?0:1})">${u.active?'Dezactivează':'Activează'}</button>`:`<span class="pill ${u.active?'ok':''}">${u.active?'ACTIV':'INACTIV'}</span>`}</td><td>${isSuperadmin||Number(u.id)===currentUserId?`<button class="btn small" type="button" onclick="openPasswordDialog(${u.id})">${Number(u.id)===currentUserId?'Schimbă parola':'Resetează parola'}</button>`:'—'}</td></tr>`;
  }).join('');
}

function openCompanyEdit(id){
  const c=state.companies.find(item=>Number(item.id)===Number(id));
  if(!c)return;
  editCompanyId.value=String(c.id);
  editCompanyName.value=c.name||'';
  editCompanyCui.value=c.cui||'';
  editCompanyReg.value=c.reg_com||'';
  editCompanyAddress.value=c.address||'';
  editCompanyAdministrator.value=c.administrator||'';
  if(isSuperadmin)editCompanyActive.value=c.active?'1':'0';
  editCompanyAnafPreview.textContent='';
  companyEditStorage.textContent=`Bază: ${c.db_filename} · ${c.db_ok?'SQLite OK, '+formatBytes(c.db_size_bytes):'LIPSĂ / INVALIDĂ'} · documente: ${c.documents_subdir}`;
  companyEditDialog.showModal();
}

companyEditForm.addEventListener('submit',async e=>{
  e.preventDefault();
  const id=Number(editCompanyId.value);
  const body={
    name:editCompanyName.value,
    cui:editCompanyCui.value,
    reg_com:editCompanyReg.value,
    address:editCompanyAddress.value,
    administrator:editCompanyAdministrator.value
  };
  if(isSuperadmin)body.active=Number(editCompanyActive.value);
  editCompanySave.disabled=true;
  editCompanySave.textContent='Se salvează…';
  try{
    await api('/api/admin/companies/'+id,{method:'PATCH',body:JSON.stringify(body)});
    companyEditDialog.close();
    await load();
    toast('Compania a fost actualizată');
  }catch(x){toast(x.message,true)}
  finally{editCompanySave.disabled=false;editCompanySave.textContent='Salvează modificările'}
});

companyForm?.addEventListener('submit',async e=>{
  e.preventDefault();
  try{
    const d=await api('/api/admin/companies',{method:'POST',body:JSON.stringify({name:companyName.value,cui:companyCui.value,slug:companySlug.value,reg_com:companyReg.value,address:companyAddress.value,administrator:companyAdministrator.value})});
    e.target.reset();
    await load();
    toast(`Compania și baza ${d.db_filename} (${formatBytes(d.db_size_bytes)}) au fost create; șabloane: ${d.templates_copied||0}`);
  }catch(x){toast(x.message,true)}
});

userForm.addEventListener('submit',async e=>{
  e.preventDefault();
  try{
    await api('/api/admin/users',{method:'POST',body:JSON.stringify({display_name:userName.value,email:userEmail.value,password:userPassword.value,company_id:Number(userCompany.value),role:userRole.value})});
    e.target.reset();
    await load();
    toast('Utilizatorul a fost salvat');
  }catch(x){toast(x.message,true)}
});


async function repairCompanyStorage(id){
  if(!confirm('Se va crea baza SQLite dacă lipsește sau se va reface schema lipsă. Datele existente nu sunt șterse. Continui?'))return;
  try{
    const d=await api('/api/admin/companies/'+id+'/storage/repair',{method:'POST',body:'{}'});
    await load();
    toast(`${d.storage.created?'Baza SQLite a fost creată':'Schema bazei a fost verificată/reparată'} · ${formatBytes(d.storage.size_bytes)}`);
  }catch(x){toast(x.message,true)}
}

async function toggleUser(id,active){
  try{await api('/api/admin/users/'+id,{method:'PATCH',body:JSON.stringify({active})});await load();toast('Status actualizat')}
  catch(x){toast(x.message,true)}
}
load().catch(x=>toast(x.message,true));

const passwordDialog=document.getElementById('passwordDialog');
const passwordForm=document.getElementById('passwordForm');
const passwordUserId=document.getElementById('passwordUserId');
const currentPassword=document.getElementById('currentPassword');
const newPassword=document.getElementById('newPassword');
const confirmPassword=document.getElementById('confirmPassword');
const passwordError=document.getElementById('passwordError');
const passwordSave=document.getElementById('passwordSave');
function openPasswordDialog(id){
  const user=state.users.find(u=>Number(u.id)===Number(id));
  if(!user||(!isSuperadmin&&Number(id)!==currentUserId))return;
  passwordForm.reset();
  passwordUserId.value=String(id);
  const own=Number(id)===currentUserId;
  document.getElementById('passwordTitle').textContent=own?'Schimbă parola':'Resetează parola';
  document.getElementById('passwordUser').textContent=user.display_name+' · '+user.email;
  document.getElementById('currentPasswordField').hidden=!own;
  currentPassword.required=own;
  document.getElementById('passwordNote').textContent=own?'Sesiunea curentă rămâne deschisă. Celelalte sesiuni vor fi închise.':'Toate sesiunile utilizatorului vor fi închise. Utilizatorul se va autentifica folosind noua parolă.';
  passwordError.hidden=true;passwordError.textContent='';
  passwordDialog.showModal();
  (own?currentPassword:newPassword).focus();
}
passwordDialog.addEventListener('close',()=>{passwordForm.reset();passwordError.textContent='';passwordError.hidden=true});
passwordForm.addEventListener('submit',async e=>{
  e.preventDefault();
  passwordError.hidden=true;
  if(newPassword.value!==confirmPassword.value){passwordError.textContent='Confirmarea parolei nu coincide.';passwordError.hidden=false;confirmPassword.focus();return}
  const id=Number(passwordUserId.value);
  const own=id===currentUserId;
  passwordSave.disabled=true;
  try{
    await api(own?'/api/profile/password':'/api/admin/users/'+id+'/password',{method:'POST',body:JSON.stringify({current_password:currentPassword.value,new_password:newPassword.value,confirm_password:confirmPassword.value})});
    passwordDialog.close();toast(own?'Parola a fost schimbată.':'Parola utilizatorului a fost resetată.');
  }catch(x){passwordError.textContent=x.message;passwordError.hidden=false}
  finally{passwordSave.disabled=false}
});
