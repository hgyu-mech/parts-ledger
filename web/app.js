'use strict';
const $ = selector => document.querySelector(selector);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const dollars = cents => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'}).format(cents / 100);
let session = sessionStorage.getItem('parts-ledger-session');
if (!session || !/^[a-f0-9]{32}$/.test(session)) {
  session = crypto.randomUUID().replaceAll('-', '');
  sessionStorage.setItem('parts-ledger-session', session);
}
let state, currentView = 'review', selectedPart = null, toastTimer, actionPending = false;

function toast(message, error = false) {
  clearTimeout(toastTimer);
  const node = $('#toast'); node.textContent = message;
  node.classList.toggle('error', error); node.classList.remove('hidden');
  toastTimer = setTimeout(() => node.classList.add('hidden'), error ? 6500 : 4000);
}

async function request(path, body) {
  const response = await fetch(path, {method: body ? 'POST' : 'GET', headers: {'X-Ledger-Session':session, ...(body ? {'Content-Type':'application/json'} : {})}, ...(body ? {body:JSON.stringify(body)} : {})});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'This action could not be completed.');
  return result;
}

async function action(name, payload = {}, message = '') {
  if (actionPending) throw new Error('Wait for the current request to finish.');
  actionPending = true;
  const dialogError = $('#dialog-error');
  const dialogButtons = $('#app-dialog').open ? [...$('#dialog-content').querySelectorAll('button:not(:disabled)')] : [];
  dialogButtons.forEach(button => button.disabled = true);
  if (dialogError) { dialogError.textContent = ''; dialogError.classList.add('hidden'); }
  $('#loading').classList.remove('hidden');
  try {
    state = await request('/api/action/' + name, {revision:state.revision, ...payload});
    render(); if (message) toast(message); return state;
  } catch (error) {
    toast(error.message, true);
    if (dialogError && $('#app-dialog').open) { dialogError.textContent = error.message; dialogError.classList.remove('hidden'); }
    if (error.message.includes('another tab')) {
      state = await request('/api/state'); render();
    }
    throw error;
  } finally {
    actionPending = false;
    dialogButtons.forEach(button => { if (button.isConnected) button.disabled = false; });
    $('#loading').classList.add('hidden');
  }
}

function owners(item) {
  return Object.keys(item.weights).map(id => state.members.find(m => m.id === id)).filter(Boolean);
}

function status(item) {
  if (item.excluded) return '<span class="status-tag excluded">Excluded</span>';
  if (item.reviewed) return `<span class="status-tag ok">${icon('check')}Reviewed</span>`;
  if (item.flags.length) return '<span class="status-tag warning">Needs review</span>';
  return '<span class="status-tag">Suggested</span>';
}

function setView(view) {
  currentView = view;
  const labels = {
    review:['01 — REVIEW','Parts & allocations','Check the parts. Keep the source. Know who owes what.'],
    split:['02 — CHECK SPLIT','Who owes what','Trace each share back to the source parts.'],
    invoices:['03 — INVOICES','Invoice status','Reviewed costs, distinct invoices, visible changes.'],
    activity:['DECISION HISTORY','The full record','From the original source to the latest payment status.']
  };
  const label = labels[view];
  $('#stage-label').textContent = label[0]; $('#page-title').textContent = label[1]; $('#page-subtitle').textContent = label[2];
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('hidden', el.id !== view + '-view'));
  document.querySelectorAll('[data-view]').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  $('#primary-action').textContent = view === 'invoices' ? 'Check cost split' : 'Invoice preview';
  $('#primary-action').insertAdjacentHTML('beforeend', icon('arrow'));
}

