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
              <button class="btn btn-plain btn-small" data-reschedule="${o.id}"
                data-cur="${esc(o.sched_start)}" data-name="${esc(o.customer_name)}"
                data-item="${esc(o.item_name)}" data-min="${o.minutes}">改期</button>
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

  orderCard(o, withActions, alt) {
    const actions = [];
    if (o.status === 'pending') actions.push(`<button class="btn btn-small" data-confirm="${o.id}">确认上门</button>`);
    if (o.status === 'confirmed') {
      actions.push(`<button class="btn btn-green btn-small" data-complete="${o.id}">完成服务</button>`);
      actions.push(`<button class="btn btn-danger btn-small" data-exc="${o.id}">上报异常</button>`);
    }
    if (['pending', 'confirmed', 'exception'].includes(o.status)) {
      actions.push(`<button class="btn btn-plain btn-small" data-reschedule="${o.id}"
        data-cur="${esc(o.sched_start)}" data-name="${esc(o.customer_name)}"
        data-item="${esc(o.item_name)}" data-min="${o.minutes}">改期</button>`);
    }
    return `
      <div class="order-card card ${o.status}${alt ? ' date-alt' : ''}" style="margin-bottom:8px">
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

  openRescheduleModal(o, rerender) {
    openModal('修改服务时间', `
      <p>顾客：<b>${esc(o.customer_name)}</b> · ${esc(o.item_name)}（${o.minutes}分钟）</p>
      <label class="fl">新的预约时间</label>
      <input type="datetime-local" id="wr-time" value="${esc(o.sched_start.replace(' ', 'T'))}">
      <div id="wr-err" style="margin-top:8px"></div>`, {
      okText: '保存',
      onOk: async () => {
        const v = document.getElementById('wr-time').value.replace('T', ' ');
        const err = document.getElementById('wr-err');
        if (!v) { toast('请选择时间'); return false; }
        try {
          await API.call(`/api/w/orders/${o.id}/reschedule`, { method: 'POST', body: { start: v } });
          toast('已改期，订单恢复为已确认', true);
          closeModal();
          rerender();
        } catch (e) {
          const d = e.data || {};
          if (d.conflicts) {
            err.innerHTML = `<div class="warn-box">新时间与其它订单冲突（需间隔30分钟以上）</div>`
              + (d.suggestions && d.suggestions.length
                ? `<div class="info-box">可用时段：${d.suggestions.map(s =>
                    `<button type="button" class="btn btn-ghost btn-small" data-wslot="${s}">${s}</button>`).join(' ')}</div>`
                : '');
            err.querySelectorAll('[data-wslot]').forEach(b => b.onclick = () => {
              const day = document.getElementById('wr-time').value.slice(0, 10);
              document.getElementById('wr-time').value = `${day}T${b.dataset.wslot}`;
            });
          } else {
            err.innerHTML = `<div class="warn-box">${esc(e.message)}</div>`;
          }
        }
        return false;
      },
    });
  },

  wireOrderButtons(el, rerender) {
    el.querySelectorAll('[data-reschedule]').forEach(b => b.onclick = () => Worker.openRescheduleModal({
      id: b.dataset.reschedule, sched_start: b.dataset.cur,
      customer_name: b.dataset.name, item_name: b.dataset.item,
      minutes: b.dataset.min,
    }, rerender));
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

  async renderOrders(el, scope = 'today') {
    const TABS = [['today', '今天'], ['tomorrow', '明天'], ['day_after', '后天'],
                  ['future', '未来'], ['history', '历史订单']];
    el.innerHTML = `
      <div class="seg" id="wk-scope">
        ${TABS.map(([k, label]) =>
          `<button data-s="${k}" class="${scope === k ? 'on' : ''}">${label}</button>`).join('')}
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
      return head + Worker.orderCard(o, true, groupIdx % 2 === 0);
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
          <button class="btn btn-plain" id="rt-check-btn" style="margin-top:10px">🔍 一键检查时间安排是否合理</button>
        </div>
        <div id="rt-check"></div>
      </div>
      <div>
        <div class="card" style="padding:8px"><div id="rt-map" class="map" style="height:320px"></div></div>
        <div class="card"><h3>顺序与时间安排</h3>
          ${plan.stops.length ? plan.stops.map(s => `
            ${s.seq > 1 && plan.legs[s.seq - 1]
              ? `<div class="gap-line">⏱ 与上一单间隔 ${plan.legs[s.seq - 1].available_min} 分钟</div>` : ''}
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
    const checkBtn = body.querySelector('#rt-check-btn');
    if (checkBtn) checkBtn.onclick = () => Worker.renderCheck(plan);
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
        // 每段路标注：预计骑行时间 / 两单预留间隔
        (plan.legs || []).forEach(l => {
          if (l.from_lat == null) return;
          L.marker([(l.from_lat + l.to_lat) / 2, (l.from_lng + l.to_lng) / 2], {
            icon: L.divIcon({
              className: '',
              html: `<div class="leg-label">≈${l.minutes}分 · 间隔${l.available_min}分</div>`,
              iconSize: [0, 0],
            }),
            interactive: false,
          }).addTo(map);
        });
        map.fitBounds(pts, { padding: [30, 30] });
      }, 60);
    }
  },

  renderCheck(plan) {
    const box = document.getElementById('rt-check');
    if (!box) return;
    const c = plan.check;
    if (!c || !c.legs.length) {
      box.innerHTML = '<div class="card"><div class="empty">当天不足两单，无需检查间隔</div></div>';
      return;
    }
    const badge = st => st === 'ok' ? '<span class="chip green">合理</span>'
      : st === 'tight' ? '<span class="chip amber">偏紧</span>' : '<span class="chip red">会迟到</span>';
    box.innerHTML = `
      <div class="card">
        <h3>时间安排检查 ${c.reasonable
          ? '<span class="chip green">✅ 全部合理</span>'
          : `<span class="chip red">迟到 ${c.late} 段</span> <span class="chip amber">偏紧 ${c.tight} 段</span>`}</h3>
        ${c.legs.map(l => `
          <div class="stop">
            <div class="seq" style="background:${l.status === 'ok' ? 'var(--green)' : l.status === 'tight' ? 'var(--amber)' : 'var(--red)'}">${l.seq}</div>
            <div class="body">
              <div><b>${esc(l.from_label)} → ${esc(l.to_label)}</b> ${badge(l.status)}</div>
              <div class="muted small">骑行 ${l.km} km · 预计 ${l.minutes} 分钟 · 间隔 ${l.available_min} 分钟 · 需 ≥ ${l.required_min} 分钟</div>
            </div>
          </div>`).join('')}
      </div>`;
    box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
