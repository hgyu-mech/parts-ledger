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

let exceptionsOnly = false;

function status(item) {
  if (item.excluded) return '<span class="decision neutral">Excluded</span>';
  if (item.reviewed) return '<span class="decision">Reviewed</span>';
  if (item.flags.length) return '<span class="decision open">Needs review</span>';
  return '<span class="decision neutral">Suggested</span>';
}

function setView(view) {
  if (currentView !== view) closeEditor(false);
  currentView = view;
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('hidden', el.id !== view + '-view'));
  document.querySelectorAll('[data-view]').forEach(el => {
    const active = el.dataset.view === view;
    el.classList.toggle('active',active);
    if (active) el.setAttribute('aria-current','page');
    else el.removeAttribute('aria-current');
  });
}

function renderRows() {
  const flagged = state.items.filter(i => i.flags.length && !i.reviewed);
  $('#flag-summary').textContent = state.invoices.length
    ? 'Review locked after invoice creation. See Activity for decisions.'
    : state.totals.reviewed + ' of ' + state.items.length + ' reviewed · ' + flagged.length + ' open exceptions';
  $('#exceptions').textContent = 'Exceptions (' + flagged.length + ')';
  for (const [id,active] of [['#all-lines',!exceptionsOnly],['#exceptions',exceptionsOnly]]) {
    $(id).classList.toggle('current',active); $(id).setAttribute('aria-pressed',String(active));
  }
  const items = exceptionsOnly ? flagged : state.items;
  $('#parts-body').innerHTML = items.length ? items.map(item => `<tr class="${item.excluded ? 'line-excluded' : item.flags.length && !item.reviewed ? 'line-exception' : ''}">
    <td class="line-ref">${escapeHTML(item.id)}</td>
    <td><span class="line-main">${escapeHTML(item.description)}</span><span class="line-sub">${escapeHTML(state.categories[item.category])}</span><span class="mobile-facts">${item.quantity} × ${dollars(item.unit_cents)} · ${escapeHTML(owners(item).map(m => m.name).join(', ') || '—')}</span></td>
    <td class="num">${item.quantity}</td><td class="num">${dollars(item.unit_cents)}</td><td class="num">${dollars(item.amount_cents)}</td>
    <td><span class="owner-names">${escapeHTML(owners(item).map(m => m.name).join(', ') || '—')}</span></td>
    <td>${status(item)}${item.flags.length && !item.reviewed ? '<small class="cell-sub">' + escapeHTML(item.flags.map(f=>f.label).join(' · ')) + '</small>' : ''}</td>
    <td>${state.invoices.length ? '' : `<button type="button" class="text-button edit-link" data-part="${escapeHTML(item.id)}" aria-expanded="false" aria-label="Review ${escapeHTML(item.id)}: ${escapeHTML(item.description)}">Review</button>`}</td>
    </tr>`).join('') : '<tr><td colspan="8">No open exceptions.</td></tr>';
  $('#approve-clear').disabled = !!state.invoices.length || !state.items.some(i => !i.reviewed && !i.flags.length);
}

function render() {
  $('#project-name').textContent = state.title;
  $('#receipt-total').textContent = dollars(state.totals.receipt_cents);
  $('#billable-total').textContent = dollars(state.totals.billable_cents);
  $('#excluded-total').textContent = state.totals.excluded_cents ? '− ' + dollars(state.totals.excluded_cents) : dollars(0);
  const sandbox = state.connection.mode === 'sandbox';
  $('#mode-pill').textContent = sandbox ? (state.connection.ready ? 'PayPal Sandbox' : 'Sandbox not configured') : 'Offline demo';
  $('#connection-note').textContent = sandbox ? 'USD · PayPal Sandbox only' : 'USD · Sample receipt · No PayPal connection';
  selectedPart = null;
  renderRows();
  for (const id of ['#source-button','#members-button','#edit-members-split']) $(id).disabled = !!state.invoices.length;
  renderSplit(); renderInvoices(); renderActivity(); setView(currentView);
}