function render() {
  $('#project-name').textContent = state.title;
  $('.mini-project>strong').textContent = state.title;
  $('#receipt-total').textContent = dollars(state.totals.receipt_cents);
  $('#billable-total').textContent = dollars(state.totals.billable_cents);
  $('#source-count').textContent = `${state.items.length} preserved source lines`;
  $('#excluded-total').textContent = state.totals.excluded_cents ? `${dollars(state.totals.excluded_cents)} excluded from billing` : 'Nothing excluded yet';
  $('#review-count').textContent = state.totals.reviewed;
  $('#review-denom').textContent = ' / ' + state.items.length;
  $('#review-progress').style.width = `${state.totals.reviewed / Math.max(1,state.items.length) * 100}%`;
  $('#nav-pending').textContent = state.totals.pending;
  $('#item-count').textContent = state.items.length;
  $('#flag-summary').textContent = state.totals.pending ? `${state.totals.flagged} flagged · ${state.totals.pending} lines awaiting confirmation` : 'Every source line reviewed. Ready to check the split.';
  const sandbox = state.connection.mode === 'sandbox';
  $('#mode-pill').innerHTML = `<span></span>${sandbox ? (state.connection.ready ? 'PayPal Sandbox' : 'Sandbox not configured') : 'Offline demo'}`;
  $('#mode-pill').classList.toggle('sandbox', sandbox && state.connection.ready);
  $('#connection-note').textContent = sandbox ? 'Sandbox test accounts only · no live PayPal endpoint · issue each invoice after confirmation.' : 'Typed sample receipt · offline PayPal responses · no money moves.';
  $('#parts-body').innerHTML = state.items.map(item => `<tr data-part="${item.id}" tabindex="0" role="button" aria-label="Review ${escapeHTML(item.description)}" class="${selectedPart === item.id ? 'selected' : ''}"><td class="row-number">${item.id.slice(1)}</td><td><span class="part-title ${item.excluded ? 'excluded' : ''}">${escapeHTML(item.description)}</span><span class="part-category">${escapeHTML(state.categories[item.category])}<span class="confidence" title="Uncalibrated model score, not a certainty guarantee">· ${Math.round(item.model.confidence * 100)}%</span></span></td><td>${item.quantity}</td><td class="amount-col"><strong>${dollars(item.amount_cents)}</strong></td><td><div class="owner-chips">${owners(item).map(m => `<span class="owner-chip" title="${escapeHTML(m.name)}">${escapeHTML(m.name.slice(0,1))}</span>`).join('')}</div></td><td>${status(item)}</td></tr>`).join('');
  const flagged = state.items.filter(i => i.flags.length && !i.reviewed);
  $('#attention-title').textContent = flagged.length ? `${flagged.length} parts need a closer look.` : (state.totals.pending ? 'Confirm the suggested shares.' : 'The split is ready to check.');
  $('#attention-list').innerHTML = flagged.map(i => `<button class="attention-item" data-part="${i.id}"><span>${i.id.slice(1)}</span><span><strong>${escapeHTML(i.description)}</strong><small>${escapeHTML(i.flags.map(f => f.label).join(' · '))}</small></span></button>`).join('');
  $('#approve-clear').disabled = !!state.invoices.length || !state.items.some(i => !i.reviewed && !i.flags.length);
  $('#source-button').disabled = !!state.invoices.length;
  $('#members-button').disabled = !!state.invoices.length;
  $('#edit-members-split').disabled = !!state.invoices.length;
  renderSplit(); renderInvoices(); renderActivity(); setView(currentView);
}

function renderSplit() {
  $('#member-cards').innerHTML = state.totals.members.map(share => `<article class="member-card"><div class="member-head"><span class="member-avatar">${escapeHTML(share.member.name.slice(0,1))}</span><div><h3>${escapeHTML(share.member.name)}</h3><p>${escapeHTML(share.member.role)}</p></div></div><div class="member-total">${dollars(share.amount_cents)}</div>${share.items.filter(i => i.share_cents).map(i => `<div class="share-line"><span>${escapeHTML(i.description)}<br><small>${escapeHTML(i.source_id)}</small></span><strong>${dollars(i.share_cents)}</strong></div>`).join('')}</article>`).join('');
  const sum = state.totals.members.reduce((n, x) => n + x.amount_cents, 0);
  $('#allocation-proof').innerHTML = `<div class="proof-row"><span>Original receipt</span><strong>${dollars(state.totals.receipt_cents)}</strong></div><div class="proof-row"><span>Reviewed exclusions</span><strong>− ${dollars(state.totals.excluded_cents)}</strong></div><div class="proof-row"><span>Allocated to members</span><strong>${dollars(sum)}</strong></div><div class="proof-row good"><span>Unallocated difference</span><strong>${dollars(state.totals.billable_cents - sum)}</strong></div><p>${state.totals.pending ? `${state.totals.pending} source lines still need review before invoicing.` : 'All source lines have a recorded decision. Shares conserve the total to the cent.'}</p>`;
}

