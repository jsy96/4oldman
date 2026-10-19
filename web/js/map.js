/* Leaflet 地图封装：底图切换、编号标记、实例管理。 */
const Maps = {
  conf: null,
  instances: new Map(),

  init(conf) { this.conf = conf; },

  tiles() {
    return this.conf && this.conf.tiles === 'gaode'
      ? L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
          { subdomains: '1234', maxZoom: 18 })
      : L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 });
  },

  create(elId) {
    this.destroy(elId);
    const m = L.map(elId, { attributionControl: false });
    this.tiles().addTo(m);
    m.setView([this.conf.center_lat, this.conf.center_lng], this.conf.zoom);
    this.instances.set(elId, m);
    return m;
  },

  get(elId) { return this.instances.get(elId); },

  destroy(elId) {
    const m = this.instances.get(elId);
    if (m) { m.remove(); this.instances.delete(elId); }
  },

  refresh() { this.instances.forEach(m => m.invalidateSize()); },

  /* 地图编号大头针：n=序号或图标文本，cls 可为 home */
  pin(n, cls) {
    return L.divIcon({
      className: '',
      html: `<div class="pin ${cls || ''}">${n}</div>`,
      iconSize: [30, 30],
      iconAnchor: [15, 28],
    });
  },
};