function renderSplit() {
  const { members, receipt_cents, excluded_cents, billable_cents, pending } = state.totals;
  const sharesByMember = members.map(({ items }) =>
    new Map(items.map(({ source_id, share_cents }) => [source_id, share_cents]))
  );
  const memberHeadings = members.map(({ member }) =>
    `<th scope="col" class="num">${escapeHTML(member.name)}</th>`
  ).join('');
  const rows = state.items.map(item => {
    const shareCells = sharesByMember.map(shares => {
      const cents = shares.get(item.id);
      return `<td class="num">${cents === undefined ? '—' : dollars(cents)}</td>`;
    }).join('');
    return `<tr>
      <td>${escapeHTML(item.id)}</td>
      <th scope="row">${escapeHTML(item.description)}${item.excluded ? ' <small>Excluded</small>' : ''}</th>
      <td class="num">${dollars(item.amount_cents)}</td>
      ${shareCells}
    </tr>`;
  }).join('');
  const memberTotals = members.map(({ amount_cents }) =>
    `<td class="num">${dollars(amount_cents)}</td>`
  ).join('');
  $('#member-cards').innerHTML = `<div class="register-scroll"><table class="register-table" aria-label="Cost allocation by source line and member">
    <thead><tr><th scope="col">Line</th><th scope="col">Part</th><th scope="col" class="num">Receipt</th>${memberHeadings}</tr></thead>
    <tbody>${rows}</tbody>
    <tfoot><tr><th scope="row" colspan="2">Totals</th><td class="num">${dollars(receipt_cents)}</td>${memberTotals}</tr></tfoot>
  </table></div>`;
  const allocated = members.reduce((sum, share) => sum + share.amount_cents, 0);
  const readiness = pending
    ? `${pending} source ${pending === 1 ? 'line needs' : 'lines need'} review before invoicing.`
    : 'All source lines reviewed.';
  $('#allocation-proof').innerHTML = `<p>Excluded ${dollars(excluded_cents)} · Billable ${dollars(billable_cents)} · Unallocated ${dollars(billable_cents - allocated)}</p><p>${readiness}</p>`;
}

function invoiceStatus(invoice) {
  return escapeHTML(invoice.status) + (invoice.mode === 'fixture' ? ' · simulated' : '');
}