function invoiceStatus(invoice) {
  const tag = invoice.status === 'PAID' ? 'ok' : invoice.error ? 'warning' : '';
  return `<span class="status-tag ${tag}">${escapeHTML(invoice.status)}${invoice.mode === 'fixture' ? ' · simulated' : ''}</span>`;
}

function renderInvoices() {
  const fixture = state.connection.mode === 'fixture';
  $('#invoice-description').textContent = fixture ? 'Offline test invoices. Their status is simulated; no PayPal request is made.' : 'Draft, issue, pay with a Sandbox buyer account, then refresh the status from PayPal.';
  $('#invoice-empty').classList.toggle('hidden', !!state.invoices.length);
  $('#create-invoices').disabled = !state.totals.ready || (state.invoices.length && state.invoices.every(i => i.provider_id));
  $('#create-invoices').textContent = state.invoices.some(i => !i.provider_id) ? 'Retry pending drafts' : 'Create reviewed drafts';
  $('#invoice-cards').innerHTML = state.invoices.map(invoice => `<article class="invoice-card"><div class="member-head"><span class="member-avatar">${escapeHTML(invoice.member_name.slice(0,1))}</span><div><h3>${escapeHTML(invoice.member_name)}</h3><div class="email" title="${escapeHTML(invoice.recipient_email)}">${escapeHTML(invoice.recipient_email)}</div></div></div><div class="member-total">${dollars(invoice.amount_cents)}</div>${invoiceStatus(invoice)}<div class="provider-id">${escapeHTML(invoice.provider_id || 'No provider ID yet')}</div>${invoice.error ? `<div class="invoice-error">${escapeHTML(invoice.error)}</div>` : ''}<div class="invoice-actions">${invoice.status === 'DRAFT' ? `<button class="button primary" data-issue="${invoice.id}">${fixture ? 'Issue test invoice' : 'Issue Sandbox invoice'}</button>` : ''}${invoice.provider_id ? `<button class="button secondary" data-refresh="${invoice.id}">Refresh status</button>` : ''}${fixture && invoice.status === 'SENT' ? `<button class="button secondary" data-simulate="${invoice.id}">Simulate payment</button>` : ''}${!fixture && invoice.payment_url ? `<a class="button secondary" href="${escapeHTML(invoice.payment_url)}" target="_blank" rel="noopener noreferrer">Open Sandbox invoice ↗</a>` : ''}</div><div class="fixture-note">${fixture ? 'Fixture response · no real payment' : 'Sandbox API response · test money only'}</div></article>`).join('');
}

function renderActivity() {
  const names = {source_imported:'Receipt classified', part_reviewed:'Part reviewed', clear_suggestions_confirmed:'Clear suggestions confirmed', member_details_updated:'Project members updated', invoice_draft_created:'Invoice draft created', invoice_create_failed:'Invoice creation needs attention', invoice_status_changed:'Invoice status changed', invoice_status_checked:'Invoice status checked'};
  $('#activity-list').innerHTML = [...state.audit].reverse().map(ev => {
    let detail = '';
    if (ev.kind === 'part_reviewed') detail = `${ev.detail.source_id} · ${ev.detail.after.excluded ? 'Excluded' : state.categories[ev.detail.after.category]} · ${ev.detail.after.reason}`;
    if (ev.kind === 'source_imported') detail = `${ev.detail.lines} source lines · the original text and checksums are retained.`;
    if (ev.kind === 'clear_suggestions_confirmed') detail = ev.detail.source_ids.join(', ') + ' · categories and cost owners confirmed.';
    if (ev.kind.startsWith('invoice_')) detail = `${ev.detail.member_id || ''}${ev.detail.before ? ' · ' + ev.detail.before + ' → ' + ev.detail.after : ''} · ${ev.detail.mode || ''}${ev.detail.error ? ' · ' + ev.detail.error : ''}`;
    return `<article class="activity-event"><time datetime="${ev.time}">${escapeHTML(new Date(ev.time).toLocaleString('en-US', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}))}</time><div><h3>${escapeHTML(names[ev.kind] || ev.kind)}</h3><p>${escapeHTML(detail)}</p><details><summary>Inspect record</summary><pre>${escapeHTML(JSON.stringify(ev.detail,null,2))}</pre></details></div></article>`;
  }).join('');
}

