/* 顾客端：订单历史 / 预约服务（时长计价+一键冲突检查）/ 账户明细 / 我的。 */
const Customer = {

  async renderOrders(el) {
    el.innerHTML = '<div class="loading">加载中…</div>';
    const { orders } = await API.call('/api/c/orders');
    if (!orders.length) { el.innerHTML = '<div class="empty">还没有订单，去“预约服务”下一单吧</div>'; return; }
    let alt = false, lastDate = null;
    el.innerHTML = orders.map(o => {
      const d = o.sched_start.slice(0, 10);
      let head = '';
      if (d !== lastDate) {  // 换日期：翻一次底色 + 加日期标题
        alt = !alt; lastDate = d;
        head = `<div class="date-group">${d === todayStr() ? '今天 · ' : ''}${d}</div>`;
      }
      return head + `
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
    const [{ items }, sum] = await Promise.all([
      API.call('/api/c/services'), API.call('/api/c/summary')]);
    const balance = sum.balance_cents;
    const today = todayStr();
    const times = [];
    for (let h = 8; h <= 17; h++) for (const m of [0, 30]) {
      if (h === 17 && m) continue;
      times.push(`${pad(h)}:${pad(m)}`);
    }
    const state = { item: items[0], dur: items[0].minutes };
    const durOpts = it => [...new Set([it.minutes, 30, 60, 90, 120, 150, 180, 240])]
      .filter(d => d >= 15 && d <= 480).sort((a, b) => a - b);
    const durLabel = d => `${d} 分钟（${(d / 60).toFixed(1).replace(/\.0$/, '')} 小时）`;
    const amount = () => Math.round(state.item.unit_price_cents * state.dur / 60);
    const hoursText = () => (state.dur / 60).toFixed(2).replace(/0+$/, '').replace(/\.$/, '');

    el.innerHTML = `
      <div class="card">
        <h3>① 选择服务项目</h3>
        <div class="pick-list" id="item-list">
          ${items.map((i, n) => `
            <label class="pick${n === 0 ? ' on' : ''}">
              <input type="radio" name="svc" value="${i.id}" ${n === 0 ? 'checked' : ''}>
              <div><div class="t">${esc(i.name)}</div>
              <div class="d">单价 ¥${fmtMoney(i.unit_price_cents)}/小时 · 默认 ${i.minutes} 分钟</div></div>
            </label>`).join('')}
        </div>
        <h3 style="margin-top:16px">② 选择时长与时间</h3>
        <div class="frow">
          <div><label class="fl">服务时长</label><select id="bk-dur"></select></div>
          <div><label class="fl">日期</label><input type="date" id="bk-date" min="${today}" value="${today}"></div>
        </div>
        <div class="frow">
          <div><label class="fl">开始时间</label><select id="bk-time">${times.map(t => `<option>${t}</option>`).join('')}</select></div>
          <div><label class="fl">本次金额</label>
            <div style="padding-top:9px"><b id="bk-amount" style="font-size:20px;color:var(--primary)">¥0.00</b>
            <div class="muted small" id="bk-calc"></div></div>
          </div>
        </div>
        <div id="bk-check" class="info-box" hidden></div>
        <button class="btn btn-plain" id="bk-check-btn" style="margin-top:8px">🔍 一键检查时间是否冲突</button>
        <div id="bk-balance" class="muted small" style="margin-top:10px"></div>
        <label class="fl">备注（选填）</label>
        <textarea id="bk-note" placeholder="例如：家住3楼无电梯、需要带浴凳等"></textarea>
        <button class="btn btn-lg" id="bk-submit" style="margin-top:16px">确认预约</button>
        <div class="muted small" style="margin-top:8px">同一服务员前后两单需间隔至少 30 分钟；账户余额不足时无法下单。</div>
      </div>`;

    const durSel = el.querySelector('#bk-dur');
    const checkBox = el.querySelector('#bk-check');
    const fillDur = () => {
      durSel.innerHTML = durOpts(state.item).map(d =>
        `<option value="${d}" ${d === state.dur ? 'selected' : ''}>${durLabel(d)}</option>`).join('');
    };
    const clearCheck = () => { checkBox.hidden = true; checkBox.textContent = ''; };
    const refresh = () => {
      const price = amount();
      el.querySelector('#bk-amount').textContent = '¥' + fmtMoney(price);
      el.querySelector('#bk-calc').textContent =
        `¥${fmtMoney(state.item.unit_price_cents)}/小时 × ${hoursText()} 小时`;
      const enough = balance >= price;
      el.querySelector('#bk-balance').innerHTML = enough
        ? `账户余额 ¥${fmtMoney(balance)}`
        : `<span class="warn-box" style="display:block">余额不足：本次需 ¥${fmtMoney(price)}，`
          + `当前余额 ¥${fmtMoney(balance)}，请联系管理员充值后再预约</span>`;
      const btn = el.querySelector('#bk-submit');
      btn.disabled = !enough;
      btn.textContent = enough ? '确认预约' : '余额不足，无法预约';
    };

    el.querySelectorAll('.pick').forEach(p => p.onclick = () => {
      el.querySelectorAll('.pick').forEach(x => x.classList.remove('on'));
      p.classList.add('on');
      p.querySelector('input').checked = true;
      state.item = items.find(i => i.id === +p.querySelector('input').value);
      state.dur = state.item.minutes;
      fillDur(); refresh(); clearCheck();
    });
    durSel.onchange = () => { state.dur = +durSel.value; refresh(); clearCheck(); };
    el.querySelector('#bk-date').onchange = clearCheck;
    el.querySelector('#bk-time').onchange = clearCheck;
    el.querySelector('#bk-check-btn').onclick = () => Customer.checkConflict(el, state);
    el.querySelector('#bk-submit').onclick = () => Customer.submitBooking(el, state);
    fillDur(); refresh();
  },

  async checkConflict(el, st) {
    const box = el.querySelector('#bk-check');
    const date = el.querySelector('#bk-date').value;
    const time = el.querySelector('#bk-time').value;
    if (!date || !time) { toast('请选择日期和时间'); return; }
    box.hidden = false;
    box.className = 'info-box';
    box.textContent = '检查中…';
    try {
      const r = await API.call('/api/c/check-conflict'
        + `?item_id=${st.item.id}&date=${date}&time=${time}&duration=${st.dur}`);
      if (r.available) {
        box.className = 'info-box';
        box.innerHTML = `✅ ${date} ${time} 起 ${r.duration_minutes} 分钟，该时段可预约`
          + `（金额 ¥${fmtMoney(r.price_cents)}）`;
      } else {
        box.className = 'warn-box';
        box.innerHTML = `⚠ ${date} ${time} 与已有预约冲突（前后需间隔 30 分钟以上）：<br>`
          + (r.conflicts || []).map(c =>
              `· ${esc(c.sched_start)} ~ ${esc(c.sched_end.slice(11))} ${esc(c.item_name)}`).join('<br>')
          + ((r.suggestions || []).length
              ? `<br>建议时段：${r.suggestions.map(s => `<button class="btn btn-ghost btn-small" data-slot="${s}">${s}</button>`).join(' ')}`
              : '<br>当天没有其它空闲时段，请换一天试试');
        box.querySelectorAll('[data-slot]').forEach(b => b.onclick = () => {
          el.querySelector('#bk-time').value = b.dataset.slot;
          Customer.checkConflict(el, st);
        });
      }
    } catch (e) {
      box.className = 'warn-box';
      box.textContent = e.message;
    }
  },

  async submitBooking(el, st) {
    const date = el.querySelector('#bk-date').value;
    const time = el.querySelector('#bk-time').value;
    if (!date || !time) { toast('请选择日期和时间'); return; }
    const body = {
      item_id: st.item.id, date, time, duration_minutes: st.dur,
      note: el.querySelector('#bk-note').value.trim(),
    };
    try {
      await API.call('/api/c/orders', { method: 'POST', body });
      toast('预约成功，请等待服务员确认', true);
      switchTab('orders');
    } catch (e) {
      const d = e.data || {};
      if (d.conflicts) { Customer.showConflict(el, st, d); return; }
      toast(e.message);
    }
  },

  showConflict(el, st, data) {
    const sugg = (data.suggestions || []).map(s =>
      `<button class="btn btn-ghost btn-small" data-slot="${s}">改约 ${s}</button>`).join(' ');
    openModal('时间冲突', `
      <div class="warn-box">该时段与您服务员的其它预约冲突（前后需间隔 30 分钟以上）：</div>
      ${(data.conflicts || []).map(c => `
        <div class="card" style="margin:0 0 8px">
          <b>${esc(c.sched_start)} ~ ${esc(c.sched_end.slice(11))}</b><br>
          <span class="muted">${esc(c.item_name)}（其他顾客）</span>
        </div>`).join('')}
      ${sugg ? `<div class="info-box">当天较空闲的时段：${sugg}</div>`
             : '<div class="info-box">当天没有其它空闲时段，请换一天试试。</div>'}
      <div class="muted small">请选择其它时段后再提交预约。</div>`, {
      okText: '知道了',
      onMount(box) {
        box.querySelectorAll('[data-slot]').forEach(b => b.onclick = () => {
          el.querySelector('#bk-time').value = b.dataset.slot;
          closeModal();
          Customer.checkConflict(el, st);
        });
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
