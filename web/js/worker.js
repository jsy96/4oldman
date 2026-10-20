/* 服务员端：今日待办（确认/完成/异常）/ 订单查询 / AI 行程路线 / 顾客联系。 */
const Worker = {

  async renderTodo(el) {
    el.innerHTML = '<div class="loading">加载中…</div>';
    const [ov, tomorrow, today] = await Promise.all([
      API.call('/api/w/overview'),
      API.call('/api/w/orders?scope=tomorrow'),
      API.call('/api/w/orders?scope=today'),
    ]);
    const pending = tomorrow.orders.filter(o => o.status === 'pending');
    const rerender = () => Worker.renderTodo(el);
    el.innerHTML = `
      <div class="stats">
        <div class="stat"><div class="num">${ov.today_orders}</div><div class="lbl">今日订单</div></div>
        <div class="stat ${ov.to_confirm ? 'warn' : ''}"><div class="num">${ov.to_confirm}</div><div class="lbl">明日待确认</div></div>
        <div class="stat"><div class="num">${ov.month_done}</div><div class="lbl">本月完成</div></div>
        <div class="stat good"><div class="num">¥${fmtMoney(ov.month_pay_cents)}</div><div class="lbl">本月酬金(已完成)</div></div>
      </div>
      <div class="card">
        <h3>明天待确认 <span class="sub">${pending.length ? '请在前一天 20:00 前确认' : '全部已确认 ✔'}</span>
          ${pending.length ? '<button class="btn btn-green btn-small" id="confirm-all">一键确认全部</button>' : ''}
        </h3>
        ${pending.length ? pending.map(o => `
          <div class="order-card card ${o.status}" style="margin-bottom:8px">
            <div class="head"><span class="time">${esc(o.sched_start.slice(11))}</span>${chip(o.status)}</div>
            <div class="who">${esc(o.customer_name)} · ${esc(o.item_name)}</div>
            <div class="meta">${esc(o.customer_address || '')}</div>
            <div class="contact-btns">
              <a class="btn btn-green btn-small" href="tel:${esc(o.customer_phone)}">📞 打电话</a>
              <a class="btn btn-ghost btn-small" href="sms:${esc(o.customer_phone)}">💬 短信</a>
              <button class="btn btn-small" data-confirm="${o.id}">确认上门</button>
            </div>
          </div>`).join('') : '<div class="empty">明天没有待确认的订单</div>'}
      </div>
      <div class="card">
        <h3>今日订单</h3>
        ${today.orders.length ? today.orders.map(o => Worker.orderCard(o, true)).join('')
          : '<div class="empty">今天没有订单</div>'}
      </div>`;
    el.querySelectorAll('[data-confirm]').forEach(b => b.onclick = async () => {
      try {
        await API.call(`/api/w/orders/${b.dataset.confirm}/confirm`, { method: 'POST' });
        toast('已确认', true);
        rerender();
      } catch (e) { toast(e.message); }
    });
    const all = el.querySelector('#confirm-all');
    if (all) all.onclick = async () => {
      try {
        const r = await API.call('/api/w/confirm_all', { method: 'POST', body: {} });
        toast(`已确认 ${r.count} 单`, true);
        rerender();
      } catch (e) { toast(e.message); }
    };
    Worker.wireOrderButtons(el, rerender);
  },

  orderCard(o, withActions) {
    const actions = [];
    if (o.status === 'pending') actions.push(`<button class="btn btn-small" data-confirm="${o.id}">确认上门</button>`);
    if (o.status === 'confirmed') {
      actions.push(`<button class="btn btn-green btn-small" data-complete="${o.id}">完成服务</button>`);
      actions.push(`<button class="btn btn-danger btn-small" data-exc="${o.id}">上报异常</button>`);
    }
    return `
      <div class="order-card card ${o.status}" style="margin-bottom:8px">
        <div class="head"><span class="time">${esc(o.sched_start.slice(11))} ~ ${esc(o.sched_end.slice(11))}</span>${chip(o.status)}</div>
        <div class="who">${esc(o.customer_name)} · ${esc(o.item_name)}</div>
        <div class="meta">📍 ${esc(o.customer_address || '地址未填写')}</div>
        ${o.exception_type ? `<div class="meta">⚠ ${esc(o.exception_type)} ${esc(o.exception_note || '')}</div>` : ''}
        <div class="contact-btns">
          <a class="btn btn-green btn-small" href="tel:${esc(o.customer_phone)}">📞 打电话</a>
          <a class="btn btn-ghost btn-small" href="sms:${esc(o.customer_phone)}">💬 短信</a>
          ${actions.join('')}
        </div>
      </div>`;
  },

  wireOrderButtons(el, rerender) {
    el.querySelectorAll('[data-confirm]').forEach(b => b.onclick = async () => {
      try {
        await API.call(`/api/w/orders/${b.dataset.confirm}/confirm`, { method: 'POST' });
        toast('已确认', true);
        rerender();
      } catch (e) { toast(e.message); }
    });
    el.querySelectorAll('[data-complete]').forEach(b => b.onclick = () => {
      openModal('完成服务', `
        <p>确认已完成该订单？完成后将自动从顾客账户扣款。</p>
        <label class="fl">服务备注（选填）</label>
        <textarea id="done-note" placeholder="例如：老人状态良好，下次建议助浴"></textarea>`, {
        okText: '确认完成',
        onOk: async () => {
          try {
            await API.call(`/api/w/orders/${b.dataset.complete}/complete`, {
              method: 'POST', body: { note: document.getElementById('done-note').value.trim() },
            });
            toast('已完成并扣款', true);
            closeModal();
            rerender();
          } catch (e) { toast(e.message); }
        },
      });
    });
    el.querySelectorAll('[data-exc]').forEach(b => b.onclick = () => {
      const types = ['顾客不在家', '顾客临时取消', '顾客身体原因', '只完成部分服务', '地址有误', '其他'];
      openModal('上报异常', `
        <label class="fl">异常类型</label>
        <select id="exc-type">${types.map(t => `<option>${t}</option>`).join('')}</select>
        <label class="fl">情况说明</label>
        <textarea id="exc-note" placeholder="请描述具体情况，便于管理员处理"></textarea>`, {
        okText: '提交',
        onOk: async () => {
          try {
            await API.call(`/api/w/orders/${b.dataset.exc}/exception`, {
              method: 'POST',
              body: { type: document.getElementById('exc-type').value,
                      note: document.getElementById('exc-note').value.trim() },
            });
            toast('已上报，等待管理员处理', true);
            closeModal();
            rerender();
          } catch (e) { toast(e.message); }
        },
      });
    });
  },

  async renderOrders(el, scope = 'upcoming') {
    el.innerHTML = `
      <div class="seg" id="wk-scope">
        <button data-s="upcoming" class="${scope === 'upcoming' ? 'on' : ''}">未来7天</button>
        <button data-s="today" class="${scope === 'today' ? 'on' : ''}">今日</button>
        <button data-s="history" class="${scope === 'history' ? 'on' : ''}">历史订单</button>
      </div>
      <div id="wk-list" style="margin-top:12px"><div class="loading">加载中…</div></div>`;
    el.querySelectorAll('#wk-scope button').forEach(b => b.onclick = () => Worker.renderOrders(el, b.dataset.s));
    const list = el.querySelector('#wk-list');
    const { orders } = await API.call(`/api/w/orders?scope=${scope}`);
    if (!orders.length) { list.innerHTML = '<div class="empty">没有订单</div>'; return; }
    let lastDate = '', groupIdx = 0;
    list.innerHTML = orders.map(o => {
      const d = o.sched_start.slice(0, 10);
      let head = '';
      if (d !== lastDate) {
        groupIdx += 1;
        head = `<div class="date-group">${d === todayStr() ? '今天 · ' : ''}${d}</div>`;
        lastDate = d;
      }
      const card = Worker.orderCard(o).replace('class="card order-card',
                                               `class="card order-card${groupIdx % 2 ? ' date-alt' : ''}`);
      return head + card;
    }).join('');
    Worker.wireOrderButtons(list, () => Worker.renderOrders(el, scope));
  },

  async renderRoute(el) {
    el.innerHTML = `
      <div class="card">
        <h3>AI 行程路线 <span class="sub">骑电瓶车 · 按预约时间排程/天气/电量</span></h3>
        <div class="row">
          <input type="date" id="rt-date" value="${tomorrowStr()}" style="max-width:180px">
          <button class="btn" id="rt-go">查看路线</button>
        </div>
      </div>
      <div class="grid2" id="rt-body"><div class="loading">加载中…</div></div>`;
    el.querySelector('#rt-go').onclick = () => Worker.loadRoute(el);
    Worker.loadRoute(el);
  },

  async loadRoute(el) {
    const date = el.querySelector('#rt-date').value;
    const body = el.querySelector('#rt-body');
    body.innerHTML = '<div class="loading">正在规划…</div>';
    const plan = await API.call(`/api/w/route?date=${date}`);
    const w = plan.weather;
    const wx = w
      ? `降水 ${w.precip_mm}mm${w.snow_cm ? ` · 雪 ${w.snow_cm}cm` : ''} · ${w.tmin}~${w.tmax}℃ · ${w.text}`
      : '天气数据暂不可用（离线或历史日期）';
    body.innerHTML = `
      <div>
        <div class="card">
          <h3>当日天气</h3>
          <div>${wx}</div>
          <div class="info-box" style="margin-top:8px">${esc(plan.weather_note || '')}</div>
        </div>
        <div class="card">
          <h3>电量预估</h3>
          <div class="stat" style="box-shadow:none;padding:6px 0;text-align:left">
            <div class="num">${plan.battery ? plan.battery.use_pct + '%' : '—'}</div>
            <div class="lbl">${plan.battery ? esc(plan.battery.note) : ''}</div>
          </div>
        </div>
        <div class="card">
          <h3>路线总览</h3>
          <div>总里程 <b>${plan.total_km} km</b> · 服务 <b>${plan.stops.length}</b> 单</div>
          <div class="muted small">距离来源：${esc(plan.distance_source || '直线×1.35估算')}</div>
          <div class="muted small">午餐预留 ${esc(plan.lunch.start)}-${esc(plan.lunch.end)}${plan.lunch.used ? '（已自动避开）' : ''}</div>
          ${plan.warnings.length ? `<div class="warn-box">${plan.warnings.map(esc).join('<br>')}</div>` : ''}
        </div>
      </div>
      <div>
        <div class="card" style="padding:8px"><div id="rt-map" class="map" style="height:320px"></div></div>
        <div class="card"><h3>顺序与时间安排</h3>
          ${plan.stops.length ? plan.stops.map(s => `
            <div class="stop">
              <div class="seq">${s.seq}</div>
              <div class="body">
                <div class="tm">${s.arrive} 到达 <small>（${s.service_start} 开始 · ${s.depart} 结束）</small></div>
                <div><b>${esc(s.customer)}</b> · ${esc(s.item)} ${chip(s.status)}</div>
                <div class="muted small">📍 ${esc(s.address)} · 预约 ${esc(s.sched.slice(11))}</div>
                <div class="contact-btns">
                  <a class="btn btn-green btn-small" href="tel:${esc(s.phone)}">📞 打电话</a>
                  <a class="btn btn-ghost btn-small" href="sms:${esc(s.phone)}">💬 短信</a>
                </div>
              </div>
            </div>`).join('') : '<div class="empty">当天暂无已确认订单</div>'}
        </div>
      </div>`;
    if ((plan.markers || []).length) {
      setTimeout(() => {
        if (!document.getElementById('rt-map')) return;  // 用户已切换页面
        const map = Maps.create('rt-map');
        const pts = [];
        plan.markers.forEach(m => {
          pts.push([m.lat, m.lng]);
          L.marker([m.lat, m.lng], { icon: Maps.pin(m.home ? '🏠' : m.seq, m.home ? 'home' : '') })
            .addTo(map)
            .bindPopup(m.home ? plan.start_name
              : `<b>${m.seq}. ${esc(m.customer)}</b><br>${esc(m.item)}<br>${esc(m.address)}`);
        });
        if (pts.length > 1) L.polyline(pts, { color: '#2563eb', weight: 4, dashArray: '8 8' }).addTo(map);
        map.fitBounds(pts, { padding: [30, 30] });
      }, 60);
    }
  },

  async renderCustomers(el) {
    el.innerHTML = '<div class="loading">加载中…</div>';
    const { customers } = await API.call('/api/w/customers');
    el.innerHTML = customers.map(c => `
      <div class="card order-card confirmed">
        <div class="who">${esc(c.name)}</div>
        <div class="meta">📍 ${esc(c.address || '地址未填写')}</div>
        <div class="meta">余额 ¥${fmtMoney(c.balance_cents)}${c.balance_cents < 0 ? '（欠费）' : ''}</div>
        <div class="contact-btns">
          <a class="btn btn-green" href="tel:${esc(c.phone)}">📞 打电话</a>
          <a class="btn btn-ghost" href="sms:${esc(c.phone)}">💬 发短信</a>
        </div>
      </div>`).join('') || '<div class="empty">暂无固定服务的顾客</div>';
  },
};