function closeDrawer() {
  $('#review-drawer').classList.add('hidden'); $('#drawer-backdrop').classList.add('hidden'); document.body.style.overflow=''; selectedPart=null;
}

function openPart(id) {
  if (state.invoices.length) { toast('This allocation is locked to its invoices. Inspect the source decisions in Activity.'); setView('activity'); return; }
  const item = state.items.find(i => i.id === id); if (!item) return;
  selectedPart = id;
  const originalCSV = state.sources.receipt.split('\n')[item.source_line-1] || '';
  $('#review-drawer').innerHTML = `<div class="drawer-top"><div><div class="eyebrow">SOURCE ${item.id} · LINE ${item.source_line}</div><h2 id="drawer-title">Review this part</h2></div><button id="drawer-close" class="icon-button" aria-label="Close review">${icon('close')}</button></div><div class="source-row"><small>ORIGINAL RECEIPT ROW</small><strong>${escapeHTML(item.description)}</strong><code>${escapeHTML(originalCSV)}</code><div class="source-numbers"><span>Quantity<b>${item.quantity}</b></span><span>Unit price<b>${dollars(item.unit_cents)}</b></span><span>Line total<b>${dollars(item.amount_cents)}</b></span></div></div><div class="flag-list">${item.flags.map(f => `<span class="status-tag warning">${escapeHTML(f.label)}</span>`).join('')}</div><form id="review-form"><label class="field"><span>Part category</span><select id="review-category">${Object.entries(state.categories).map(([key,label]) => `<option value="${key}" ${key===item.category?'selected':''}>${escapeHTML(label)}</option>`).join('')}</select></label><div class="model-explanation">Model suggestion: ${escapeHTML(state.categories[item.model.category])} · score ${Math.round(item.model.confidence*100)}%.<br>${item.model.evidence_terms.length ? 'Supporting terms: ' + escapeHTML(item.model.evidence_terms.join(', ')) : 'No familiar terms; choose the category yourself.'}</div><div class="field"><span>Who uses this part?</span><div class="owner-picker">${state.members.map(m => `<label class="owner-choice"><input type="checkbox" name="owner" value="${m.id}" ${item.weights[m.id]?'checked':''}>${escapeHTML(m.name)}</label>`).join('')}</div><small>Selected members share this line equally. Odd cents are allocated once.</small></div><label class="field"><span>Review reason</span><textarea id="review-reason" placeholder="What did you check? Why this category or split?" minlength="8" maxlength="400" required>${escapeHTML(item.reason)}</textarea><small>Record the decision; the original model suggestion stays unchanged.</small></label><label class="review-options"><input type="checkbox" id="review-excluded" ${item.excluded?'checked':''}><span>Exclude this source row from billing.<br><small>Keep it in the ledger with the reason above.</small></span></label><button class="button primary drawer-save" type="submit">Save reviewed decision ${icon('check')}</button></form><div class="drawer-action-note">A review decision does not create or issue an invoice.</div>`;
  $('#review-drawer').classList.remove('hidden'); $('#drawer-backdrop').classList.remove('hidden'); document.body.style.overflow='hidden';
  $('#drawer-close').onclick=closeDrawer;
  $('#review-form').onsubmit=async ev=>{
    ev.preventDefault();
    const weights={}; document.querySelectorAll('input[name="owner"]:checked').forEach(n=>weights[n.value]=1);
    try {await action('review',{item_id:id,category:$('#review-category').value,weights,reason:$('#review-reason').value,excluded:$('#review-excluded').checked},'Review decision saved. Original source retained.');closeDrawer();}catch{}
  };
  $('#review-category').focus();
}

function dialog(title, body, actions='') {
  $('#dialog-content').innerHTML=`<div class="dialog-top"><h2>${escapeHTML(title)}</h2><button id="dialog-close" class="icon-button" aria-label="Close dialog">${icon('close')}</button></div>${body}<div id="dialog-error" class="invoice-error hidden" role="alert"></div>${actions?`<div class="dialog-actions">${actions}</div>`:''}`;
  $('#dialog-close').onclick=()=>$('#app-dialog').close();
  $('#app-dialog').showModal();
}

