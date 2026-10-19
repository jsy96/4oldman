/* 应用外壳：全局工具、登录、角色导航、弹窗与提示。 */
let CONF = null, ME = null;

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtMoney = c => ((c || 0) / 100).toFixed(2);
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
  admin: [['stats', '📊', '统计'], ['orders', '🧾', '订单'], ['users', '👥', '人员'], ['items', '🧺', '项目'], ['recharge', '💰', '充值'], ['payout', '💵', '酬金']],
};
const RENDER = {
  customer: { orders: el => Customer.renderOrders(el), book: el => Customer.renderBook(el),
    money: el => Customer.renderMoney(el), me: el => Customer.renderMe(el) },
  worker: { todo: el => Worker.renderTodo(el), orders: el => Worker.renderOrders(el),
    route: el => Worker.renderRoute(el), customers: el => Worker.renderCustomers(el) },
  admin: { stats: el => Admin.renderStats(el), orders: el => Admin.renderOrders(el),
    users: el => Admin.renderUsers(el), items: el => Admin.renderItems(el),
    recharge: el => Admin.renderRecharge(el), payout: el => Admin.renderPayout(el) },
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
function showLogin() {
  $('#app-view').hidden = true;
  $('#login-view').hidden = false;
  $('#login-form').onsubmit = async e => {
    e.preventDefault();
    const err = $('#login-err');
    err.hidden = true;
    try {
      const r = await API.call('/api/login', { method: 'POST', body: {
        phone: $('#login-phone').value.trim(), password: $('#login-pwd').value } });
      API.setToken(r.token);
      ME = await API.call('/api/me');
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
  $('#brand-name').textContent = CONF.app_name;
  document.title = `${CONF.app_name} · ${ROLE_TEXT[ME.role]}`;
  $('#top-hello').textContent = `${ME.name}（${ROLE_TEXT[ME.role]}）`;
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

/* ---------- 启动 ---------- */
async function boot() {
  try {
    CONF = await API.call('/api/meta');
  } catch (e) {
    document.body.innerHTML = `<div class="login-wrap"><div class="login-card">
      <h1>服务暂不可用</h1><p class="login-sub">${esc(e.message)}</p></div></div>`;
    return;
  }
  Maps.init(CONF.map);
  if (API.token) {
    try { ME = await API.call('/api/me'); showApp(); return; } catch (e) { API.setToken(''); }
  }
  showLogin();
}
window.addEventListener('DOMContentLoaded', boot);
