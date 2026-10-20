/* 接口封装：统一鉴权头、401 自动回登录页、错误信息透出。
   url() 按 <base> 解析，兼容挂在路由前缀（如 /eldercare）下部署。 */
const API = {
  token: localStorage.getItem('care_token') || '',
  setToken(t) {
    this.token = t || '';
    if (t) localStorage.setItem('care_token', t);
    else localStorage.removeItem('care_token');
  },
  url(path) {
    /* 按 <base> 解析；无 <base> 时用当前页面路径（兼容 /eldercare 前缀部署） */
    let base = document.baseURI;
    if (!document.querySelector('base') && !location.pathname.endsWith('/'))
      base = location.origin + location.pathname + '/';
    return new URL(String(path).replace(/^\/+/, ''), base).href;
  },
  async call(path, { method = 'GET', body } = {}) {
    let res;
    try {
      res = await fetch(this.url(path), {
        method,
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this.token },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      throw new Error('网络连接失败，请检查网络后重试');
    }
    let data = {};
    try { data = await res.json(); } catch (e) { /* 空响应 */ }
    if (res.status === 401) {
      this.setToken('');
      location.reload();
      throw new Error(data.error || '请重新登录');
    }
    if (!res.ok) {
      const err = new Error(data.error || `请求失败(${res.status})`);
      err.data = data;
      throw err;
    }
    return data;
  },
};