function sourceDialog() {
  dialog('Keep the source in view',`<p class="dialog-description">Paste a typed receipt and an optional bill of materials. Only these source lines are classified; no amount is invented by the model.</p><form id="source-form"><label class="field"><span>Project name</span><input id="source-title" value="${escapeHTML(state.title)}" maxlength="100" required></label><label class="field"><span>Receipt CSV · description,quantity,unit_price</span><textarea class="source-editor" id="source-receipt" required>${escapeHTML(state.sources.receipt)}</textarea></label><label class="field"><span>Optional BOM CSV · description,quantity</span><textarea class="source-editor bom" id="source-bom">${escapeHTML(state.sources.bom)}</textarea></label><p>Importing replaces the current review decisions. Original text and new source checksums will be retained.</p><div class="dialog-actions"><button type="submit" class="button primary">Run local model ${icon('arrow')}</button></div></form>`);
  $('#source-form').onsubmit=async ev=>{ev.preventDefault();try{await action('import',{title:$('#source-title').value,receipt:$('#source-receipt').value,bom:$('#source-bom').value},'Sources imported and classified locally.');$('#app-dialog').close();}catch{}};
}

function membersDialog() {
  const sandbox=state.connection.mode==='sandbox';
  dialog('Project members',`<p class="dialog-description">${sandbox?'Use generated Sandbox buyer addresses such as sb-…@personal.example.com. Normal personal addresses cannot be invoiced by this app.':'These are fictional aliases. Offline test recipients use example.test addresses.'}</p><form id="members-form">${state.members.map(m=>`<div class="member-form-row"><label class="field"><span>Name</span><input data-name="${m.id}" value="${escapeHTML(m.name)}" maxlength="40" required></label><label class="field"><span>Test recipient email</span><input type="email" data-email="${m.id}" value="${escapeHTML(m.email)}" required><small>${escapeHTML(m.role)}</small></label></div>`).join('')}<div class="dialog-actions"><button type="submit" class="button primary">Save test recipients</button></div></form>`);
  $('#members-form').onsubmit=async ev=>{ev.preventDefault();const members=state.members.map(m=>({...m,name:document.querySelector(`[data-name="${m.id}"]`).value,email:document.querySelector(`[data-email="${m.id}"]`).value}));try{await action('members',{members},'Project members updated.');$('#app-dialog').close();}catch{}};
}

function createInvoiceDialog() {
  if(!state.totals.ready){toast(`Review the remaining ${state.totals.pending} source lines first.`,true);setView('review');return;}
  const fixture=state.connection.mode==='fixture';
  dialog(fixture?'Create offline test drafts':'Create Sandbox invoice drafts',`<p class="dialog-description">${fixture?'This exercises the invoice workflow with local fixture responses. It does not connect to PayPal.':'This creates drafts through PayPal Sandbox. Issuing an invoice requires a separate confirmation; no buyer payment is initiated.'}</p><div class="confirm-list">${state.totals.members.filter(s=>s.amount_cents).map(s=>`<div class="confirm-row"><span>${escapeHTML(s.member.name)}<small>${escapeHTML(s.member.email)}</small></span><strong>${dollars(s.amount_cents)}</strong></div>`).join('')}</div><label class="confirm-check"><input id="draft-confirm" type="checkbox"><span>I checked the recipients, excluded rows and exact shares. Create these ${fixture?'offline test':'Sandbox'} drafts.</span></label>`,`<button id="draft-create" class="button primary" disabled>Create reviewed drafts</button>`);
  $('#draft-confirm').onchange=()=>$('#draft-create').disabled=!$('#draft-confirm').checked;
  $('#draft-create').onclick=async()=>{try{await action('create_invoices',{confirmed:true});$('#app-dialog').close();setView('invoices');const failed=state.invoices.filter(i=>i.error).length;toast(failed?`${failed} draft${failed>1?'s':''} need attention. The recorded request IDs are retained for retry.`:'Reviewed drafts created.',!!failed);}catch{}};
}