function renderInvoices() {
  const fixture = state.connection.mode === 'fixture';
  $('#invoice-description').textContent = fixture
    ? 'Offline test invoices. Statuses are simulated.'
    : 'Create drafts, issue each invoice, and refresh its status from PayPal Sandbox.';
  $('#invoice-empty').classList.toggle('hidden', state.invoices.length > 0);
  const hasPendingDraft = state.invoices.some(invoice => !invoice.provider_id);
  $('#create-invoices').disabled = !state.totals.ready || (state.invoices.length > 0 && !hasPendingDraft);
  $('#create-invoices').textContent = hasPendingDraft ? 'Retry pending drafts' : 'Create reviewed drafts';
  if (!state.invoices.length) {
    $('#invoice-cards').innerHTML = '';
    return;
  }
  const rows = state.invoices.map(invoice => {
    const id = escapeHTML(invoice.id);
    const actions = [];
    if (invoice.status === 'DRAFT') {
      actions.push(`<button class="text-button" data-issue="${id}">${fixture ? 'Issue test invoice' : 'Issue Sandbox invoice'}</button>`);
    }
    if (invoice.provider_id) {
      actions.push(`<button class="text-button" data-refresh="${id}">Refresh status</button>`);
    }
    if (fixture && invoice.status === 'SENT') {
      actions.push(`<button class="text-button" data-simulate="${id}">Simulate payment</button>`);
    }
    if (!fixture && invoice.payment_url) {
      actions.push(`<a class="button secondary small" href="${escapeHTML(invoice.payment_url)}" target="_blank" rel="noopener noreferrer">Open Sandbox invoice ↗</a>`);
    }
    return `<tr>
      <th scope="row">${escapeHTML(invoice.member_name)}<br><small>${escapeHTML(invoice.recipient_email)}</small></th>
      <td class="num">${dollars(invoice.amount_cents)}</td>
      <td>${invoiceStatus(invoice)}${invoice.error ? `<br><small class="invoice-error">${escapeHTML(invoice.error)}</small>` : ''}</td>
      <td>${escapeHTML(invoice.provider_id || 'Pending')}<br><small>${invoice.mode === 'fixture' ? 'Offline fixture' : 'PayPal Sandbox'}</small></td>
      <td><div class="register-actions">${actions.join(' ')}</div></td>
    </tr>`;
  }).join('');
  $('#invoice-cards').innerHTML = `<div class="register-scroll"><table class="register-table" aria-label="Invoice register">
    <thead><tr><th scope="col">Recipient</th><th scope="col" class="num">Amount</th><th scope="col">Status</th><th scope="col">Reference</th><th scope="col">Actions</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

function renderActivity() {
  const names = {
    source_imported: 'Receipt classified',
    part_reviewed: 'Part reviewed',
    clear_suggestions_confirmed: 'Suggestions confirmed',
    member_details_updated: 'Project members updated',
    invoice_draft_created: 'Invoice draft created',
    invoice_create_failed: 'Invoice creation needs attention',
    invoice_status_changed: 'Invoice status changed',
    invoice_status_checked: 'Invoice status checked'
  };
  const rows = [...state.audit].reverse().map(event => {
    const detail = event.detail;
    let description = '';
    if (event.kind === 'part_reviewed') {
      const category = detail.after.excluded ? 'Excluded' : state.categories[detail.after.category];
      description = [detail.source_id, category, detail.after.reason].filter(Boolean).join(' · ');
    } else if (event.kind === 'source_imported') {
      description = `${detail.lines} receipt lines imported. Import checksums are recorded below.`;
    } else if (event.kind === 'clear_suggestions_confirmed') {
      description = detail.source_ids.join(', ');
    } else if (event.kind.startsWith('invoice_')) {
      const transition = detail.before ? `${detail.before} → ${detail.after}` : '';
      const mode = detail.mode === 'fixture' ? 'Offline fixture' : detail.mode === 'sandbox' ? 'PayPal Sandbox' : detail.mode;
      description = [detail.member_id, transition, mode, detail.error].filter(Boolean).join(' · ');
    }
    const time = new Date(event.time).toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
    return `<tr>
      <td><time datetime="${escapeHTML(event.time)}">${escapeHTML(time)}</time></td>
      <th scope="row">${escapeHTML(names[event.kind] || event.kind)}</th>
      <td>
        ${description ? `<div>${escapeHTML(description)}</div>` : ''}
        <details><summary>Inspect record</summary><pre>${escapeHTML(JSON.stringify(detail, null, 2))}</pre></details>
      </td>
    </tr>`;
  }).join('');
  $('#activity-list').innerHTML = `<div class="register-scroll"><table class="register-table" aria-label="Activity register">
    <thead><tr><th scope="col">Time</th><th scope="col">Event</th><th scope="col">Record</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

function closeEditor(restoreFocus = true) {
  const id = selectedPart;
  const trigger = id && document.querySelector(`[data-part="${id}"]`);
  $('#inline-review')?.closest('tr').remove();
  trigger?.closest('tr').classList.remove('line-selected');
  trigger?.setAttribute('aria-expanded','false');
  trigger?.removeAttribute('aria-controls');
  selectedPart = null;
  if (restoreFocus) trigger?.focus({preventScroll:true});
}

function openPart(id) {
  if (actionPending || state.invoices.length) return;
  if (selectedPart === id) { closeEditor(); return; }
  closeEditor(false);
  const item = state.items.find(i => i.id === id);
  const trigger = document.querySelector(`[data-part="${id}"]`);
  if (!item || !trigger) return;
  selectedPart = id;
  const originalCSV = state.sources.receipt.split(/\r\n|\r|\n/)[item.source_line-1] || '';
  const row = document.createElement('tr'); row.className = 'editor-row';
  row.innerHTML = `<td colspan="8"><section id="inline-review" class="inline-review" aria-labelledby="line-review-title">
    <header class="editor-title"><h3 id="line-review-title">${escapeHTML(id)} · ${escapeHTML(item.description)}</h3><button id="review-close" type="button" class="text-button">Close</button></header>
    <div class="editor-grid">
      <div class="source-facts">
        <h4>Original receipt · line ${item.source_line}</h4><code>${escapeHTML(originalCSV)}</code>
        <p>${item.quantity} × ${dollars(item.unit_cents)} = <strong>${dollars(item.amount_cents)}</strong></p>
        ${item.flags.map(f => '<p class="source-exception">'+escapeHTML(f.label)+'</p>').join('')}
        <p>Model suggestion: <strong>${escapeHTML(state.categories[item.model.category])}</strong> · score ${Math.round(item.model.confidence*100)}%${item.model.evidence_terms.length ? ' · ' + escapeHTML(item.model.evidence_terms.join(', ')) : ''}</p>
      </div>
      <form id="review-form" class="edit-fields">
        <label class="field"><span>Reviewed category</span><select id="review-category">${Object.entries(state.categories).map(([key,label]) => `<option value="${escapeHTML(key)}" ${key===item.category?'selected':''}>${escapeHTML(label)}</option>`).join('')}</select></label>
        <fieldset><legend>Cost owners (equal shares)</legend><div class="owner-picker">${state.members.map(m => `<label><input type="checkbox" name="owner" value="${escapeHTML(m.id)}" ${item.weights[m.id]?'checked':''}>${escapeHTML(m.name)}</label>`).join('')}</div></fieldset>
        <label class="field wide"><span>Review reason</span><textarea id="review-reason" rows="2" minlength="8" maxlength="400" required>${escapeHTML(item.reason)}</textarea></label>
        <p id="review-error" class="invoice-error hidden wide" role="alert"></p>
        <div class="editor-actions wide"><label class="review-options"><input type="checkbox" id="review-excluded" ${item.excluded?'checked':''}>Exclude this line from billing</label><button class="button primary" id="review-save" type="submit">Save decision</button></div>
      </form>
    </div>
  </section></td>`;
  trigger.closest('tr').classList.add('line-selected');
  trigger.setAttribute('aria-expanded','true'); trigger.setAttribute('aria-controls','inline-review');
  trigger.closest('tr').after(row);
  $('#review-close').onclick=()=>closeEditor();
  $('#review-form').onsubmit=async ev=>{
    ev.preventDefault();
    const weights={}; row.querySelectorAll('input[name="owner"]:checked').forEach(n=>weights[n.value]=1);
    const submit=$('#review-save'); submit.disabled=true;
    const notice=$('#review-error'); notice.classList.add('hidden');
    try {
      await action('review',{item_id:id,category:$('#review-category').value,weights,reason:$('#review-reason').value,excluded:$('#review-excluded').checked},'Decision saved.');
      (document.querySelector(`[data-part="${id}"]`) || $('#exceptions')).focus({preventScroll:true});
    } catch (error) {
      if (notice.isConnected) { notice.textContent=error.message; notice.classList.remove('hidden'); }
    } finally { if (submit.isConnected) submit.disabled=false; }
  };
  $('#review-category').focus({preventScroll:true});
  const bounds=row.getBoundingClientRect();
  if (bounds.bottom > window.innerHeight - 16) $('#inline-review').scrollIntoView({block:'nearest',inline:'nearest'});
}

function dialog(title, body, actions='') {
  $('#dialog-content').innerHTML=`<div class="dialog-top"><h2>${escapeHTML(title)}</h2><button id="dialog-close" class="icon-button" aria-label="Close dialog">${icon('close')}</button></div>${body}<div id="dialog-error" class="invoice-error hidden" role="alert"></div>${actions?`<div class="dialog-actions">${actions}</div>`:''}`;
  $('#dialog-close').onclick=()=>$('#app-dialog').close();
  $('#app-dialog').showModal();
}

function sourceDialog() {
  dialog('Source files',`<p class="dialog-description">Paste a typed receipt and an optional bill of materials. Only these source lines are classified; no amount is invented by the model.</p><form id="source-form"><label class="field"><span>Project name</span><input id="source-title" value="${escapeHTML(state.title)}" maxlength="100" required></label><label class="field"><span>Receipt CSV · description,quantity,unit_price</span><textarea class="source-editor" id="source-receipt" required>${escapeHTML(state.sources.receipt)}</textarea></label><label class="field"><span>Optional BOM CSV · description,quantity</span><textarea class="source-editor bom" id="source-bom">${escapeHTML(state.sources.bom)}</textarea></label><p>Importing replaces the current CSV text and clears its review decisions. Activity keeps the checksums from earlier imports.</p><div class="dialog-actions"><button type="submit" class="button primary">Import and classify</button></div></form>`);
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

$('#all-lines').onclick=()=>{ if (!state || actionPending) return; closeEditor(false); exceptionsOnly=false; renderRows(); };
$('#exceptions').onclick=()=>{ if (!state || actionPending) return; closeEditor(false); exceptionsOnly=true; renderRows(); };
document.addEventListener('keydown',ev=>{ if (ev.key==='Escape' && selectedPart && !$('#app-dialog').open) closeEditor(); });

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
$('#primary-action').onclick=()=>setView('split');
$('#create-invoices').onclick=createInvoiceDialog;
$('#reset-button').onclick=()=>{dialog('Start a fresh sample project',`<p class="dialog-description">The current project is archived locally. A new fictional parts receipt and BOM will be loaded. Existing Sandbox invoices are not deleted or cancelled.</p>`,`<button id="reset-confirm" class="button primary">Start fresh demo</button>`);$('#reset-confirm').onclick=async()=>{try{await action('reset',{},'Fresh sample project loaded.');$('#app-dialog').close();setView('review');}catch{}};};
$('#model-info').onclick=()=>dialog('How the suggestions work',`<p class="dialog-description">A local statistical model is trained on ${state.model.training_examples} original, labelled workshop descriptions. It classifies the text at runtime; a fixed lookup table does not supply its predictions.</p><div class="model-facts"><span>Algorithm<strong>Naive Bayes</strong></span><span>External model calls<strong>0</strong></span><span>Training examples<strong>${state.model.training_examples}</strong></span><span>Authored holdout checks<strong>${state.model.holdout_correct} / ${state.model.holdout_examples}</strong></span></div><p>${escapeHTML(state.model.limitations)}</p><p style="margin-top:14px">BOM matching, duplicate checks, owner defaults and cent arithmetic are deterministic helpers, not claimed as AI. You confirm every cost decision before an invoice can be created.</p>`);
$('#export-button').onclick=async()=>{try{const result=await request('/api/export');const blob=new Blob([JSON.stringify(result,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='parts-ledger-reviewed-export.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Source, review decisions and invoice records exported.');}catch(error){toast(error.message,true);}};

(async()=>{try{state=await request('/api/state');render();}catch(error){toast(error.message,true);$('#flag-summary').textContent='Could not load the workspace. Reload after checking the server.';}})();
