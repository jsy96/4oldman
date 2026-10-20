/* 应用外壳：全局工具、登录、角色导航、弹窗与提示。 */
let CONF = null, ME = null;

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtMoney = c => ((c || 0) / 100).toFixed(2);
const fmtMinutes = m => (m >= 60 ? `${Math.floor(m / 60)} 小时 ${m % 60} 分` : `${m} 分钟`);

/* 行程时间安排检查结果（服务员端与管理员端共用） */
function scheduleCheckHtml(c) {
  const badge = st => st === 'ok' ? '<span class="chip green">合理</span>'
    : st === 'tight' ? '<span class="chip amber">偏紧</span>' : '<span class="chip red">会迟到</span>';
  const color = st => st === 'ok' ? 'var(--green)' : st === 'tight' ? 'var(--amber)' : 'var(--red)';
  const orders = (c.orders || []).map(o => `
    <div class="stop">
      <div class="seq" style="background:${color(o.status)}">${o.seq}</div>
      <div class="body">
        <div><b>第${o.seq}单 ${esc(o.customer)}</b> · ${esc(o.item)} ${badge(o.status)}</div>
        <div class="tm">${o.start} - ${o.end}</div>
        ${o.seq === 1
          ? `<div class="muted small">距驻地 ${o.distance_km} km · 骑行约 ${o.travel_min} 分钟 · 建议 ${esc(o.depart_advice || '')} 之前出发</div>`
          : `<div class="muted small">距上一单 ${o.distance_km} km · 骑行约 ${o.travel_min} 分钟 · 预留 ${o.gap_min} 分钟（需 ≥ ${o.required_min} 分钟）</div>`}
      </div>
    </div>`).join('');
  const ret = c.return_leg ? `
    <div class="stop">
      <div class="seq" style="background:#64748b">⌂</div>
      <div class="body">
        <div><b>返程回驻地</b></div>
        <div class="muted small">最后一单 ${esc((c.orders || []).length ? c.orders[c.orders.length - 1].end : '')} 结束
          · 距驻地 ${c.return_leg.distance_km} km · 骑行约 ${c.return_leg.travel_min} 分钟
          · 约 ${esc(c.return_leg.arrive_home)} 到达驻地</div>
      </div>
    </div>` : '';
  const t = c.totals || {};
  return orders + ret + `
    <div class="info-box" style="margin-top:12px">
      全天：骑行 <b>${t.distance_km} km</b> / <b>${fmtMinutes(t.ride_minutes || 0)}</b>
      · 工作时长 <b>${fmtMinutes(t.work_minutes || 0)}</b>
      · 收入 <b>¥${fmtMoney(t.income_cents || 0)}</b>
    </div>`;
}
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const todayStr = () => dstr(new Date());
const tomorrowStr = () => dstr(new Date(Date.now() + 864e5));

const STATUS = {
  pending: ['待确认', 'amber'], confirmed: ['已确认', 'blue'], completed: ['已完成', 'green'],
  exception: ['异常', 'red'], cancelled: ['已取消', 'gray'],
};
const chip = st => `<span class="chip ${STATUS[st] ? STATUS[st][1] : 'gray'}">${STATUS[st] ? STATUS[st][0] : st}</span>`;
const KIND = { recharge: '充值', order: '服务扣款', refund: '退款', adjust: '调整' };
const ROLE_TEXT = { admin: '管理员', worker: '服务员', customer: '顾客' };

const NAV = {
  customer: [['orders', '📋', '订单历史'], ['book', '➕', '预约服务'], ['money', '💰', '账户明细'], ['me', '👤', '我的']],
  worker: [['todo', '✅', '今日待办'], ['orders', '🗓️', '订单'], ['route', '🗺️', '行程路线'], ['customers', '👪', '我的顾客']],
  admin: [['stats', '📊', '统计'], ['orders', '🧾', '订单'], ['map', '🗺️', '行程检查'],
    ['users', '👥', '人员'], ['items', '🧺', '项目'], ['recharge', '💰', '充值'], ['payout', '💵', '酬金']],
};
const RENDER = {
  customer: { orders: el => Customer.renderOrders(el), book: el => Customer.renderBook(el),
    money: el => Customer.renderMoney(el), me: el => Customer.renderMe(el) },
  worker: { todo: el => Worker.renderTodo(el), orders: el => Worker.renderOrders(el),
    route: el => Worker.renderRoute(el), customers: el => Worker.renderCustomers(el) },
  admin: { stats: el => Admin.renderStats(el), orders: el => Admin.renderOrders(el),
    map: el => Admin.renderMap(el), users: el => Admin.renderUsers(el),
    items: el => Admin.renderItems(el), recharge: el => Admin.renderRecharge(el),
    payout: el => Admin.renderPayout(el) },
};

