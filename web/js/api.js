/* 接口封装：统一鉴权头、401 自动回登录页、错误信息透出。 */
const API = {
  token: localStorage.getItem('care_token') || '',
  setToken(t) {
    this.token = t || '';
    if (t) localStorage.setItem('care_token', t);
    else localStorage.removeItem('care_token');
  },
  async call(path, { method = 'GET', body } = {}) {
    let res;
    try {
      res = await fetch(path, {
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
