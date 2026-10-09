'use strict';
const state={company:null,loans:[],associates:[],dashboard:null,bnrRates:[],documents:[],templates:[]};
const canEdit=document.body.dataset.canEdit==='1';
const canAdminCompany=document.body.dataset.canAdminCompany==='1';
const ui=Object.freeze({
  menuBtn:document.getElementById('menuBtn'),
  companyName:document.getElementById('companyName'),
  companyMeta:document.getElementById('companyMeta'),
  companySwitch:document.getElementById('companySwitch'),
  themeBtn:document.getElementById('themeBtn'),
  nav:document.getElementById('nav'),
  kPrincipal:document.getElementById('kPrincipal'),
  kRepaid:document.getElementById('kRepaid'),
  kBalance:document.getElementById('kBalance'),
  kInterest:document.getElementById('kInterest'),
  kInterestDue:document.getElementById('kInterestDue'),
  dashboardLoans:document.getElementById('dashboardLoans'),
  recentBody:document.getElementById('recentBody'),
  loanCards:document.getElementById('loanCards'),
  txFilter:document.getElementById('txFilter'),
  txBody:document.getElementById('txBody'),
  interestBody:document.getElementById('interestBody'),
  interestStartBody:document.getElementById('interestStartBody'),
  bnrUpdateBtn:document.getElementById('bnrUpdateBtn'),
  bnrCurrentRate:document.getElementById('bnrCurrentRate'),
  bnrCurrentDate:document.getElementById('bnrCurrentDate'),
  bnrRatesBody:document.getElementById('bnrRatesBody'),
  documentsBody:document.getElementById('documentsBody'),
  templatesBody:document.getElementById('templatesBody'),
  companyCard:document.getElementById('companyCard'),
  dbFileName:document.getElementById('dbFileName'),
  dbIntegrity:document.getElementById('dbIntegrity'),
  dbStorageInfo:document.getElementById('dbStorageInfo'),
  associatesBody:document.getElementById('associatesBody'),
  auditCard:document.getElementById('auditCard'),
  auditBody:document.getElementById('auditBody'),
  txModal:document.getElementById('txModal'),
  txModalTitle:document.getElementById('txModalTitle'),
  txForm:document.getElementById('txForm'),
  txLoan:document.getElementById('txLoan'),
  txDate:document.getElementById('txDate'),
  txType:document.getElementById('txType'),
  txAmount:document.getElementById('txAmount'),
  txTax:document.getElementById('txTax'),
  txReference:document.getElementById('txReference'),
  txNotes:document.getElementById('txNotes'),
  loanEditModal:document.getElementById('loanEditModal'),
  loanEditForm:document.getElementById('loanEditForm'),
  loanEditId:document.getElementById('loanEditId'),
  loanEditContractNo:document.getElementById('loanEditContractNo'),
  loanEditAssociate:document.getElementById('loanEditAssociate'),
  loanEditInterestStartDate:document.getElementById('loanEditInterestStartDate'),
  loanEditMaturityDate:document.getElementById('loanEditMaturityDate'),
  loanEditStatus:document.getElementById('loanEditStatus'),
  loanEditNotes:document.getElementById('loanEditNotes'),
  loanEditSave:document.getElementById('loanEditSave'),
  docModal:document.getElementById('docModal'),
  docType:document.getElementById('docType'),
  docNo:document.getElementById('docNo'),
  docDate:document.getElementById('docDate'),
  docLoan:document.getElementById('docLoan'),
  docFilename:document.getElementById('docFilename'),
  docNotes:document.getElementById('docNotes'),
  wordUploadModal:document.getElementById('wordUploadModal'),
  wordUploadForm:document.getElementById('wordUploadForm'),
  wordDocumentId:document.getElementById('wordDocumentId'),
  wordDocumentLabel:document.getElementById('wordDocumentLabel'),
  wordDocumentFile:document.getElementById('wordDocumentFile'),
  wordDocumentNotes:document.getElementById('wordDocumentNotes'),
  wordUploadButton:document.getElementById('wordUploadButton'),
  templateUploadModal:document.getElementById('templateUploadModal'),
  templateUploadForm:document.getElementById('templateUploadForm'),
  templateUploadFile:document.getElementById('templateUploadFile'),
  templateUploadDescription:document.getElementById('templateUploadDescription'),
  templateUploadButton:document.getElementById('templateUploadButton'),
  generatedUploadModal:document.getElementById('generatedUploadModal'),
  generatedUploadForm:document.getElementById('generatedUploadForm'),
  generatedDocumentId:document.getElementById('generatedDocumentId'),
  generatedDocumentLabel:document.getElementById('generatedDocumentLabel'),
  generatedPdfFile:document.getElementById('generatedPdfFile'),
  generatedPdfNotes:document.getElementById('generatedPdfNotes'),
  generatedUploadButton:document.getElementById('generatedUploadButton'),
  signedUploadModal:document.getElementById('signedUploadModal'),
  signedUploadForm:document.getElementById('signedUploadForm'),
  signedDocumentId:document.getElementById('signedDocumentId'),
  signedDocumentLabel:document.getElementById('signedDocumentLabel'),
  signedPdfFile:document.getElementById('signedPdfFile'),
  signedPdfNotes:document.getElementById('signedPdfNotes'),
  signedUploadButton:document.getElementById('signedUploadButton'),
  documentVersionsModal:document.getElementById('documentVersionsModal'),
  documentVersionsTitle:document.getElementById('documentVersionsTitle'),
  wordVersionsBody:document.getElementById('wordVersionsBody'),
  generatedVersionsBody:document.getElementById('generatedVersionsBody'),
  documentVersionsBody:document.getElementById('documentVersionsBody'),
  companyEditModal:document.getElementById('companyEditModal'),
  companyEditForm:document.getElementById('companyEditForm'),
  editCompanyName:document.getElementById('editCompanyName'),
  editCompanyCui:document.getElementById('editCompanyCui'),
  editCompanyAnafButton:document.getElementById('editCompanyAnafButton'),
  editCompanyAnafPreview:document.getElementById('editCompanyAnafPreview'),
  editCompanyRegCom:document.getElementById('editCompanyRegCom'),
  editCompanyAddress:document.getElementById('editCompanyAddress'),
  editCompanyAdministrator:document.getElementById('editCompanyAdministrator'),
  companyEditSave:document.getElementById('companyEditSave'),
  associateModal:document.getElementById('associateModal'),
  associateModalTitle:document.getElementById('associateModalTitle'),
  assocId:document.getElementById('assocId'),
  assocName:document.getElementById('assocName'),
  assocShare:document.getElementById('assocShare'),
  assocCnp:document.getElementById('assocCnp'),
  assocIdDoc:document.getElementById('assocIdDoc'),
  assocIban:document.getElementById('assocIban'),
  assocAddress:document.getElementById('assocAddress'),
  bnrRateModal:document.getElementById('bnrRateModal'),
  bnrEffectiveDate:document.getElementById('bnrEffectiveDate'),
  bnrRateValue:document.getElementById('bnrRateValue'),
  bnrSourceUrl:document.getElementById('bnrSourceUrl'),
  bnrNotes:document.getElementById('bnrNotes'),
  segmentsModal:document.getElementById('segmentsModal'),
  segmentsModalTitle:document.getElementById('segmentsModalTitle'),
  segmentsBody:document.getElementById('segmentsBody'),
  toastBox:document.getElementById('toastBox'),
});
const {menuBtn, companyName, companyMeta, companySwitch, themeBtn, nav, kPrincipal, kRepaid, kBalance, kInterest, kInterestDue, dashboardLoans, recentBody, loanCards, txFilter, txBody, interestBody, interestStartBody, bnrUpdateBtn, bnrCurrentRate, bnrCurrentDate, bnrRatesBody, documentsBody, templatesBody, companyCard, dbFileName, dbIntegrity, dbStorageInfo, associatesBody, auditCard, auditBody, txModal, txModalTitle, txForm, txLoan, txDate, txType, txAmount, txTax, txReference, txNotes, loanEditModal, loanEditForm, loanEditId, loanEditContractNo, loanEditAssociate, loanEditInterestStartDate, loanEditMaturityDate, loanEditStatus, loanEditNotes, loanEditSave, docModal, docType, docNo, docDate, docLoan, docFilename, docNotes, wordUploadModal, wordUploadForm, wordDocumentId, wordDocumentLabel, wordDocumentFile, wordDocumentNotes, wordUploadButton, templateUploadModal, templateUploadForm, templateUploadFile, templateUploadDescription, templateUploadButton, generatedUploadModal, generatedUploadForm, generatedDocumentId, generatedDocumentLabel, generatedPdfFile, generatedPdfNotes, generatedUploadButton, signedUploadModal, signedUploadForm, signedDocumentId, signedDocumentLabel, signedPdfFile, signedPdfNotes, signedUploadButton, documentVersionsModal, documentVersionsTitle, wordVersionsBody, generatedVersionsBody, documentVersionsBody, companyEditModal, companyEditForm, editCompanyName, editCompanyCui, editCompanyAnafButton, editCompanyAnafPreview, editCompanyRegCom, editCompanyAddress, editCompanyAdministrator, companyEditSave, associateModal, associateModalTitle, assocId, assocName, assocShare, assocCnp, assocIdDoc, assocIban, assocAddress, bnrRateModal, bnrEffectiveDate, bnrRateValue, bnrSourceUrl, bnrNotes, segmentsModal, segmentsModalTitle, segmentsBody, toastBox}=ui;

