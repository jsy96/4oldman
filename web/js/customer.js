/* 顾客端：订单历史 / 预约服务（冲突智能提醒）/ 账户明细 / 我的。 */
const Customer = {

  async renderOrders(el) {
    el.innerHTML = '<div class="loading">加载中…</div>';
    const { orders } = await API.call('/api/c/orders');
    if (!orders.length) { el.innerHTML = '<div class="empty">还没有订单，去“预约服务”下一单吧</div>'; return; }
    let alt = false, lastDate = null;
    el.innerHTML = orders.map(o => {
      const d = o.sched_start.slice(0, 10);
      if (d !== lastDate) { alt = !alt; lastDate = d; }  // 换日期翻一次底色
      return `
      <div class="card order-card ${o.status}${alt ? ' date-alt' : ''}">
        <div class="head"><span class="time">${esc(o.sched_start)}</span>${chip(o.status)}</div>
        <div class="who">${esc(o.item_name)} <span class="muted small">¥${fmtMoney(o.price_cents)}</span></div>
        <div class="meta">服务员：${esc(o.worker_name)} · ${o.minutes}分钟</div>
        ${o.exception_type ? `<div class="warn-box">异常：${esc(o.exception_type)} ${esc(o.exception_note || '')}</div>` : ''}
        ${o.note ? `<div class="meta">备注：${esc(o.note)}</div>` : ''}
        ${['pending', 'confirmed'].includes(o.status) ? `<button class="btn btn-plain btn-small" data-cancel="${o.id}">取消预约</button>` : ''}
      </div>`;
    }).join('');
    el.querySelectorAll('[data-cancel]').forEach(b => b.onclick = async () => {
      if (!confirm('确定取消这个预约吗？')) return;
      try {
        await API.call(`/api/c/orders/${b.dataset.cancel}/cancel`, { method: 'POST' });
        toast('已取消', true);
        Customer.renderOrders(el);
      } catch (e) { toast(e.message); }
    });
  },

  async renderBook(el) {
    el.innerHTML = '<div class="loading">加载中…</div>';
    const { items } = await API.call('/api/c/services');
    const today = todayStr();
    const times = [];
    for (let h = 8; h <= 17; h++) for (const m of [0, 30]) {
      if (h === 17 && m) continue;
      times.push(`${pad(h)}:${pad(m)}`);
    }
    el.innerHTML = `
      <div class="card">
        <h3>① 选择服务项目</h3>
        <div class="pick-list" id="item-list">
          ${items.map((i, n) => `
            <label class="pick${n === 0 ? ' on' : ''}">
              <input type="radio" name="svc" value="${i.id}" data-min="${i.minutes}" ${n === 0 ? 'checked' : ''}>
              <div><div class="t">${esc(i.name)}</div>
              <div class="d">约 ${i.minutes} 分钟 · ¥${fmtMoney(i.price_cents)}</div></div>
            </label>`).join('')}
        </div>
        <h3 style="margin-top:16px">② 选择日期时间</h3>
        <div class="frow">
          <div><label class="fl">日期</label><input type="date" id="bk-date" min="${today}" value="${today}"></div>
          <div><label class="fl">时间</label><select id="bk-time">${times.map(t => `<option>${t}</option>`).join('')}</select></div>
        </div>
        <label class="fl">备注（选填）</label>
        <textarea id="bk-note" placeholder="例如：家住3楼无电梯、需要带浴凳等"></textarea>
        <button class="btn btn-lg" id="bk-submit" style="margin-top:16px">确认预约</button>
        <div class="muted small" style="margin-top:8px">预约后如与服务员其他顾客时间冲突，我们会提醒您并推荐空闲时段。</div>
      </div>`;
    el.querySelectorAll('.pick').forEach(p => p.onclick = () => {
      el.querySelectorAll('.pick').forEach(x => x.classList.remove('on'));
      p.classList.add('on');
      p.querySelector('input').checked = true;
    });
    el.querySelector('#bk-submit').onclick = () => Customer.submitBooking(el);
  },

  async submitBooking(el, force = false) {
    const itemId = +el.querySelector('input[name=svc]:checked').value;
    const body = {
      item_id: itemId,
      date: el.querySelector('#bk-date').value,
      time: el.querySelector('#bk-time').value,
      note: el.querySelector('#bk-note').value.trim(),
      force,
    };
    if (!body.date || !body.time) { toast('请选择日期和时间'); return; }
    try {
      const r = await API.call('/api/c/orders', { method: 'POST', body });
      toast('预约成功，请等待服务员确认', true);
      if (r.order && r.order.conflict_warning) {
        setTimeout(() => toast('提示：该时段与服务员其他预约相近，请留意确认'), 800);
      }
      switchTab('orders');
    } catch (e) {
      const d = e.data || {};
      if (d.conflicts) { Customer.showConflict(el, d, body); return; }
      toast(e.message);
    }
  },

  showConflict(el, data, body) {
    const sugg = (data.suggestions || []).map(s =>
      `<button class="btn btn-ghost btn-small" data-slot="${s}">改约 ${s}</button>`).join(' ');
    openModal('时间冲突提醒', `
      <div class="warn-box">您的服务员这个时间段已被其他顾客预约：</div>
      ${(data.conflicts || []).map(c => `
        <div class="card" style="margin:0 0 8px">
          <b>${esc(c.sched_start)} ~ ${c.sched_end.slice(11)}</b><br>
          <span class="muted">${esc(c.item_name)}（其他顾客）</span>
        </div>`).join('')}
      ${data.suggestions && data.suggestions.length ? `
        <div class="info-box">当天较空闲的时段：${sugg}</div>` : ''}
      <div class="muted small">可点击上方按钮改约，或坚持原时间提交（管理员会协助协调）。</div>`, {
      extraButtons: `<button class="btn" id="cf-force">仍按此时间预约</button>`,
      onMount(box) {
        box.querySelectorAll('[data-slot]').forEach(b => b.onclick = () => {
          el.querySelector('#bk-time').value = b.dataset.slot;
          closeModal();
          toast('已为您选择 ' + b.dataset.slot + '，正在提交…');
          Customer.submitBooking(el, false);
        });
        const f = box.querySelector('#cf-force');
        if (f) f.onclick = () => { closeModal(); Customer.submitBooking(el, true); };
      },
    });
  },

  async renderMoney(el) {
    el.innerHTML = '<div class="loading">加载中…</div>';
    const { transactions, balance_cents } = await API.call('/api/c/transactions');
    el.innerHTML = `
      <div class="stats">
        <div class="stat ${balance_cents < 0 ? 'warn' : 'good'}">
          <div class="num">¥${fmtMoney(balance_cents)}</div>
          <div class="lbl">账户余额 ${balance_cents < 0 ? '（欠费，请联系客服充值）' : ''}</div>
        </div>
      </div>
      ${transactions.length ? transactions.map(t => `
        <div class="card order-card" style="border-left-color:${t.delta_cents >= 0 ? 'var(--green)' : 'var(--red)'}">
          <div class="head">
            <b>${esc(KIND[t.kind] || t.kind)}</b>
            <span class="${t.delta_cents >= 0 ? 'money-plus' : 'money-minus'}">
              ${t.delta_cents >= 0 ? '+' : ''}${fmtMoney(t.delta_cents)}</span>
          </div>
          <div class="meta">${esc(t.created_at)} · 余额 ¥${fmtMoney(t.balance_after)}</div>
          ${t.note ? `<div class="meta">${esc(t.note)}</div>` : ''}
        </div>`).join('') : '<div class="empty">暂无账户明细</div>'}`;
  },

  async renderMe(el) {
    const me = await API.call('/api/me');
    const s = await API.call('/api/c/summary');
    el.innerHTML = `
      <div class="card"><h3>我的信息</h3>
        <div>姓名：<b>${esc(me.name)}</b></div>
        <div>手机号：${esc(me.phone)}</div>
        <div>居住地址：${esc(me.address || '未填写')}</div>
      </div>
      ${s.worker ? `
      <div class="card"><h3>我的服务员</h3>
        <div class="who" style="font-size:18px;font-weight:700">${esc(s.worker.name)}</div>
        <div class="meta muted">电话 ${esc(s.worker.phone)}</div>
        <div class="contact-btns">
          <a class="btn btn-green" href="tel:${esc(s.worker.phone)}">📞 拨打电话</a>
          <a class="btn btn-ghost" href="sms:${esc(s.worker.phone)}">💬 发短信</a>
        </div>
      </div>` : '<div class="card">管理员还未给您指派服务员</div>'}
      ${s.next_order ? `<div class="info-box">下一次服务：${esc(s.next_order.sched_start)} ${esc(s.next_order.item_name)}</div>` : ''}
      <div class="card center muted small">${esc(CONF.app_name)} ${esc(CONF.version)}</div>`;
  },
};