/* ---------- 提示 ---------- */
let toastTimer = null;
function toast(msg, ok) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (ok === true ? ' ok' : ok === false ? ' err' : '');
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
}

/* ---------- 弹窗 ---------- */
function closeModal() {
  $('#modal-root').innerHTML = '';
  Maps.destroy('uf-map');
}
function openModal(title, html, opts = {}) {
  closeModal();
  const root = $('#modal-root');
  const mask = document.createElement('div');
  mask.className = 'modal-mask';
  const foot = [
    opts.extraButtons || '',
    opts.onOk ? '<button class="btn btn-plain" data-cancel>取消</button>' : '',
    `<button class="btn ${opts.okBtnClass || ''}" data-ok>${esc(opts.okText || (opts.onOk ? '确定' : '关闭'))}</button>`,
  ].join('');
  mask.innerHTML = `<div class="modal">
    <h3>${esc(title)}<button class="x" data-x>✕</button></h3>
    ${html}<div class="foot">${foot}</div></div>`;
  root.appendChild(mask);
  const box = mask.querySelector('.modal');
  mask.addEventListener('click', e => { if (e.target === mask) closeModal(); });
  box.querySelector('[data-x]').onclick = closeModal;
  const cx = box.querySelector('[data-cancel]');
  if (cx) cx.onclick = closeModal;
  box.querySelector('[data-ok]').onclick = async () => {
    if (!opts.onOk) { closeModal(); return; }
    const r = await opts.onOk();
    if (r !== false) closeModal();
  };
  if (opts.onMount) opts.onMount(box);
}

/* ---------- 登录 ---------- */
function _hideBoot() {
  const b = document.getElementById('boot-splash');
  if (b) b.remove();
}

function showLogin() {
  $('#app-view').hidden = true;
  $('#login-view').hidden = false;
  _hideBoot();
  $('#forgot-link').onclick = openForgotModal;
  $('#login-form').onsubmit = async e => {
    e.preventDefault();
    const err = $('#login-err');
    err.hidden = true;
    try {
      const r = await API.call('/api/login', { method: 'POST', body: {
        phone: $('#login-phone').value.trim(), password: $('#login-pwd').value } });
      API.setToken(r.token);
      ME = { id: r.id, role: r.role, name: r.name, is_super: r.is_super || 0 };  // 登录响应已含用户信息
      showApp();
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    }
  };
}

/* ---------- 主界面 ---------- */
function showApp() {
  $('#login-view').hidden = true;
  $('#app-view').hidden = false;
  _hideBoot();
  $('#brand-name').textContent = CONF.app_name;
  document.title = `${CONF.app_name} · ${ROLE_TEXT[ME.role]}`;
  $('#top-hello').textContent = `${ME.name}（${ROLE_TEXT[ME.role]}）`;
  $('#btn-pwd').onclick = openChangePwdModal;
  $('#btn-logout').onclick = async () => {
    try { await API.call('/api/logout', { method: 'POST' }); } catch (e) { /* 忽略 */ }
    API.setToken('');
    location.reload();
  };
  const bar = $('#tabbar');
  bar.innerHTML = NAV[ME.role].map(([k, ico, txt]) =>
    `<button data-tab="${k}"><span class="ico">${ico}</span><span>${txt}</span></button>`).join('');
  bar.querySelectorAll('button').forEach(b => b.onclick = () => switchTab(b.dataset.tab));
  switchTab(NAV[ME.role][0][0]);
}

function switchTab(key) {
  const main = $('#main');
  main.className = `main role-${ME.role}`;
  $('#tabbar').querySelectorAll('button').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === key));
  Maps.refresh();
  RENDER[ME.role][key](main);
}