const fmt=new Intl.NumberFormat('ro-RO',{minimumFractionDigits:2,maximumFractionDigits:2});
const money=v=>fmt.format(Number(v||0))+' lei';
const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const typeLabel={ADVANCE:'Alimentare împrumut',REPAYMENT:'Rambursare principal',INTEREST_PAYMENT:'Plată dobândă',ADJUSTMENT:'Ajustare',OPENING_BALANCE:'Sold inițial'};
const csrfToken=document.querySelector('meta[name="csrf-token"]').content;
async function api(url,opt={}){const method=(opt.method||'GET').toUpperCase();const headers={'Content-Type':'application/json',...(opt.headers||{})};if(!['GET','HEAD','OPTIONS'].includes(method))headers['X-CSRF-Token']=csrfToken;const r=await fetch(url,{credentials:'same-origin',headers,...opt});if(r.status===401){location.href='/login';throw new Error('Sesiunea a expirat')};const ct=r.headers.get('content-type')||'';const data=ct.includes('json')?await r.json():await r.text();if(!r.ok||data?.ok===false)throw new Error(data?.error||'Eroare de comunicare');return data}
async function uploadApi(url,formData){const r=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':csrfToken},body:formData});if(r.status===401){location.href='/login';throw new Error('Sesiunea a expirat')};const ct=r.headers.get('content-type')||'';const data=ct.includes('json')?await r.json():await r.text();if(!r.ok||data?.ok===false)throw new Error(data?.error||'Eroare la încărcare');return data}
function toast(msg,bad=false){const el=document.getElementById('toastBox');el.textContent=msg;el.style.background=bad?'var(--danger)':'var(--ink)';el.classList.add('show');clearTimeout(el._t);el._t=setTimeout(()=>el.classList.remove('show'),2800)}
function openModal(id){document.getElementById(id).classList.add('show')}function closeModal(id){document.getElementById(id).classList.remove('show')}
function anafSummary(i){const flags=[i.vat_registered?'TVA':'neplătitor TVA',i.vat_on_collection?'TVA la încasare':null,i.e_invoice?'RO e-Factura':null,i.inactive?'INACTIV FISCAL':'activ fiscal'].filter(Boolean);return `${i.registration_status||'stare necomunicată'} · ${flags.join(' · ')}${i.caen_code?' · CAEN '+i.caen_code:''} · verificat ${i.queried_date}`}
async function lookupAnafCurrentCompany(){if(!canAdminCompany)return;const cui=String(editCompanyCui.value||'').trim();if(!cui){toast('Introduceți CUI-ul înainte de interogarea ANAF.',true);editCompanyCui.focus();return}const button=editCompanyAnafButton;const old=button.textContent;button.disabled=true;button.textContent='Se verifică…';editCompanyAnafPreview.textContent='Interogare ANAF v9 în curs…';try{const d=await api('/api/anaf/company-lookup',{method:'POST',body:JSON.stringify({cui})});const i=d.item;editCompanyCui.value=i.cui;if(i.name)editCompanyName.value=i.name;if(i.reg_com)editCompanyRegCom.value=i.reg_com;if(i.address)editCompanyAddress.value=i.address;editCompanyAnafPreview.textContent=anafSummary(i);toast('Datele publice ANAF au fost preluate. Verificați și salvați compania.')}catch(x){editCompanyAnafPreview.textContent=x.message;toast(x.message,true)}finally{button.disabled=false;button.textContent=old}}
function showPage(name){document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-'+name));document.querySelectorAll('#nav button').forEach(b=>b.classList.toggle('active',b.dataset.page===name));document.body.classList.remove('menuopen');if(name==='transactions')loadTransactions();if(name==='interest'){loadLoans();loadInterest();}if(name==='bnr')loadBnrRates();if(name==='documents')loadDocuments();if(name==='templates')loadTemplates();if(name==='settings')loadSettings()}
document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>showPage(b.dataset.page));document.getElementById('menuBtn').onclick=()=>document.body.classList.toggle('menuopen');
const savedTheme=localStorage.getItem('mtm-theme')||'light';document.documentElement.dataset.theme=savedTheme;document.getElementById('themeBtn').onclick=()=>{const n=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=n;localStorage.setItem('mtm-theme',n)};
async function refreshAll(){try{await Promise.all([loadDashboard(),loadLoans(),loadAssociates()]);toast('Date actualizate')}catch(e){toast(e.message,true)}}
async function loadDashboard(){const d=await api('/api/dashboard');state.dashboard=d;state.company=d.company;document.getElementById('companyName').textContent=d.company.name;document.getElementById('companyMeta').textContent=`CUI ${d.company.cui} · Nr. RC ${d.company.reg_com||'necompletat'}`;kPrincipal.textContent=money(d.totals.principal);kRepaid.textContent=money(d.totals.repaid);kBalance.textContent=money(d.totals.balance);kInterest.textContent=money(d.totals.interest_calculated);kInterestDue.textContent=money(d.totals.interest_outstanding);const cr=d.current_bnr_rate;if(cr){document.querySelector('#kInterest').nextElementSibling.textContent=`rata BNR ${fmt.format(cr.rate)}% · valabilă din ${cr.effective_date}`;}
 dashboardLoans.innerHTML=d.loans.map(l=>{const pct=Math.min(100,Number(l.repaid)/Number(l.principal)*100);return `<div class="contract"><div class="contracthead"><div><h3>${esc(l.associate_name)}</h3><div class="contractmeta">${esc(l.contract_no)} · ${esc(l.contract_date)}–${esc(l.maturity_date)} · BNR ${fmt.format(l.interest_rate)}%/an</div></div><span class="pill ok">${esc(l.status)}</span></div><div class="progress"><i style="width:${pct}%"></i></div><div class="contractstats"><div><small>Principal</small><b>${money(l.principal)}</b></div><div><small>Rambursat</small><b>${money(l.repaid)}</b></div><div><small>Sold</small><b>${money(l.balance)}</b></div><div><small>Dobândă calculată</small><b>${money(l.interest_calculated)}</b></div></div></div>`}).join('');
 recentBody.innerHTML=d.recent.length?d.recent.map(r=>`<tr><td>${esc(r.txn_date)}</td><td>${esc(r.associate_name)}</td><td><span class="pill info">${esc(typeLabel[r.txn_type]||r.txn_type)}</span></td><td class="num">${money(r.amount)}</td></tr>`).join(''):'<tr><td colspan="4" class="empty">Nu sunt operațiuni.</td></tr>';populateLoanSelects()}
async function loadLoans(){const d=await api('/api/loans');state.loans=d.items;loanCards.innerHTML=d.items.map(l=>{const pct=Math.min(100,Number(l.repaid)/Number(l.principal)*100);const due=Number(l.interest_recognized)-Number(l.interest_paid);const edit=canEdit?`<button class="btn small" onclick="openLoanEdit(${l.id})">Editează contractul</button>`:'';return `<div class="contract"><div class="contracthead"><div><h3>${esc(l.contract_no)} · ${esc(l.associate_name)}</h3><div class="contractmeta">Semnat ${esc(l.original_contract_date)} · dobândă din ${esc(l.interest_start_date||'neconfigurată')} · scadență ${esc(l.maturity_date||'—')} · rată BNR curentă ${fmt.format(l.interest_rate)}%/an</div></div><span class="pill ok">${esc(l.status)}</span></div><div class="progress"><i style="width:${pct}%"></i></div><div class="contractstats"><div><small>Finanțări cumulate</small><b>${money(l.principal)}</b></div><div><small>Rambursat</small><b>${money(l.repaid)}</b></div><div><small>Principal rămas</small><b>${money(l.balance)}</b></div><div><small>Dobândă neachitată</small><b>${money(due)}</b></div></div><div class="formactions">${edit}<a class="btn small" href="/document-files/${encodeURIComponent(l.id===1?'02_Contract_IA-01-2020_Trif_Marius.docx':'03_Contract_IA-02-2020_Trif_Mariana_Mirela.docx')}/download">Deschide contractul</a><button class="btn small" onclick="openTransaction('REPAYMENT',${l.id})">Înregistrează rambursare</button></div></div>`}).join('');populateLoanSelects();renderInterestStartControls()}
function renderInterestStartControls(){
  if(!interestStartBody)return;
  interestStartBody.innerHTML=state.loans.length?state.loans.map(l=>{
    const field=canEdit
      ? `<input id="interestStart-${l.id}" type="date" value="${esc(l.interest_start_date||'')}" min="${esc(l.contract_date||'')}" ${l.maturity_date?`max="${esc(l.maturity_date)}"`:''}>`
      : `<b>${esc(l.interest_start_date||'neconfigurată')}</b>`;
    const actions=canEdit
      ? `<div class="actions actions-start"><button class="btn small primary" onclick="saveInterestStartDate(${l.id},this)">Salvează</button><button class="btn small" onclick="openLoanEdit(${l.id})">Detalii contract</button></div>`
      : '';
    return `<tr><td><b>${esc(l.contract_no)}</b></td><td>${esc(l.associate_name)}</td><td>${esc(l.contract_date||'—')}</td><td>${field}</td><td>${esc(l.maturity_date||'—')}</td><td>${actions}</td></tr>`;
  }).join(''):'<tr><td colspan="6" class="empty">Nu există contracte de împrumut.</td></tr>';
}
async function saveInterestStartDate(id,button){
  if(!canEdit)return;
  const loan=state.loans.find(item=>item.id===id);
  const input=document.getElementById(`interestStart-${id}`);
  if(!loan||!input)return;
  const old=button.textContent;
  button.disabled=true;
  button.textContent='Se salvează…';
  try{
    const d=await api(`/api/loans/${id}`,{method:'PATCH',body:JSON.stringify({interest_start_date:input.value||null})});
    await Promise.all([loadLoans(),loadInterest(),loadDashboard()]);
    toast(`Data dobânzii a fost salvată · ${d.deleted_preliminary||0} calcule preliminare eliminate · ${d.recalculated_periods||0} perioade recalculate`);
  }catch(e){toast(e.message,true)}finally{button.disabled=false;button.textContent=old}
}
function openLoanEdit(id){
  const loan=state.loans.find(item=>item.id===id);
  if(!canEdit||!loan)return;
  loanEditForm.reset();
  loanEditId.value=String(loan.id);
  loanEditContractNo.value=loan.contract_no||'';
  loanEditAssociate.value=loan.associate_name||'';
  loanEditInterestStartDate.value=loan.interest_start_date||'';
  loanEditMaturityDate.value=loan.maturity_date||'';
  loanEditStatus.value=loan.status||'ACTIVE';
  loanEditNotes.value=loan.notes||'';
  openModal('loanEditModal');
}
async function saveLoanContract(e){
  e.preventDefault();
  if(!canEdit)return;
  const id=Number(loanEditId.value);
  const body={
    interest_start_date:loanEditInterestStartDate.value||null,
    maturity_date:loanEditMaturityDate.value||null,
    status:loanEditStatus.value,
    notes:loanEditNotes.value,
  };
  loanEditSave.disabled=true;
  loanEditSave.textContent='Se salvează…';
  try{
    const d=await api(`/api/loans/${id}`,{method:'PATCH',body:JSON.stringify(body)});
    closeModal('loanEditModal');
    await Promise.all([loadLoans(),loadInterest(),loadDashboard()]);
    toast(`Contract actualizat · ${d.deleted_preliminary||0} calcule preliminare eliminate · ${d.recalculated_periods||0} perioade recalculate`);
  }catch(x){toast(x.message,true)}finally{loanEditSave.disabled=false;loanEditSave.textContent='Salvează și recalculează'}
}

function populateLoanSelects(){const html=state.loans.map(l=>`<option value="${l.id}">${esc(l.contract_no)} · ${esc(l.associate_name)} · sold ${money(l.balance)}</option>`).join('');txLoan.innerHTML=html;docLoan.innerHTML='<option value="">Document general</option>'+html}
async function loadTransactions(){const t=txFilter.value?`?type=${encodeURIComponent(txFilter.value)}`:'';const d=await api('/api/transactions'+t);txBody.innerHTML=d.items.length?d.items.map(r=>`<tr><td>${esc(r.txn_date)}</td><td>${esc(r.contract_no)}</td><td>${esc(r.associate_name)}</td><td><span class="pill ${r.txn_type==='REPAYMENT'?'ok':'info'}">${esc(typeLabel[r.txn_type]||r.txn_type)}</span></td><td>${esc(r.reference||'—')}<div class="muted">${esc(r.notes||'')}</div></td><td class="num">${money(r.amount)}</td><td class="num">${money(r.tax_withheld)}</td><td><button class="btn small danger" onclick="deleteTransaction(${r.id})">Șterge</button></td></tr>`).join(''):'<tr><td colspan="8" class="empty">Nu există operațiuni pentru filtrul selectat.</td></tr>'}
function openTransaction(type='REPAYMENT',loanId){txForm.reset();txType.value=type;txDate.value=new Date().toISOString().slice(0,10);txTax.value='0';if(loanId)txLoan.value=String(loanId);txModalTitle.textContent=type==='REPAYMENT'?'Rambursare principal':type==='ADVANCE'?'Alimentare împrumut':'Plată dobândă';openModal('txModal')}
async function saveTransaction(e){e.preventDefault();try{await api('/api/transactions',{method:'POST',body:JSON.stringify({loan_id:Number(txLoan.value),txn_date:txDate.value,txn_type:txType.value,amount:Number(txAmount.value),tax_withheld:Number(txTax.value||0),payment_method:'BANK',reference:txReference.value,notes:txNotes.value})});closeModal('txModal');await refreshAll();await loadTransactions();await loadInterest();toast('Operațiunea a fost salvată')}catch(x){toast(x.message,true)}}
async function deleteTransaction(id){if(!confirm('Ștergi această operațiune? Soldurile și dobânda vor trebui recalculate.'))return;try{await api('/api/transactions/'+id,{method:'DELETE'});await refreshAll();await loadTransactions();toast('Operațiune ștearsă')}catch(e){toast(e.message,true)}}
async function loadInterest(){const d=await api('/api/interest');interestBody.innerHTML=d.items.length?d.items.map(r=>`<tr><td>${esc(r.period_start)}<br><span class="muted">– ${esc(r.period_end)}</span></td><td>${esc(r.contract_no)}<br><span class="muted">${esc(r.associate_name)}</span></td><td class="num">${money(r.opening_balance)}</td><td class="num">${money(r.principal_repayments)}</td><td class="num">${money(r.closing_balance)}</td><td class="num">${r.days}</td><td>${esc(r.rate_summary||'—')}<br><button class="btn small" onclick="showInterestSegments(${r.id})">Detalii</button></td><td class="num"><b>${money(r.calculated_amount)}</b></td><td class="num">${money(r.recognized_amount)}</td><td><span class="pill ${r.status==='RECOGNIZED'?'ok':'warn'}">${esc(r.status)}</span></td><td>${r.status==='RECOGNIZED'?'':`<button class="btn small primary" onclick="recognizeInterest(${r.id},${r.calculated_amount},'${r.period_end}')">Recunoaște</button>`}</td></tr>`).join(''):'<tr><td colspan="11" class="empty">Nu există perioade calculate.</td></tr>'}
async function recalculateInterest(){try{const d=await api('/api/interest/recalculate',{method:'POST',body:'{}'});await loadInterest();await loadDashboard();toast(`${d.periods} perioade recalculate`)}catch(e){toast(e.message,true)}}
async function recognizeInterest(id,amount,day){if(!confirm(`Recunoști dobânda de ${money(amount)} la ${day}?`))return;try{await api('/api/interest/recognize',{method:'POST',body:JSON.stringify({id,recognized_amount:amount,recognized_date:day})});await loadInterest();await loadDashboard();toast('Dobândă recunoscută')}catch(e){toast(e.message,true)}}
async function loadBnrRates(){const d=await api('/api/bnr-rates');state.bnrRates=d.items;const current=d.items[0];bnrCurrentRate.textContent=current?fmt.format(current.rate)+'%':'—';bnrCurrentDate.textContent=current?'valabilă din '+current.effective_date:'Nu există rată înregistrată';bnrRatesBody.innerHTML=d.items.length?d.items.map(r=>`<tr><td><b>${esc(r.effective_date)}</b></td><td class="num"><b>${fmt.format(r.rate)}%</b></td><td><span class="pill ${r.entry_mode==='MANUAL'?'warn':'ok'}">${esc(r.entry_mode)}</span></td><td>${r.source_url?`<a href="${esc(r.source_url)}" target="_blank" rel="noopener">Sursa BNR</a>`:'—'}<div class="muted">${esc(r.source_document||'')}</div></td><td>${esc(r.fetched_at||'—')}</td><td>${esc(r.notes||'')}</td><td><button class="btn small danger" onclick="deleteBnrRate(${r.id})">Șterge</button></td></tr>`).join(''):'<tr><td colspan="7" class="empty">Nu există rate BNR înregistrate.</td></tr>'}
async function updateBnrRate(){const b=document.getElementById('bnrUpdateBtn');b.disabled=true;b.textContent='Se actualizează…';try{const d=await api('/api/bnr-rates/update',{method:'POST',body:'{}'});await Promise.all([loadBnrRates(),loadInterest(),loadDashboard(),loadLoans()]);toast(`Rata BNR ${fmt.format(d.item.rate)}% a fost actualizată; ${d.periods} perioade recalculate`)}catch(e){toast(e.message,true)}finally{b.disabled=false;b.textContent='↻ Actualizează din BNR'}}
function openBnrRateModal(){bnrEffectiveDate.value=new Date().toISOString().slice(0,10);bnrRateValue.value=state.bnrRates[0]?.rate??'';bnrNotes.value='';openModal('bnrRateModal')}
async function saveBnrRate(e){e.preventDefault();try{await api('/api/bnr-rates',{method:'POST',body:JSON.stringify({effective_date:bnrEffectiveDate.value,rate:Number(bnrRateValue.value),source_url:bnrSourceUrl.value,notes:bnrNotes.value})});closeModal('bnrRateModal');await Promise.all([loadBnrRates(),loadInterest(),loadDashboard(),loadLoans()]);toast('Rata a fost salvată și perioadele au fost recalculate')}catch(x){toast(x.message,true)}}
async function deleteBnrRate(id){if(!confirm('Ștergi această rată din registru?'))return;try{await api('/api/bnr-rates/'+id,{method:'DELETE'});await loadBnrRates();toast('Rata a fost ștearsă')}catch(e){toast(e.message,true)}}
async function showInterestSegments(id){try{const d=await api('/api/interest/segments/'+id);segmentsModalTitle.textContent=`${d.accrual.contract_no} · ${d.accrual.associate_name} · ${d.accrual.period_start}–${d.accrual.period_end}`;segmentsBody.innerHTML=d.items.map(r=>`<tr><td>${esc(r.segment_start)} – ${esc(r.segment_end)}</td><td class="num">${r.days}</td><td class="num">${fmt.format(r.rate)}%</td><td class="num">${fmt.format(r.balance_days)}</td><td class="num"><b>${money(r.calculated_amount)}</b></td><td>${r.source_url?`<a href="${esc(r.source_url)}" target="_blank" rel="noopener">BNR</a>`:'—'}<div class="muted">valabilă din ${esc(r.rate_effective_date||'—')}</div></td></tr>`).join('');openModal('segmentsModal')}catch(e){toast(e.message,true)}}
function fileSize(bytes){const n=Number(bytes||0);if(n<1024)return n+' B';if(n<1048576)return (n/1024).toFixed(1)+' KB';return (n/1048576).toFixed(1)+' MB'}

async function loadTemplates(){const d=await api('/api/templates');state.templates=d.items;templatesBody.innerHTML=d.items.length?d.items.map(t=>{const path=t.path.split('/').map(encodeURIComponent).join('/');const copy=canEdit?`<button class="btn small" onclick="copyTemplate('${encodeURIComponent(t.path)}')">Copiază în companie</button>`:'';return `<tr><td><span class="pill ${t.category==='STANDARD'?'ok':'info'}">${esc(t.category)}</span></td><td><b>${esc(t.filename)}</b>${t.uploaded_by?`<div class="muted">încărcat de ${esc(t.uploaded_by)}</div>`:''}</td><td>${esc(t.description)}</td><td>${esc(t.extension)}</td><td class="num">${fileSize(t.size_bytes)}</td><td>${esc(t.modified_at||'—')}</td><td><div class="actions actions-start"><a class="btn small primary" href="/templates/${path}/download">↓ Descarcă</a>${copy}</div></td></tr>`}).join(''):'<tr><td colspan="7" class="empty">Nu există șabloane.</td></tr>'}
function openTemplateUpload(){templateUploadForm.reset();openModal('templateUploadModal')}
async function uploadTemplate(e){e.preventDefault();const file=templateUploadFile.files[0];if(!file){toast('Selectați fișierul șablon',true);return}if(file.size>25*1024*1024){toast('Fișierul depășește limita de 25 MB',true);return}const fd=new FormData();fd.append('file',file);fd.append('description',templateUploadDescription.value);templateUploadButton.disabled=true;templateUploadButton.textContent='Se încarcă…';try{const d=await uploadApi('/api/templates/upload',fd);closeModal('templateUploadModal');await loadTemplates();toast(`Șablon încărcat: ${d.filename}`)}catch(x){toast(x.message,true)}finally{templateUploadButton.disabled=false;templateUploadButton.textContent='Încarcă șablon'}}
async function copyTemplate(encodedPath){const path=decodeURIComponent(encodedPath).split('/').map(encodeURIComponent).join('/');try{const d=await api(`/api/templates/${path}/copy-to-company`,{method:'POST',body:'{}'});toast(d.copied?`Șablon copiat în dosarul companiei: ${d.filename}`:`Șablonul există deja în dosarul companiei: ${d.filename}`)}catch(x){toast(x.message,true)}}
async function loadDocuments(){
  const d=await api('/api/documents');
  state.documents=d.items;
  documentsBody.innerHTML=d.items.length?d.items.map(r=>{
    const currentName=(r.filename||'').split('/').pop();
    const word=r.filename
      ? `<a class="btn small" href="/documents/${r.id}/download">↓ ${esc(currentName)}</a>${Number(r.word_version_count||0)?`<div class="muted">${r.word_version_count} versiuni Word</div>`:''}`
      : '<span class="muted">Fără fișier Word</span>';
    const generated=Number(r.generated_pdf_count||0)>0
      ? `<a class="btn small primary" target="_blank" href="/documents/${r.id}/generated/${r.latest_generated_pdf_id}/view">PDF arhivat v${r.latest_generated_pdf_version_no}</a><div class="muted">${esc(r.latest_generated_pdf_at||'')}</div>`
      : (r.filename?`<a class="btn small primary" target="_blank" href="/documents/${r.id}/word-print">Previzualizează / PDF</a><div class="muted">Print → Save as PDF</div>`:'<span class="muted">Negenerat</span>');
    const signed=Number(r.signed_count||0)>0
      ? `<a class="btn small primary" href="/documents/${r.id}/signed/${r.latest_signed_id}/download">↓ PDF v${r.latest_signed_version_no}</a><div class="muted">${esc(r.latest_signed_uploaded_at||'')}</div>`
      : '<span class="muted">Nesemnat</span>';
    const common=r.filename?`<a class="btn small" target="_blank" href="/documents/${r.id}/word-print">🖨 Tipărește / PDF</a>`:'';
    const editActions=canEdit
      ? `<button class="btn small" onclick="openWordUpload(${r.id})">↺ Înlocuiește Word</button><button class="btn small" onclick="generatePdf(${r.id},this)">PDF / Print</button><button class="btn small" onclick="openGeneratedUpload(${r.id})">↑ PDF generat</button><button class="btn small" onclick="openSignedUpload(${r.id})">↑ PDF semnat</button><button class="btn small" onclick="showDocumentVersions(${r.id})">Istoric</button><button class="btn small danger" onclick="deleteDocument(${r.id})">Șterge</button>`
      : `<button class="btn small" onclick="showDocumentVersions(${r.id})">Istoric</button>`;
    return `<tr><td>${esc(r.doc_date||'—')}</td><td><b>${esc(r.doc_type)}</b><div class="muted">${esc(r.doc_no||'fără număr')}</div></td><td>${esc(r.associate_name||'General')}<div class="muted">${esc(r.contract_no||'—')}</div></td><td>${word}</td><td>${generated}</td><td>${signed}</td><td><span class="pill ${r.status==='SIGNED'?'ok':'warn'}">${esc(r.status)}</span></td><td><div class="actions actions-start">${common}${editActions}</div></td></tr>`;
  }).join(''):'<tr><td colspan="8" class="empty">Nu există documente.</td></tr>';
}
function openDocumentModal(){docDate.value=new Date().toISOString().slice(0,10);openModal('docModal')}
async function saveDocument(e){e.preventDefault();const loan=state.loans.find(l=>l.id===Number(docLoan.value));try{await api('/api/documents',{method:'POST',body:JSON.stringify({doc_type:docType.value,doc_no:docNo.value,doc_date:docDate.value,loan_id:docLoan.value||null,associate_id:loan?.associate_id||null,filename:docFilename.value,status:'READY_FOR_SIGNATURE',notes:docNotes.value})});closeModal('docModal');e.target.reset();await loadDocuments();toast('Document adăugat')}catch(x){toast(x.message,true)}}
function openWordUpload(id){const d=state.documents.find(x=>x.id===id);wordUploadForm.reset();wordDocumentId.value=String(id);wordDocumentLabel.textContent=d?`${d.doc_type} ${d.doc_no||''} · ${(d.filename||'fără fișier Word').split('/').pop()}`:`Document ${id}`;openModal('wordUploadModal')}
async function uploadWordVersion(e){e.preventDefault();const id=Number(wordDocumentId.value);const file=wordDocumentFile.files[0];if(!file){toast('Selectați documentul Word',true);return}if(file.size>25*1024*1024){toast('Fișierul depășește limita de 25 MB',true);return}const fd=new FormData();fd.append('file',file);fd.append('notes',wordDocumentNotes.value);wordUploadButton.disabled=true;wordUploadButton.textContent='Se încarcă…';try{const d=await uploadApi(`/api/documents/${id}/word-version`,fd);closeModal('wordUploadModal');await loadDocuments();toast(`Documentul Word a devenit versiunea ${d.version_no}`)}catch(x){toast(x.message,true)}finally{wordUploadButton.disabled=false;wordUploadButton.textContent='Înlocuiește Word'}}
async function generatePdf(id,button){
  const old=button.textContent;
  button.disabled=true;
  button.textContent='Se pregătește…';
  try{
    const d=await api(`/api/documents/${id}/generate-pdf`,{method:'POST',body:'{}'});
    if(d.mode==='browser_print'&&d.print_url){
      toast('S-a deschis previzualizarea. Alegeți Print → Save as PDF.');
      window.open(d.print_url,'_blank','noopener');
      return;
    }
    await loadDocuments();
    toast(d.reused?`PDF-ul existent v${d.version_no} corespunde documentului Word curent`:`PDF generat ca versiunea ${d.version_no}`);
    window.open(`/documents/${id}/generated/${d.id}/view`,'_blank','noopener');
  }catch(x){toast(x.message,true)}finally{button.disabled=false;button.textContent=old}
}
function openGeneratedUpload(id){const d=state.documents.find(x=>x.id===id);generatedUploadForm.reset();generatedDocumentId.value=String(id);generatedDocumentLabel.textContent=d?`${d.doc_type} ${d.doc_no||''} · ${d.filename||'fără fișier Word'}`:`Document ${id}`;openModal('generatedUploadModal')}
async function uploadGeneratedPdf(e){e.preventDefault();const id=Number(generatedDocumentId.value);const file=generatedPdfFile.files[0];if(!file){toast('Selectați fișierul PDF salvat',true);return}if(file.size>25*1024*1024){toast('Fișierul depășește limita de 25 MB',true);return}const fd=new FormData();fd.append('file',file);fd.append('notes',generatedPdfNotes.value);generatedUploadButton.disabled=true;generatedUploadButton.textContent='Se încarcă…';try{const d=await uploadApi(`/api/documents/${id}/generated-versions`,fd);closeModal('generatedUploadModal');await loadDocuments();toast(d.reused?`PDF-ul există deja ca versiunea ${d.version_no}`:`PDF generat încărcat ca versiunea ${d.version_no}`)}catch(x){toast(x.message,true)}finally{generatedUploadButton.disabled=false;generatedUploadButton.textContent='Încarcă PDF generat'}}
function openSignedUpload(id){const d=state.documents.find(x=>x.id===id);signedUploadForm.reset();signedDocumentId.value=String(id);signedDocumentLabel.textContent=d?`${d.doc_type} ${d.doc_no||''} · ${d.filename||'fără fișier original'}`:`Document ${id}`;openModal('signedUploadModal')}
async function uploadSignedPdf(e){e.preventDefault();const id=Number(signedDocumentId.value);const file=signedPdfFile.files[0];if(!file){toast('Selectați fișierul PDF',true);return}if(file.size>25*1024*1024){toast('Fișierul depășește limita de 25 MB',true);return}const fd=new FormData();fd.append('file',file);fd.append('notes',signedPdfNotes.value);signedUploadButton.disabled=true;signedUploadButton.textContent='Se încarcă…';try{const d=await uploadApi(`/api/documents/${id}/signed-versions`,fd);closeModal('signedUploadModal');await loadDocuments();toast(`PDF semnat încărcat ca versiunea ${d.version_no}`)}catch(x){toast(x.message,true)}finally{signedUploadButton.disabled=false;signedUploadButton.textContent='Încarcă PDF'}}
async function showDocumentVersions(id){try{const d=await api(`/api/documents/${id}/history`);documentVersionsTitle.textContent=`Istoric · ${d.document.doc_type} ${d.document.doc_no||''}`;wordVersionsBody.innerHTML=d.word_items.length?d.word_items.map(v=>`<tr><td><b>v${v.version_no}</b>${v.is_current?'<div><span class="pill ok">curent</span></div>':''}</td><td><a href="/documents/${id}/word/${v.id}/download">${esc(v.original_filename)}</a><div><a target="_blank" class="btn small" href="/documents/${id}/word/${v.id}/print">Tipărește / PDF</a></div></td><td>${esc(v.uploaded_at)}</td><td>${esc(v.uploaded_by||'—')}</td><td>${fileSize(v.size_bytes)}</td><td class="mono" title="${esc(v.sha256)}">${esc(v.sha256.slice(0,12))}…</td><td>${esc(v.notes||'')}</td></tr>`).join(''):'<tr><td colspan="7" class="empty">Documentul Word inițial nu a fost încă înlocuit.</td></tr>';generatedVersionsBody.innerHTML=d.generated_items.length?d.generated_items.map(v=>`<tr><td><b>v${v.version_no}</b></td><td>${esc(v.original_filename)}</td><td>${esc(v.generated_at)}</td><td>${esc(v.generated_by||'—')}</td><td>${fileSize(v.size_bytes)}</td><td class="mono" title="${esc(v.sha256)}">${esc(v.sha256.slice(0,12))}…</td><td><div class="actions actions-start"><a target="_blank" class="btn small primary" href="/documents/${id}/generated/${v.id}/view">Vizualizează / tipărește</a><a class="btn small" href="/documents/${id}/generated/${v.id}/download">Descarcă</a></div></td></tr>`).join(''):'<tr><td colspan="7" class="empty">Nu există PDF-uri generate.</td></tr>';documentVersionsBody.innerHTML=d.signed_items.length?d.signed_items.map(v=>`<tr><td><b>v${v.version_no}</b></td><td><a href="/documents/${id}/signed/${v.id}/download">${esc(v.original_filename)}</a></td><td>${esc(v.uploaded_at)}</td><td>${esc(v.uploaded_by||'—')}</td><td>${fileSize(v.size_bytes)}</td><td class="mono" title="${esc(v.sha256)}">${esc(v.sha256.slice(0,12))}…</td><td>${esc(v.notes||'')}</td><td>${canEdit?`<button class="btn small danger" onclick="deleteSignedVersion(${id},${v.id})">Șterge</button>`:''}</td></tr>`).join(''):'<tr><td colspan="8" class="empty">Nu există versiuni semnate.</td></tr>';openModal('documentVersionsModal')}catch(x){toast(x.message,true)}}
async function deleteSignedVersion(documentId,versionId){if(!confirm('Ștergi această versiune PDF semnată și fișierul fizic aferent?'))return;try{await api(`/api/documents/${documentId}/signed-versions/${versionId}`,{method:'DELETE'});await loadDocuments();await showDocumentVersions(documentId);toast('Versiunea semnată a fost ștearsă')}catch(x){toast(x.message,true)}}
async function deleteDocument(id){if(!confirm('Ștergi înregistrarea din registru? Fișierul original nu va fi șters.'))return;try{await api('/api/documents/'+id,{method:'DELETE'});await loadDocuments();toast('Înregistrare ștearsă')}catch(e){toast(e.message,true)}}
async function loadAssociates(){const d=await api('/api/associates');state.associates=d.items}
async function loadSettings(){await loadAssociates();const c=await api('/api/company');state.company=c.item;companyCard.innerHTML=`<div class="formgrid"><div class="field span2"><label>Denumire</label><b>${esc(c.item.name)}</b></div><div class="field"><label>CUI</label><b>${esc(c.item.cui)}</b></div><div class="field"><label>Nr. RC</label><b>${esc(c.item.reg_com||'de completat')}</b></div><div class="field span4"><label>Sediu</label><span>${esc(c.item.address||'de completat')}</span></div><div class="field span2"><label>Administrator</label><span>${esc(c.item.administrator||'de completat')}</span></div></div>`;dbFileName.textContent=c.item.db_filename||'—';dbIntegrity.textContent=c.item.db_ok?'SQLite OK':(c.item.db_exists?'Bază invalidă':'Bază lipsă');dbIntegrity.className=c.item.db_ok?'oktext':'errtext';const size=Number(c.item.db_size_bytes||0);dbStorageInfo.textContent=`${c.item.db_path||'Cale indisponibilă'} · ${fileSize(size)} · documente: ${c.item.documents_subdir||'—'}`;associatesBody.innerHTML=state.associates.length?state.associates.map(a=>`<tr><td><b>${esc(a.name)}</b><div class="muted">${esc(a.address||'')}</div></td><td class="num">${fmt.format(a.share_pct)}%</td><td>${esc(a.cnp||'de completat')}</td><td>${esc(a.id_doc||'—')}</td><td>${esc(a.iban||'de completat')}</td><td><button class="btn small" onclick="editAssociate(${a.id})">Editează</button></td></tr>`).join(''):`<tr><td colspan="6" class="empty">Nu există asociați / creditori în baza acestei companii. Folosiți „Adaugă creditor”.</td></tr>`}
function openCompanyEdit(){if(!canAdminCompany||!state.company)return;editCompanyName.value=state.company.name||'';editCompanyCui.value=state.company.cui||'';editCompanyRegCom.value=state.company.reg_com||'';editCompanyAddress.value=state.company.address||'';editCompanyAdministrator.value=state.company.administrator||'';editCompanyAnafPreview.textContent='';openModal('companyEditModal')}
async function saveCompany(e){e.preventDefault();if(!canAdminCompany)return;companyEditSave.disabled=true;companyEditSave.textContent='Se salvează…';try{await api('/api/company',{method:'PATCH',body:JSON.stringify({name:editCompanyName.value,cui:editCompanyCui.value,reg_com:editCompanyRegCom.value,address:editCompanyAddress.value,administrator:editCompanyAdministrator.value})});closeModal('companyEditModal');await Promise.all([loadSettings(),loadDashboard()]);toast('Datele companiei au fost actualizate')}catch(x){toast(x.message,true)}finally{companyEditSave.disabled=false;companyEditSave.textContent='Salvează compania'}}
function clearAssociateForm(){assocId.value='';assocName.value='';assocShare.value='0';assocCnp.value='';assocIdDoc.value='';assocIban.value='';assocAddress.value=''}
function openAssociateCreate(){clearAssociateForm();associateModalTitle.textContent='Adaugă asociat / creditor';openModal('associateModal')}
function editAssociate(id){const a=state.associates.find(x=>x.id===id);associateModalTitle.textContent='Actualizare asociat / creditor';assocId.value=a.id;assocName.value=a.name;assocShare.value=a.share_pct;assocCnp.value=a.cnp||'';assocIdDoc.value=a.id_doc||'';assocIban.value=a.iban||'';assocAddress.value=a.address||'';openModal('associateModal')}
async function saveAssociate(e){e.preventDefault();const id=assocId.value;const body=JSON.stringify({name:assocName.value,share_pct:Number(assocShare.value),cnp:assocCnp.value,id_doc:assocIdDoc.value,iban:assocIban.value,address:assocAddress.value});try{await api(id?'/api/associates/'+id:'/api/associates',{method:id?'PATCH':'POST',body});closeModal('associateModal');await loadSettings();await refreshAll();toast(id?'Creditor actualizat':'Creditor adăugat')}catch(x){toast(x.message,true)}}
async function loadAudit(){const d=await api('/api/audit');auditCard.classList.remove('is-hidden');auditBody.innerHTML=d.items.length?d.items.map(r=>`<tr><td>${esc(r.event_time)}</td><td>${esc(r.action)}</td><td>${esc(r.entity)} ${r.entity_id??''}</td><td>${esc(r.details||'')}</td></tr>`).join(''):'<tr><td colspan="4" class="empty">Jurnal gol.</td></tr>';auditCard.scrollIntoView({behavior:'smooth'})}
function exportData(dataset){location.href='/api/export?dataset='+encodeURIComponent(dataset)}
async function backupDb(){try{const d=await api('/api/backup');toast('Backup creat: '+d.filename)}catch(e){toast(e.message,true)}}
window.addEventListener('click',e=>{if(e.target.classList.contains('modalback'))e.target.classList.remove('show')});
document.getElementById('companySwitch')?.addEventListener('change',async e=>{try{await api('/api/auth/company',{method:'POST',body:JSON.stringify({company_id:Number(e.target.value)})});location.reload()}catch(x){toast(x.message,true)}});
refreshAll().catch(e=>toast(e.message,true));
