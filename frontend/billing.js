/* Hosted billing uses dashboard authentication; client state can never grant credits. */
(() => {
  let sequence = 0, page = 1, timer = null, enabled = false, busy = false;
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = (amount, currency) => new Intl.NumberFormat('en-US', {style:'currency', currency}).format(amount / 100);
  function reset() {
    sequence++; clearTimeout(timer); timer = null; page = 1; enabled = false; busy = false;
    for (const id of ['billing-products','billing-subscriptions','billing-orders','billing-return-status']) if ($(id)) $(id).textContent = '';
    for (const id of ['billing-refresh','billing-reconcile','billing-pagination']) if ($(id)) $(id).hidden = true;
    if ($('billing-notice')) $('billing-notice').textContent = 'Sign in to view billing.';
  }
  async function json(path, options) {
    const response = await api('/api/payments' + path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(data.detail || 'Billing is temporarily unavailable. Please retry.'); error.status = response.status; throw error; }
    return data;
  }
  function redirect(url) {
    const value = new URL(url);
    if (value.protocol !== 'https:' || value.username || value.password) throw Error('Invalid billing link.');
    window.location.assign(value.href);
  }
  async function refresh(nextPage = page) {
    const uid = currentUser?.id, seq = ++sequence;
    if (!uid || !$('billing-notice')) return;
    try {
      const catalog = await json('/packages');
      if (currentUser?.id !== uid || seq !== sequence) return;
      const [status, history] = await Promise.all([json('/status'), json('/orders?page=' + nextPage)]);
      if (currentUser?.id !== uid || seq !== sequence) return;
      enabled = true; page = nextPage;
      if ($('billing-plans-preview')) $('billing-plans-preview').hidden = true;
      $('billing-notice').textContent = (catalog.test_mode ? 'TEST MODE — no real payment. ' : '') + catalog.credit_policy + ' ' + catalog.subscription_policy;
      $('billing-products').innerHTML = catalog.products.map(p => `<article class="billing-product"><span class="billing-kind">${p.kind === 'subscription' ? 'MONTHLY SUBSCRIPTION' : 'ONE-TIME PACK'}</span><h3>${escape(p.name)}</h3><p class="billing-price">${escape(money(p.price_cents, p.currency))}${p.kind === 'subscription' ? '<small> / month</small>' : ''}</p><p>${Number(p.credits).toLocaleString('en-US')} credits${p.kind === 'subscription' ? ' per billing month' : ''}</p><p class="billing-validity">${p.kind === 'subscription' ? 'Unused credits expire at the end of each billing period.' : 'One-time purchase. Credits never expire.'}</p><button class="btn btn-primary" data-billing-buy="${escape(p.id)}">${p.kind === 'subscription' ? 'Subscribe monthly' : 'Buy credits'}</button><small>Taxes may apply. Final amount shown at checkout.</small></article>`).join('');
      $('billing-subscriptions').innerHTML = status.subscriptions.map(s => `<div class="billing-subscription"><span>Subscription: <strong>${escape(s.status)}</strong>${s.ends_at ? ' · Ends ' + escape(new Date(s.ends_at).toLocaleDateString()) : s.renews_at ? ' · Renews ' + escape(new Date(s.renews_at).toLocaleDateString()) : ''}</span><button class="btn btn-sm btn-outline" data-billing-portal="${escape(s.id)}">Manage subscription</button></div>`).join('');
      $('billing-orders').innerHTML = history.orders.length ? `<h3>Payment history</h3><div class="billing-table"><table><thead><tr><th>Date</th><th>Amount</th><th>Status</th><th>Credits</th><th>Receipt</th></tr></thead><tbody>${history.orders.map(o => `<tr><td>${escape(new Date(o.created_at).toLocaleDateString())}</td><td>${escape(money(o.amount_cents,o.currency))}</td><td>${escape(o.status)}${o.refunded_cents ? ' · ' + escape(money(o.refunded_cents,o.currency)) + ' refunded' : ''}</td><td>${Number(o.credits) - Number(o.credits_reversed)}</td><td><button class="btn btn-sm btn-outline" data-billing-receipt="${escape(o.id)}">View receipt</button></td></tr>`).join('')}</tbody></table></div>` : '<p class="section-intro">No confirmed payments yet.</p>';
      $('billing-refresh').hidden = false; $('billing-reconcile').hidden = false;
      $('billing-pagination').hidden = history.total <= 20;
      $('billing-page').textContent = 'Page ' + page;
      $('billing-prev').disabled = page <= 1; $('billing-next').disabled = page * 20 >= history.total;
      const pending = new URLSearchParams(location.search).get('checkout');
      if (pending && /^[a-f0-9]{64}$/.test(pending)) void checkReturn(pending, uid, seq, 0);
    } catch (error) {
      if (currentUser?.id !== uid || seq !== sequence) return;
      enabled = false;
      if ($('billing-plans-preview')) $('billing-plans-preview').hidden = false;
      $('billing-notice').textContent = error.status === 404 ? 'Purchases are not enabled yet. Your existing credits and projects remain available.' : error.message;
      for (const id of ['billing-products','billing-subscriptions','billing-orders']) $(id).textContent = '';
      for (const id of ['billing-refresh','billing-reconcile','billing-pagination']) $(id).hidden = true;
    }
  }
  async function checkReturn(id, uid, seq, attempt) {
    clearTimeout(timer);
    try {
      const result = await json('/checkout/' + id);
      if (currentUser?.id !== uid || seq !== sequence) return;
      if (result.state === 'refunded') {
        $('billing-return-status').textContent = 'This payment was refunded. The corresponding credits have been reversed.';
        await loadCredits();
      } else if (result.credits_confirmed) {
        $('billing-return-status').textContent = 'Payment confirmed. Your credit balance has been updated.';
        const url = new URL(location.href); url.searchParams.delete('checkout'); window.history.replaceState(null, '', url.pathname + url.search + url.hash);
        await loadCredits(); await refresh();
      } else {
        $('billing-return-status').textContent = 'Waiting for payment confirmation. Returning from checkout does not confirm payment. You can leave and check your history later.';
        if (attempt < 11) timer = setTimeout(() => checkReturn(id, uid, seq, attempt + 1), 5000);
      }
    } catch (error) { if (currentUser?.id === uid && seq === sequence) $('billing-return-status').textContent = error.message; }
  }
  async function action(button) {
    const uid = currentUser?.id;
    if (!uid || !enabled || busy) return;
    busy = true; button.disabled = true;
    try {
      if (button.dataset.billingBuy) {
        const product = button.dataset.billingBuy;
        const storageKey = 'm2v-billing-checkout:' + uid + ':' + product;
        let key;
        try { key = sessionStorage.getItem(storageKey); } catch (_) {}
        key ||= crypto.randomUUID();
        try { sessionStorage.setItem(storageKey, key); } catch (_) {}
        try {
          const result = await json('/checkout', {method:'POST',json:{product_id:product,idempotency_key:key}});
          if (currentUser?.id !== uid) return;
          if (result.url) redirect(result.url);
          else { try { sessionStorage.removeItem(storageKey); } catch (_) {} await loadCredits(); await refresh(); }
        } catch (error) {
          if (error.status === 409 || error.status === 410) { try { sessionStorage.removeItem(storageKey); } catch (_) {} }
          throw error;
        }
      } else {
        const path = button.dataset.billingPortal ? '/portal/' + encodeURIComponent(button.dataset.billingPortal) : '/receipt/' + encodeURIComponent(button.dataset.billingReceipt);
        const result = await json(path,{method:'POST'});
        if (currentUser?.id === uid) redirect(result.url);
      }
    } catch (error) { if (currentUser?.id === uid) $('billing-return-status').textContent = error.message; }
    finally { busy = false; button.disabled = false; }
  }
  document.addEventListener('DOMContentLoaded', () => {
    $('billing-panel')?.addEventListener('click', event => {
      const button = event.target.closest('button[data-billing-buy],button[data-billing-portal],button[data-billing-receipt]');
      if (button) void action(button);
    });
    $('billing-refresh')?.addEventListener('click', () => { void refresh(); void loadCredits(); });
    $('billing-prev')?.addEventListener('click', () => refresh(page - 1));
    $('billing-next')?.addEventListener('click', () => refresh(page + 1));
    $('billing-reconcile')?.addEventListener('click', async event => {
      const button=event.currentTarget,uid=currentUser?.id;button.disabled=true;
      try { const result=await json('/reconcile',{method:'POST'}); if(currentUser?.id===uid){$('billing-return-status').textContent=result.notice;await loadCredits();await refresh();} }
      catch(error){if(currentUser?.id===uid)$('billing-return-status').textContent=error.message;}
      finally{button.disabled=false;}
    });
  });
  window.m2vBilling = {refresh,reset};
})();
