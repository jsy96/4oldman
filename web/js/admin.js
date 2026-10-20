/* 管理端：统计 / 订单管理（含异常处理）/ 人员管理 / 服务项目 / 批量充值 / 酬金发放。 */
const Admin = {
  cache: { workers: [], customers: [], items: [] },

  async loadRefs() {
    const [w, c, i] = await Promise.all([
      API.call('/api/a/users?role=worker'),
      API.call('/api/a/users?role=customer'),
      API.call('/api/a/items'),
    ]);
    this.cache = { workers: w.users, customers: c.users, items: i.items };
  },

  /* ============ 数据统计 ============ */
  async renderStats(el) {
    const first = todayStr().slice(0, 8) + '01';
    await this.loadRefs();
    el.innerHTML = `
      <div class="card">
        <h3>订单统计</h3>
        <div class="frow">
          <div><label class="fl">开始日期</label><input type="date" id="st-from" value="${first}"></div>
          <div><label class="fl">结束日期</label><input type="date" id="st-to" value="${todayStr()}"></div>
        </div>
        <div class="frow">
          <div><label class="fl">服务员</label><select id="st-worker">
            <option value="">全部</option>
            ${this.cache.workers.map(w => `<option value="${w.id}">${esc(w.name)}</option>`).join('')}</select></div>
          <div><label class="fl">顾客</label><select id="st-customer">
            <option value="">全部</option>
            ${this.cache.customers.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></div>
        </div>
        <label class="fl">服务项目</label>
        <select id="st-item"><option value="">全部</option>
          ${this.cache.items.map(i => `<option value="${i.id}">${esc(i.name)}</option>`).join('')}</select>
        <div class="row" style="margin-top:14px">
          <button class="btn" id="st-go">查询</button>
          <button class="btn btn-ghost" id="st-csv">导出 CSV</button>
        </div>
      </div>
      <div id="st-body"></div>`;
    const qs = () => `from=${el.querySelector('#st-from').value}&to=${el.querySelector('#st-to').value}` +
      `&worker=${el.querySelector('#st-worker').value}&customer=${el.querySelector('#st-customer').value}` +
      `&item=${el.querySelector('#st-item').value}`;
    el.querySelector('#st-go').onclick = () => Admin.loadStats(el, qs());
    el.querySelector('#st-csv').onclick = () => Admin.exportCsv(qs());
    this.loadStats(el, qs());
  },

  async loadStats(el, q) {
    const body = el.querySelector('#st-body');
    body.innerHTML = '<div class="loading">统计中…</div>';
    const r = await API.call('/api/a/stats?' + q);
    const s = r.summary;
    body.innerHTML = `
      <div class="stats">
        <div class="stat"><div class="num">${s.total}</div><div class="lbl">订单总数</div></div>
        <div class="stat good"><div class="num">${s.completed}</div><div class="lbl">已完成</div></div>
        <div class="stat ${s.exception ? 'warn' : ''}"><div class="num">${s.exception}</div><div class="lbl">异常</div></div>
        <div class="stat"><div class="num">${s.cancelled}</div><div class="lbl">已取消</div></div>
        <div class="stat good"><div class="num">¥${fmtMoney(s.revenue_cents)}</div><div class="lbl">服务收入</div></div>
        <div class="stat"><div class="num">¥${fmtMoney(s.refund_cents)}</div><div class="lbl">退款</div></div>
        <div class="stat"><div class="num">¥${fmtMoney(s.wage_cents)}</div><div class="lbl">酬金合计</div></div>
        <div class="stat ${s.wage_unpaid_cents ? 'warn' : ''}"><div class="num">¥${fmtMoney(s.wage_unpaid_cents)}</div><div class="lbl">未发酬金</div></div>
      </div>
      <div id="st-groups"></div>`;
    const grp = (title, rows, moneyKey) => `
      <div class="card"><h3>${title}</h3>
        ${rows.length ? `<div class="tblwrap"><table class="tbl">
          <tr><th>名称</th><th>订单数</th><th>完成数</th><th>收入</th>${moneyKey === 'wage_cents' ? '<th>酬金</th>' : ''}</tr>
          ${rows.map(x => `<tr><td>${esc(x.name)}</td><td>${x.total}</td><td>${x.completed}</td>
            <td>¥${fmtMoney(x.revenue_cents)}</td>${moneyKey === 'wage_cents' ? `<td>¥${fmtMoney(x.wage_cents)}</td>` : ''}</tr>`).join('')}
        </table></div>` : '<div class="empty">区间内无订单</div>'}
      </div>`;
    el.querySelector('#st-groups').innerHTML =
      grp('按服务员', r.by_worker, 'wage_cents') + grp('按服务项目', r.by_item, 'revenue_cents') +
      grp('按月份', r.by_month, 'revenue_cents');
  },

  async exportCsv(q) {
    try {
      const res = await fetch(API.url('/api/a/stats/export.csv?' + q),
        { headers: { Authorization: 'Bearer ' + API.token } });
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = '订单统计.csv';
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { toast('导出失败'); }
  },

  /* ============ 订单管理（含异常处理） ============ */
  async renderOrders(el) {
    await this.loadRefs();
    const first = todayStr().slice(0, 8) + '01';
    el.innerHTML = `
      <div class="card">
        <h3>订单管理 <button class="btn btn-small" id="od-new">➕ 代顾客下单</button></h3>
        <div class="frow">
          <div><label class="fl">开始</label><input type="date" id="od-from" value="${first}"></div>
          <div><label class="fl">结束</label><input type="date" id="od-to" value="${todayStr().slice(0, 8)}31"></div>
        </div>
        <div class="frow">
          <div><label class="fl">状态</label><select id="od-status">
            <option value="">全部</option>
            <option value="pending">待确认</option><option value="confirmed">已确认</option>
            <option value="completed">已完成</option><option value="exception" selected>异常</option>
            <option value="cancelled">已取消</option></select></div>
          <div><label class="fl">服务员</label><select id="od-worker">
            <option value="">全部</option>
            ${this.cache.workers.map(w => `<option value="${w.id}">${esc(w.name)}</option>`).join('')}</select></div>
        </div>
        <div class="frow">
          <div><label class="fl">顾客</label><select id="od-customer">
            <option value="">全部</option>
            ${this.cache.customers.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></div>
          <div><label class="fl">服务项目</label><select id="od-item">
            <option value="">全部</option>
            ${this.cache.items.map(i => `<option value="${i.id}">${esc(i.name)}</option>`).join('')}</select></div>
        </div>
        <button class="btn" id="od-go" style="margin-top:14px">查询</button>
      </div>
      <div id="od-list"><div class="loading">加载中…</div></div>`;
    const qs = () => `from=${el.querySelector('#od-from').value}&to=${el.querySelector('#od-to').value}` +
      `&status=${el.querySelector('#od-status').value}&worker=${el.querySelector('#od-worker').value}` +
      `&customer=${el.querySelector('#od-customer').value}&item=${el.querySelector('#od-item').value}`;
    const reload = async () => Admin.loadOrderList(el.querySelector('#od-list'), qs());
    el.querySelector('#od-go').onclick = reload;
    el.querySelector('#od-new').onclick = () => Admin.newOrderModal(reload);
    reload();
  },

  async loadOrderList(box, q) {
    box.innerHTML = '<div class="loading">加载中…</div>';
    const { orders } = await API.call('/api/a/orders?' + q);
    if (!orders.length) { box.innerHTML = '<div class="empty">没有符合条件的订单</div>'; return; }
    const reload = () => Admin.loadOrderList(box, q);
    box.innerHTML = `<div class="tblwrap"><table class="tbl">
      <tr><th>预约时间</th><th>顾客</th><th>服务员</th><th>项目</th><th>金额</th><th>状态</th><th>操作</th></tr>
      ${orders.map(o => `
        <tr>
          <td>${esc(o.sched_start)}<br><span class="muted small">#${o.id}</span></td>
          <td>${esc(o.customer_name)}</td><td>${esc(o.worker_name)}</td>
          <td>${esc(o.item_name)}</td>
          <td>¥${fmtMoney(o.price_cents)}${o.refunded ? '<br><span class="muted small">已退款</span>' : ''}</td>
          <td>${chip(o.status)}${o.exception_type ? `<br><span class="muted small">${esc(o.exception_type)}</span>` : ''}</td>
          <td><div class="ops">
            ${['pending', 'confirmed', 'exception'].includes(o.status) ? `<button class="btn btn-ghost btn-small" data-reschedule="${o.id}" data-cur="${esc(o.sched_start)}">改期</button>` : ''}
            ${['pending', 'confirmed', 'exception'].includes(o.status) ? `<button class="btn btn-ghost btn-small" data-reassign="${o.id}" data-cur="${esc(o.worker_name)}">改派</button>` : ''}
            ${['pending', 'exception'].includes(o.status) ? `<button class="btn btn-small" data-resolve="${o.id}" data-act="confirm">恢复确认</button>` : ''}
            ${['confirmed', 'exception'].includes(o.status) ? `<button class="btn btn-green btn-small" data-resolve="${o.id}" data-act="complete">标记完成</button>` : ''}
            ${o.status !== 'cancelled' && o.status !== 'completed' ? `<button class="btn btn-danger btn-small" data-resolve="${o.id}" data-act="cancel_refund">取消退款</button>` : ''}
            <button class="btn btn-plain btn-small" data-logs="${o.id}">日志</button>
          </div></td>
        </tr>`).join('')}
    </table></div>`;
    box.querySelectorAll('[data-reschedule]').forEach(b => b.onclick = () => {
      const cur = b.dataset.cur.replace(' ', 'T');
      openModal('订单改期', `
        <p>当前预约时间：<b>${esc(b.dataset.cur)}</b></p>
        <label class="fl">新的预约时间</label>
        <input type="datetime-local" id="rs-time" value="${cur}">`, {
        okText: '确认改期',
        onOk: async () => {
          const v = document.getElementById('rs-time').value.replace('T', ' ');
          if (!v) { toast('请选择时间'); return false; }
          try {
            const r = await API.call(`/api/a/orders/${b.dataset.reschedule}/reschedule`,
              { method: 'POST', body: { start: v } });
            toast('已改期并恢复为已确认', true);
            if (r.conflict_warning) setTimeout(() => toast('注意：新时段与该服务员其他预约相近'), 700);
            closeModal();
            reload();
          } catch (e) { toast(e.message); }
          return false;
        },
      });
    });
    box.querySelectorAll('[data-reassign]').forEach(b => b.onclick = () => {
      openModal('订单改派', `
        <p>当前服务员：<b>${esc(b.dataset.cur)}</b></p>
        <label class="fl">改派给</label>
        <select id="ra-w">${Admin.cache.workers.filter(w => w.active)
          .map(w => `<option value="${w.id}">${esc(w.name)}</option>`).join('')}</select>`, {
        okText: '确认改派',
        onOk: async () => {
          try {
            await API.call(`/api/a/orders/${b.dataset.reassign}/reassign`,
              { method: 'POST', body: { worker_id: +document.getElementById('ra-w').value } });
            toast('已改派', true);
            closeModal();
            reload();
          } catch (e) { toast(e.message); }
          return false;
        },
      });
    });
    box.querySelectorAll('[data-resolve]').forEach(b => b.onclick = async () => {
      const act = b.dataset.act;
      const txt = { confirm: '恢复为已确认？', complete: '标记为已完成（将扣款）？', cancel_refund: '取消该订单（已扣款将自动退款）？' }[act];
      if (!confirm(txt)) return;
      try {
        await API.call(`/api/a/orders/${b.dataset.resolve}/resolve`, { method: 'POST', body: { action: act } });
        toast('处理成功', true);
        reload();
      } catch (e) { toast(e.message); }
    });
    box.querySelectorAll('[data-logs]').forEach(b => b.onclick = async () => {
      const { logs } = await API.call(`/api/a/orders/${b.dataset.logs}/logs`);
      openModal(`订单 #${b.dataset.logs} 操作日志`, logs.length
        ? logs.map(l => `<div class="stop"><div class="body">
            <b>${esc(l.action)}</b> <span class="muted small">${esc(l.created_at)} · ${esc(l.actor)}</span>
            ${l.detail ? `<div class="muted small">${esc(l.detail)}</div>` : ''}</div></div>`).join('')
        : '<div class="empty">无日志</div>', { okOnly: true });
    });
  },

  newOrderModal(done) {
    openModal('代顾客下单', `
      <label class="fl">顾客</label>
      <select id="no-customer">${this.cache.customers.filter(c => c.active)
        .map(c => `<option value="${c.id}">${esc(c.name)}（${c.worker_name ? '服务员：' + esc(c.worker_name) : '未指派'}）</option>`).join('')}</select>
      <label class="fl">服务项目</label>
      <select id="no-item">${this.cache.items.filter(i => i.active)
        .map(i => `<option value="${i.id}">${esc(i.name)} · ¥${fmtMoney(i.price_cents)} / ${i.minutes}分钟</option>`).join('')}</select>
      <div class="frow">
        <div><label class="fl">日期</label><input type="date" id="no-date" min="${todayStr()}" value="${tomorrowStr()}"></div>
        <div><label class="fl">时间</label><input type="time" id="no-time" value="09:00" step="1800"></div>
      </div>
      <label class="fl">备注（选填）</label>
      <textarea id="no-note"></textarea>`, {
      okText: '下单',
      onOk: async () => {
        try {
          const r = await API.call('/api/a/orders', { method: 'POST', body: {
            customer_id: +document.getElementById('no-customer').value,
            item_id: +document.getElementById('no-item').value,
            date: document.getElementById('no-date').value,
            time: document.getElementById('no-time').value,
            note: document.getElementById('no-note').value.trim(),
          } });
          toast('下单成功', true);
          if (r.conflict_warning) setTimeout(() => toast('注意：该时段与服务员其他预约相近，建议协调'), 700);
          closeModal();
          done();
        } catch (e) { toast(e.message); }
        return false;
      },
    });
  },

  /* ============ 人员管理 ============ */
  async renderUsers(el, role = 'worker') {
    await this.loadRefs();
    el.innerHTML = `
      <div class="card">
        <h3>人员管理
          <span class="row">
            <span class="seg" id="us-role">
              <button data-r="worker" class="${role === 'worker' ? 'on' : ''}">服务员</button>
              <button data-r="customer" class="${role === 'customer' ? 'on' : ''}">顾客</button>
            </span>
            <button class="btn btn-small" id="us-new">➕ 新增</button>
          </span>
        </h3>
        <div id="us-list"><div class="loading">加载中…</div></div>
      </div>`;
    el.querySelectorAll('#us-role button').forEach(b =>
      b.onclick = () => Admin.renderUsers(el, b.dataset.r));
    el.querySelector('#us-new').onclick = () => Admin.userModal(role, null, () => Admin.renderUsers(el, role));
    this.loadUserList(el.querySelector('#us-list'), role, () => Admin.renderUsers(el, role));
  },

  async loadUserList(box, role, rerender) {
    const { users } = await API.call('/api/a/users?role=' + role);
    box.innerHTML = users.length ? users.map(u => `
      <div class="order-card card ${u.active ? 'confirmed' : 'cancelled'}" style="margin-bottom:8px">
        <div class="head"><span class="who">${esc(u.name)} ${u.active ? '' : '<span class="chip gray">已停用</span>'}</span></div>
        <div class="meta">📱 ${esc(u.phone)}</div>
        <div class="meta">📍 ${esc(u.address || '地址未填写')} ${u.lat != null ? '· 已定位' : '· <b style="color:var(--red)">未定位</b>'}</div>
        ${role === 'worker'
          ? `<div class="meta">固定顾客 ${u.customer_count} 人</div>`
          : `<div class="meta">服务员：${esc(u.worker_name || '未指派')} · 余额 ¥${fmtMoney(u.balance_cents)}</div>`}
        <div class="contact-btns">
          <button class="btn btn-ghost btn-small" data-edit="${u.id}">编辑</button>
          ${u.active
            ? `<button class="btn btn-danger btn-small" data-off="${u.id}">停用</button>`
            : `<button class="btn btn-green btn-small" data-on="${u.id}">启用</button>`}
        </div>
      </div>`).join('') : '<div class="empty">暂无人员</div>';
    box.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => {
      const u = users.find(x => x.id === +b.dataset.edit);
      Admin.userModal(role, u, rerender);
    });
    box.querySelectorAll('[data-off]').forEach(b => b.onclick = async () => {
      if (!confirm('停用后该账号无法登录（数据保留，可重新启用）。确定停用？')) return;
      try {
        await API.call(`/api/a/users/${b.dataset.off}`, { method: 'DELETE' });
        toast('已停用', true);
        rerender();
      } catch (e) { toast(e.message); }
    });
    box.querySelectorAll('[data-on]').forEach(b => b.onclick = async () => {
      try {
        await API.call(`/api/a/users/${b.dataset.on}`, { method: 'PUT', body: { active: 1 } });
        toast('已启用', true);
        rerender();
      } catch (e) { toast(e.message); }
    });
  },

  userModal(role, u, done) {
    const isNew = !u;
    let marker = null, pos = u && u.lat != null ? [u.lat, u.lng] : null;
    openModal(isNew ? `新增${role === 'worker' ? '服务员' : '顾客'}` : `编辑：${u.name}`, `
      <div class="frow">
        <div><label class="fl">姓名</label><input type="text" id="uf-name" value="${u ? esc(u.name) : ''}"></div>
        <div><label class="fl">手机号（账号）</label><input type="tel" id="uf-phone" value="${u ? esc(u.phone) : ''}"></div>
      </div>
      <label class="fl">${isNew ? '初始密码' : '重置密码（留空不改）'}</label>
      <input type="text" id="uf-pwd" placeholder="至少 6 位" ${u ? 'value=""' : ''}>
      <label class="fl">居住地址</label>
      <input type="text" id="uf-addr" value="${u ? esc(u.address) : ''}" placeholder="例：江汉区解放大道690号">
      <button type="button" class="btn btn-ghost btn-small" id="uf-geo" style="margin-top:6px">📍 根据地址自动定位</button>
      <span class="muted small" style="margin-left:8px">或直接点击下方地图选点</span>
      ${role === 'customer' ? `
      <label class="fl">指派服务员</label>
      <select id="uf-worker">${this.cache.workers.filter(w => w.active)
        .map(w => `<option value="${w.id}" ${u && u.worker_id === w.id ? 'selected' : ''}>${esc(w.name)}</option>`).join('')}</select>` : ''}
      <label class="fl">位置（点击地图打点，用于路线规划）</label>
      <div id="uf-map" class="map" style="height:240px"></div>
      <div class="muted small" id="uf-pos">${pos ? `已定位：${pos[0].toFixed(5)}, ${pos[1].toFixed(5)}` : '未设置位置'}</div>`, {
      okText: '保存',
      onOk: async () => {
        try {
          const body = {
            role, name: document.getElementById('uf-name').value.trim(),
            phone: document.getElementById('uf-phone').value.trim(),
            password: document.getElementById('uf-pwd').value,
            address: document.getElementById('uf-addr').value.trim(),
            lat: pos ? pos[0] : null, lng: pos ? pos[1] : null,
          };
          if (role === 'customer') body.worker_id = +document.getElementById('uf-worker').value;
          if (isNew) await API.call('/api/a/users', { method: 'POST', body });
          else await API.call(`/api/a/users/${u.id}`, { method: 'PUT', body });
          toast('已保存', true);
          closeModal();
          done();
        } catch (e) { toast(e.message); }
        return false;
      },
      onMount(box) {
        setTimeout(() => {
          const map = Maps.create('uf-map');
          if (pos) {
            map.setView(pos, 15);
            marker = L.marker(pos, { icon: Maps.pin('📍') }).addTo(map);
          }
          map.on('click', e => {
            pos = [e.latlng.lat, e.latlng.lng];
            if (marker) marker.setLatLng(e.latlng);
            else marker = L.marker(pos, { icon: Maps.pin('📍') }).addTo(map);
            box.querySelector('#uf-pos').textContent = `已定位：${pos[0].toFixed(5)}, ${pos[1].toFixed(5)}`;
          });
          box.querySelector('#uf-geo').onclick = async () => {
            const addr = box.querySelector('#uf-addr').value.trim();
            if (!addr) { toast('请先填写地址'); return; }
            toast('正在解析地址…');
            try {
              const g = await API.call(`/api/a/geocode?address=${encodeURIComponent(addr)}`);
              pos = [g.lat, g.lng];
              map.setView(pos, 16);
              if (marker) marker.setLatLng(pos);
              else marker = L.marker(pos, { icon: Maps.pin('📍') }).addTo(map);
              box.querySelector('#uf-pos').textContent = `已定位：${pos[0].toFixed(5)}, ${pos[1].toFixed(5)}（高德解析）`;
              Maps.refresh();
            } catch (e) { toast(e.message); }
          };
          Maps.refresh();
        }, 80);
      },
    });
  },

  /* ============ 服务项目 ============ */
  async renderItems(el) {
    await this.loadRefs();
    el.innerHTML = `
      <div class="card">
        <h3>服务项目 <button class="btn btn-small" id="it-new">➕ 新增</button></h3>
        <div class="tblwrap"><table class="tbl">
          <tr><th>项目</th><th>时长(分)</th><th>价格</th><th>服务员酬金</th><th>状态</th><th>操作</th></tr>
          ${this.cache.items.map(i => `
            <tr>
              <td>${esc(i.name)}</td><td>${i.minutes}</td>
              <td>¥${fmtMoney(i.price_cents)}</td><td>¥${fmtMoney(i.worker_pay_cents)}</td>
              <td>${i.active ? '<span class="chip green">在售</span>' : '<span class="chip gray">停用</span>'}</td>
              <td><div class="ops">
                <button class="btn btn-ghost btn-small" data-it="${i.id}">编辑</button>
                ${i.active ? `<button class="btn btn-danger btn-small" data-itoff="${i.id}">停用</button>` : ''}
              </div></td>
            </tr>`).join('')}
        </table></div>
      </div>`;
    const rerender = () => Admin.renderItems(el);
    el.querySelector('#it-new').onclick = () => Admin.itemModal(null, rerender);
    el.querySelectorAll('[data-it]').forEach(b => b.onclick = () =>
      Admin.itemModal(Admin.cache.items.find(x => x.id === +b.dataset.it), rerender));
    el.querySelectorAll('[data-itoff]').forEach(b => b.onclick = async () => {
      if (!confirm('停用后顾客不能再预约该项目（历史订单不受影响）。确定？')) return;
      try {
        await API.call(`/api/a/items/${b.dataset.itoff}`, { method: 'DELETE' });
        toast('已停用', true);
        rerender();
      } catch (e) { toast(e.message); }
    });
  },

  itemModal(item, done) {
    const i = item || { name: '', minutes: 60, price_cents: 0, worker_pay_cents: 0 };
    openModal(item ? `编辑：${item.name}` : '新增服务项目', `
      <label class="fl">项目名称</label><input type="text" id="if-name" value="${esc(i.name)}">
      <div class="frow">
        <div><label class="fl">时长（分钟）</label><input type="number" id="if-min" min="10" step="10" value="${i.minutes}"></div>
        <div><label class="fl">价格（元）</label><input type="number" id="if-price" min="0" step="0.5" value="${fmtMoney(i.price_cents)}"></div>
      </div>
      <label class="fl">服务员酬金（元）</label>
      <input type="number" id="if-pay" min="0" step="0.5" value="${fmtMoney(i.worker_pay_cents)}">`, {
      okText: '保存',
      onOk: async () => {
        try {
          const body = {
            name: document.getElementById('if-name').value.trim(),
            minutes: +document.getElementById('if-min').value,
            price_cents: Math.round(+document.getElementById('if-price').value * 100),
            worker_pay_cents: Math.round(+document.getElementById('if-pay').value * 100),
          };
          if (item) await API.call(`/api/a/items/${item.id}`, { method: 'PUT', body });
          else await API.call('/api/a/items', { method: 'POST', body });
          toast('已保存', true);
          closeModal();
          done();
        } catch (e) { toast(e.message); }
        return false;
      },
    });
  },

  /* ============ 批量充值 ============ */
  async renderRecharge(el) {
    await this.loadRefs();
    const month = todayStr().slice(0, 7);
    const cs = this.cache.customers.filter(c => c.active);
    el.innerHTML = `
      <div class="card">
        <h3>批量充值（虚拟币）</h3>
        <div class="frow">
          <div><label class="fl">充值说明</label><input type="text" id="rc-note" value="${month}月充值"></div>
          <div><label class="fl">每人金额（元）</label><input type="number" id="rc-amt" min="1" step="1" value="300"></div>
        </div>
        <div class="row" style="margin-top:12px">
          <button class="btn btn-ghost btn-small" id="rc-all">全选</button>
          <button class="btn btn-plain btn-small" id="rc-none">全不选</button>
          <span class="muted small">勾选要充值的顾客（右侧显示当前余额）</span>
        </div>
        <div class="cklist" style="margin-top:8px">
          ${cs.map(c => `<label class="ck-item"><input type="checkbox" class="rc-ck" value="${c.id}" checked>
            <span>${esc(c.name)}</span><span class="muted small">余额 ¥${fmtMoney(c.balance_cents)}</span></label>`).join('')}
        </div>
        <button class="btn btn-lg" id="rc-go" style="margin-top:14px">确认充值</button>
      </div>
      <div class="card"><h3>最近充值记录</h3><div id="rc-his"><div class="loading"></div></div></div>`;
    el.querySelector('#rc-all').onclick = () => el.querySelectorAll('.rc-ck').forEach(k => k.checked = true);
    el.querySelector('#rc-none').onclick = () => el.querySelectorAll('.rc-ck').forEach(k => k.checked = false);
    el.querySelector('#rc-go').onclick = async () => {
      const ids = [...el.querySelectorAll('.rc-ck:checked')].map(k => +k.value);
      const amt = Math.round(+el.querySelector('#rc-amt').value * 100);
      if (!ids.length) { toast('请勾选顾客'); return; }
      if (!(amt > 0)) { toast('请输入正确金额'); return; }
      if (!confirm(`确定为 ${ids.length} 位顾客每人充值 ${fmtMoney(amt)} 元？`)) return;
      try {
        const r = await API.call('/api/a/recharge', { method: 'POST', body: {
          customer_ids: ids, amount_cents: amt, note: el.querySelector('#rc-note').value.trim() } });
        toast(`已为 ${r.count} 位顾客充值成功`, true);
        Admin.renderRecharge(el);
      } catch (e) { toast(e.message); }
    };
    const his = await API.call('/api/a/recharges');
    el.querySelector('#rc-his').innerHTML = his.recharges.length
      ? `<div class="tblwrap"><table class="tbl">
          <tr><th>时间</th><th>顾客</th><th>金额</th><th>说明</th></tr>
          ${his.recharges.map(r => `<tr><td>${esc(r.created_at)}</td><td>${esc(r.customer_name)}</td>
            <td class="money-plus">+¥${fmtMoney(r.delta_cents)}</td><td>${esc(r.note || '')}</td></tr>`).join('')}
        </table></div>` : '<div class="empty">暂无记录</div>';
  },

  /* ============ 酬金发放 ============ */
  async renderPayout(el) {
    await this.loadRefs();
    el.innerHTML = `
      <div class="card">
        <h3>酬金发放（按已完成订单）</h3>
        <div class="frow">
          <div><label class="fl">服务员</label><select id="pw-worker">
            ${this.cache.workers.filter(w => w.active)
              .map(w => `<option value="${w.id}">${esc(w.name)}</option>`).join('')}</select></div>
          <div><label class="fl">开始日期</label><input type="date" id="pw-from" value="${todayStr().slice(0, 8)}01"></div>
        </div>
        <label class="fl">结束日期</label><input type="date" id="pw-to" value="${todayStr()}">
        <button class="btn" id="pw-preview" style="margin-top:14px">预览待发酬金</button>
      </div>
      <div id="pw-body"></div>
      <div class="card"><h3>发放历史</h3><div id="pw-his"><div class="loading"></div></div></div>`;
    const reloadHis = async () => {
      const p = await API.call('/api/a/payouts');
      el.querySelector('#pw-his').innerHTML = p.payouts.length
        ? `<div class="tblwrap"><table class="tbl">
            <tr><th>时间</th><th>服务员</th><th>区间</th><th>单数</th><th>金额</th></tr>
            ${p.payouts.map(x => `<tr><td>${esc(x.created_at)}</td><td>${esc(x.worker_name)}</td>
              <td>${esc(x.from_date)} ~ ${esc(x.to_date)}</td><td>${x.order_count}</td>
              <td class="money-plus">¥${fmtMoney(x.total_cents)}</td></tr>`).join('')}
          </table></div>` : '<div class="empty">暂无发放记录</div>';
    };
    el.querySelector('#pw-preview').onclick = async () => {
      const wid = el.querySelector('#pw-worker').value;
      const from = el.querySelector('#pw-from').value, to = el.querySelector('#pw-to').value;
      const body = el.querySelector('#pw-body');
      body.innerHTML = '<div class="loading">查询中…</div>';
      const pv = await API.call(`/api/a/payout/preview?worker=${wid}&from=${from}&to=${to}`);
      body.innerHTML = pv.count ? `
        <div class="card">
          <h3>待发订单 <span class="sub">${pv.count} 单 · 合计 <b class="money-plus">¥${fmtMoney(pv.total_cents)}</b></span></h3>
          <div class="tblwrap"><table class="tbl">
            <tr><th>预约时间</th><th>顾客</th><th>项目</th><th>酬金</th></tr>
            ${pv.orders.map(o => `<tr><td>${esc(o.sched_start)}</td><td>${esc(o.customer_name)}</td>
              <td>${esc(o.item_name)}</td><td>¥${fmtMoney(o.worker_pay_cents)}</td></tr>`).join('')}
          </table></div>
          <button class="btn btn-green btn-lg" id="pw-go" style="margin-top:12px">确认发放 ¥${fmtMoney(pv.total_cents)}</button>
        </div>` : '<div class="empty">该时间段没有待发放的酬金</div>';
      const go = body.querySelector('#pw-go');
      if (go) go.onclick = async () => {
        if (!confirm('确认发放该笔酬金？发放后不可重复发放。')) return;
        try {
          const r = await API.call('/api/a/payout', { method: 'POST', body: { worker_id: +wid, from, to } });
          toast(`已发放 ${r.count} 单，共 ¥${fmtMoney(r.total_cents)}`, true);
          Admin.renderPayout(el);
        } catch (e) { toast(e.message); }
      };
    };
    reloadHis();
  },
};