function issueInvoiceDialog(id) {
  const invoice=state.invoices.find(i=>i.id===id);const fixture=state.connection.mode==='fixture';
  dialog(fixture?'Issue this test invoice':'Issue this Sandbox invoice',`<p class="dialog-description">${fixture?'This changes only a local simulated invoice to SENT.':'PayPal Sandbox will issue the test invoice to this generated Sandbox account. This is separate from the buyer paying it.'}</p><div class="confirm-list"><div class="confirm-row"><span>${escapeHTML(invoice.member_name)}<small>${escapeHTML(invoice.recipient_email)}</small></span><strong>${dollars(invoice.amount_cents)}</strong></div></div><label class="confirm-check"><input id="issue-confirm" type="checkbox"><span>Issue this ${fixture?'offline test':'Sandbox'} invoice for the reviewed amount.</span></label>`,`<button id="issue-submit" class="button primary" disabled>Issue invoice</button>`);
  $('#issue-confirm').onchange=()=>$('#issue-submit').disabled=!$('#issue-confirm').checked;
  $('#issue-submit').onclick=async()=>{try{await action('send_invoice',{invoice_id:id,confirmed:true},'Invoice issued. Payment status remains separate.');$('#app-dialog').close();}catch{}};
}

$('#drawer-backdrop').onclick=closeDrawer;
document.addEventListener('keydown',ev=>{if(ev.key==='Escape')closeDrawer();if((ev.key==='Enter'||ev.key===' ')&&ev.target.matches('tr[data-part]')){ev.preventDefault();openPart(ev.target.dataset.part);}});
document.addEventListener('click',ev=>{
  const target=ev.target.closest('[data-view],[data-part],[data-issue],[data-refresh],[data-simulate]');if(!target)return;
  if(target.dataset.view)setView(target.dataset.view);
  if(target.dataset.part)openPart(target.dataset.part);
  if(target.dataset.issue)issueInvoiceDialog(target.dataset.issue);
  if(target.dataset.refresh)action('refresh_invoice',{invoice_id:target.dataset.refresh},state.connection.mode==='fixture'?'Offline status checked. No PayPal request.':'Status refreshed from PayPal Sandbox.').catch(()=>{});
  if(target.dataset.simulate)action('simulate_payment',{invoice_id:target.dataset.simulate},'Offline test payment simulated. No money moved.').catch(()=>{});
});
$('#source-button').onclick=sourceDialog;
$('#members-button').onclick=membersDialog;$('#edit-members-split').onclick=membersDialog;
$('#approve-clear').onclick=async()=>{try{await action('approve_clear');toast(state.totals.pending ? `${state.totals.pending} source lines still need review.` : 'All source lines reviewed. The cost split is ready.');}catch{}};
$('#primary-action').onclick=()=>{if(currentView==='invoices'){setView('split');return;}setView('split');if(!state.totals.ready)toast('Check the split now; finish the flagged reviews before creating invoices.');};
$('#create-invoices').onclick=createInvoiceDialog;
$('#reset-button').onclick=()=>{dialog('Start a fresh sample project',`<p class="dialog-description">The current project is archived locally. A new fictional parts receipt and BOM will be loaded. Existing Sandbox invoices are not deleted or cancelled.</p>`,`<button id="reset-confirm" class="button primary">Start fresh demo</button>`);$('#reset-confirm').onclick=async()=>{try{await action('reset',{},'Fresh sample project loaded.');$('#app-dialog').close();setView('review');}catch{}};};
$('#model-info').onclick=()=>dialog('How the suggestions work',`<p class="dialog-description">A local statistical model is trained on ${state.model.training_examples} original, labelled workshop descriptions. It classifies the text at runtime; a fixed lookup table does not supply its predictions.</p><div class="model-facts"><span>Algorithm<strong>Naive Bayes</strong></span><span>External model calls<strong>0</strong></span><span>Training examples<strong>${state.model.training_examples}</strong></span><span>Authored holdout checks<strong>${state.model.holdout_correct} / ${state.model.holdout_examples}</strong></span></div><p>${escapeHTML(state.model.limitations)}</p><p style="margin-top:14px">BOM matching, duplicate checks, owner defaults and cent arithmetic are deterministic helpers, not claimed as AI. You confirm every cost decision before an invoice can be created.</p>`);
$('#export-button').onclick=async()=>{try{const result=await request('/api/export');const blob=new Blob([JSON.stringify(result,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='parts-ledger-reviewed-export.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Source, review decisions and invoice records exported.');}catch(error){toast(error.message,true);}};

(async()=>{try{state=await request('/api/state');render();}catch(error){toast(error.message,true);$('#flag-summary').textContent='Could not load the workspace. Reload after checking the server.';}})();
