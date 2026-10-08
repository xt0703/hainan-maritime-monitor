const map = L.map('map').setView([18.9, 110.0], 6);

// === Lớp nền ===
const normalMap = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18,
  attribution: '&copy; OpenStreetMap contributors'
});

const satelliteMap = L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  {
    maxZoom: 18,
    attribution: 'Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'
  }
);

// Ghi nhớ lớp nền người dùng đã chọn.
const savedBaseMap = localStorage.getItem('hainan-base-map');
(savedBaseMap === 'satellite' ? satelliteMap : normalMap).addTo(map);

L.control.layers({
  '🗺️ Bản đồ thường': normalMap,
  '🛰️ Vệ tinh': satelliteMap
}, null, {
  position: 'topright',
  collapsed: true
}).addTo(map);

map.on('baselayerchange', e => {
  localStorage.setItem(
    'hainan-base-map',
    e.layer === satelliteMap ? 'satellite' : 'normal'
  );
});

// === Lớp cảnh báo ===
const layer = L.layerGroup().addTo(map);
let records = [];

const esc = s => String(s ?? '').replace(/[&<>'"]/g, c => ({
  '&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'
}[c]));

const fmt = s => s
  ? new Intl.DateTimeFormat('vi-VN', {
      dateStyle:'short',
      timeStyle:'short',
      timeZone:'Asia/Ho_Chi_Minh'
    }).format(new Date(s))
  : 'Chưa trích xuất';

const now = () => new Date();

function status(r){
  const n = now();
  const s = (r.restriction_start_vn || r.restriction_start_cn)
    ? new Date(r.restriction_start_vn || r.restriction_start_cn)
    : null;
  const e = (r.restriction_end_vn || r.restriction_end_cn)
    ? new Date(r.restriction_end_vn || r.restriction_end_cn)
    : null;
  const first = r.first_seen_at ? new Date(r.first_seen_at) : null;

  if(first && n - first <= 48 * 3600e3) return 'new';
  if(s && e && n >= s && n <= e) return 'active';
  if(s && n < s) return 'upcoming';
  if(e && n > e) return 'expired';
  return 'unknown';
}

function styleFor(st){
  if(st === 'new') {
    return {color:'#d92d20', fillColor:'#f04438', weight:4, fillOpacity:.27};
  }
  if(st === 'active') {
    return {color:'#f79009', fillColor:'#fdb022', weight:3, fillOpacity:.24};
  }
  if(st === 'upcoming') {
    return {color:'#7f56d9', fillColor:'#9e77ed', weight:3, fillOpacity:.21};
  }
  return {color:'#667085', fillColor:'#98a2b3', weight:2, fillOpacity:.12};
}

function popup(r){
  const src = r.source_url
    ? `<a target="_blank" rel="noopener" href="${esc(r.source_url)}">Nguồn chính thức</a>`
    : '';

  return `
    <b>${esc(r.notice_no_en || r.notice_no_cn)}</b><br>
    ${esc(r.title_vi)}<br>
    <small>${esc(r.body_vi)}</small>
    <hr>
    <b>Bắt đầu (VN):</b> ${fmt(r.restriction_start_vn || r.restriction_start_cn)}<br>
    <b>Kết thúc (VN):</b> ${fmt(r.restriction_end_vn || r.restriction_end_cn)}<br>
    ${src}
  `;
}

function draw(r){
  const st = status(r);
  const sty = styleFor(st);
  const g = r.geometry;
  if(!g) return;

  let l;

  if(g.type === 'Polygon'){
    const latlngs = g.coordinates[0].map(([lon,lat]) => [lat,lon]);
    l = L.polygon(latlngs, sty);
  } else if(g.type === 'Point'){
    const [lon,lat] = g.coordinates;
    if(g.radius_nm){
      l = L.circle([lat,lon], {...sty, radius:g.radius_nm * 1852});
    } else {
      l = L.circleMarker([lat,lon], {...sty, radius:7});
    }
  }

  if(l) l.bindPopup(popup(r)).addTo(layer);
}

// === Bộ lọc ===
// Hiển thị thông báo nếu khoảng thời gian cấm biển giao nhau
// với khoảng Từ ngày -> Đến ngày mà người dùng chọn.
function passFilter(r){
  const y = document.querySelector('#year').value;
  const c = document.querySelector('#category').value;
  const f = document.querySelector('#fromDate').value;
  const t = document.querySelector('#toDate').value;

  if(y !== 'all' && String(r.year) !== y) return false;
  if(c !== 'all' && r.category !== c) return false;

  const rawStart =
    r.restriction_start_vn ||
    r.restriction_start_cn ||
    r.issued_at_cn ||
    null;

  const rawEnd =
    r.restriction_end_vn ||
    r.restriction_end_cn ||
    rawStart;

  const eventStart = rawStart ? new Date(rawStart) : null;
  const eventEnd = rawEnd ? new Date(rawEnd) : eventStart;

  const filterStart = f ? new Date(f + 'T00:00:00+07:00') : null;
  const filterEnd = t ? new Date(t + 'T23:59:59+07:00') : null;

  if(filterStart && eventEnd && eventEnd < filterStart) return false;
  if(filterEnd && eventStart && eventStart > filterEnd) return false;

  return true;
}

function render(){
  layer.clearLayers();

  const rows = records.filter(passFilter);
  rows.forEach(draw);

  document.querySelector('#list').innerHTML = rows.map(r => {
    const st = status(r);
    const label = {
      new:'MỚI',
      active:'ĐANG HIỆU LỰC',
      upcoming:'SẮP HIỆU LỰC',
      expired:'HẾT HIỆU LỰC',
      unknown:'CHƯA RÕ'
    }[st];

    return `
      <article class="card ${st}">
        <h3>${esc(r.notice_no_en || r.notice_no_cn)} · ${esc(r.title_vi)}</h3>
        <div>
          <span class="tag">${label}</span>
          <span class="tag">${esc(r.area_name_vi || '')}</span>
        </div>
        <div class="meta">
          Bắt đầu: ${fmt(r.restriction_start_vn || r.restriction_start_cn)}<br>
          Kết thúc: ${fmt(r.restriction_end_vn || r.restriction_end_cn)}
        </div>
        <div class="summary">${esc(r.body_vi || '')}</div>
      </article>
    `;
  }).join('') || '<p>Không có thông báo phù hợp bộ lọc.</p>';
}

fetch('data/notices.json', {cache:'no-store'})
  .then(r => r.json())
  .then(j => {
    records = j;
    render();

    const ts = records
      .map(x => x.updated_at)
      .filter(Boolean)
      .sort()
      .pop();

    document.querySelector('#lastUpdate').textContent =
      ts ? 'Cập nhật ' + fmt(ts) : `${records.length} thông báo`;
  })
  .catch(() => {
    document.querySelector('#list').innerHTML =
      '<p>Không tải được dữ liệu.</p>';
  });

['fromDate','toDate','year','category'].forEach(id => {
  document.querySelector('#' + id).addEventListener('change', render);
});

document.querySelector('#reset').addEventListener('click', () => {
  document.querySelector('#fromDate').value = '';
  document.querySelector('#toDate').value = '';
  document.querySelector('#year').value = 'all';
  document.querySelector('#category').value = 'all';
  render();
});