/* ---------- 密码管理 ---------- */
async function openChangePwdModal() {
  let phone = '';
  try { phone = (await API.call('/api/me')).phone || ''; } catch (e) { /* 忽略 */ }
  openModal('修改密码（短信验证）', `
    <label class="fl">手机号（账号）</label>
    <input type="tel" id="cp-phone" value="${esc(phone)}" readonly>
    <label class="fl">短信验证码</label>
    <div class="row">
      <input type="text" id="cp-code" style="flex:1" placeholder="6 位验证码" inputmode="numeric">
      <button type="button" class="btn btn-ghost" id="cp-send">发送验证码</button>
    </div>
    <label class="fl">新密码（至少 6 位）</label>
    <input type="password" id="cp-new" autocomplete="new-password">
    <label class="fl">确认新密码</label>
    <input type="password" id="cp-new2" autocomplete="new-password">
    <div class="muted small" style="margin-top:8px">验证码发送到账号绑定的手机号，5 分钟内有效，1 分钟内只能发送一次。</div>`, {
    okText: '修改密码',
    onMount(box) {
      box.querySelector('#cp-send').onclick = async () => {
        if (!phone) { toast('未获取到手机号，请重新登录'); return; }
        const btn = box.querySelector('#cp-send');
        try {
          const r = await API.call('/api/auth/send-code',
            { method: 'POST', body: { phone, scene: 'change' } });
          if (r.debug_code) {
            box.querySelector('#cp-code').value = r.debug_code;
            toast('调试模式：验证码已自动填入', true);
          } else {
            toast(r.message || '验证码已发送', true);
          }
          let left = 60;
          btn.disabled = true;
          btn.textContent = left + 's 后重发';
          const t = setInterval(() => {
            left -= 1;
            if (left <= 0) { clearInterval(t); btn.disabled = false; btn.textContent = '发送验证码'; }
            else btn.textContent = left + 's 后重发';
          }, 1000);
        } catch (e) { toast(e.message); }
      };
    },
    onOk: async () => {
      const code = $('#cp-code').value.trim();
      const n = $('#cp-new').value;
      const n2 = $('#cp-new2').value;
      if (!code) { toast('请输入短信验证码'); return false; }
      if (!n) { toast('请输入新密码'); return false; }
      if (n !== n2) { toast('两次输入的新密码不一致'); return false; }
      try {
        await API.call('/api/auth/change-password',
          { method: 'POST', body: { code, new_password: n } });
        toast('密码已修改', true);
        closeModal();
      } catch (e) { toast(e.message); }
      return false;
    },
  });
}

function openForgotModal() {
  openModal('找回密码', `
    <label class="fl">手机号（账号）</label>
    <input type="tel" id="fp-phone" value="${esc($('#login-phone').value.trim())}">
    <label class="fl">验证码</label>
    <div class="row">
      <input type="text" id="fp-code" style="flex:1" placeholder="6 位验证码" inputmode="numeric">
      <button type="button" class="btn btn-ghost" id="fp-send">发送验证码</button>
    </div>
    <label class="fl">新密码（至少 6 位）</label>
    <input type="password" id="fp-new" autocomplete="new-password">
    <div class="muted small" style="margin-top:8px">验证码 5 分钟内有效，同一手机号 1 分钟内只能发送一次。</div>`, {
    okText: '重置密码',
    onMount(box) {
      box.querySelector('#fp-send').onclick = async () => {
        const phone = box.querySelector('#fp-phone').value.trim();
        if (!phone) { toast('请输入手机号'); return; }
        const btn = box.querySelector('#fp-send');
        try {
          const r = await API.call('/api/auth/send-code',
            { method: 'POST', body: { phone, scene: 'reset' } });
          if (r.debug_code) {
            box.querySelector('#fp-code').value = r.debug_code;
            toast('调试模式：验证码已自动填入', true);
          } else {
            toast(r.message || '验证码已发送', true);
          }
          let left = 60;
          btn.disabled = true;
          btn.textContent = left + 's 后重发';
          const t = setInterval(() => {
            left -= 1;
            if (left <= 0) { clearInterval(t); btn.disabled = false; btn.textContent = '发送验证码'; }
            else btn.textContent = left + 's 后重发';
          }, 1000);
        } catch (e) { toast(e.message); }
      };
    },
    onOk: async () => {
      const phone = $('#fp-phone').value.trim();
      const code = $('#fp-code').value.trim();
      const n = $('#fp-new').value;
      if (!phone || !code || !n) { toast('请填写完整'); return false; }
      try {
        await API.call('/api/auth/reset-password',
          { method: 'POST', body: { phone, code, new_password: n } });
        toast('密码已重置，请用新密码登录', true);
        $('#login-phone').value = phone;
        $('#login-pwd').value = '';
        closeModal();
      } catch (e) { toast(e.message); }
      return false;
    },
  });
}

/* ---------- 启动 ---------- */
async function boot() {
  // 先用本地缓存的配置立即初始化（第二次打开秒开），同时后台刷新最新配置
  let cached = null;
  try { cached = JSON.parse(localStorage.getItem('care_meta') || 'null'); } catch (e) { cached = null; }
  if (cached && cached.map) { CONF = cached; Maps.init(CONF.map); }
  const metaP = API.call('/api/meta').then(m => {
    CONF = m;
    try { localStorage.setItem('care_meta', JSON.stringify(m)); } catch (e) { /* 忽略 */ }
    Maps.init(m.map);
    return m;
  }).catch(() => null);

  if (API.token) {
    try {
      const [me] = await Promise.all([API.call('/api/me'), metaP]);  // 并行，省一个往返
      ME = me;
      showApp();
      return;
    } catch (e) { API.setToken(''); }
  }
  await metaP;
  if (!CONF) {
    document.body.innerHTML = `<div class="login-wrap"><div class="login-card">
      <h1>服务暂不可用</h1><p class="login-sub">网络连接失败，请稍后刷新重试</p></div></div>`;
    return;
  }
  showLogin();
}
window.addEventListener('DOMContentLoaded', boot);
