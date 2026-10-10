const AUTO_REFRESH_MS = 5 * 60 * 1000;
const SEEN_KEY = 'hainan-seen-records-v1';
const ACTIVE_KEY = 'hainan-active-only-v1';

const map = L.map('map').setView([18.9, 110.0], 6);

const normalMap = L.tileLayer(
  'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {
    maxZoom: 18,
    attribution: '&copy; OpenStreetMap contributors'
  }
);

const satelliteMap = L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  {
    maxZoom: 18,
    attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics'
  }
);

const savedBaseMap = localStorage.getItem('hainan-base-map');
(savedBaseMap === 'satellite' ? satelliteMap : normalMap).addTo(map);

L.control.layers({
  '🗺️ Bản đồ thường': normalMap,
  '🛰️ Vệ tinh': satelliteMap
}).addTo(map);

map.on('baselayerchange', e => {
  localStorage.setItem(
    'hainan-base-map',
    e.layer === satelliteMap ? 'satellite' : 'normal'
  );
});

const layer = L.layerGroup().addTo(map);

let records = [];
let loading = false;
let activeOnly = localStorage.getItem(ACTIVE_KEY) === '1';

const esc = s => String(s ?? '').replace(/[&<>'"]/g, c => ({
  '&':'&amp;',
  '<':'&lt;',
  '>':'&gt;',
  "'":'&#39;',
  '"':'&quot;'
}[c]));

function safeDate(v) {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

function fmt(v) {
  const d = safeDate(v);
  if (!d) return 'Chưa trích xuất';

  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'short',
    timeStyle: 'short',
    timeZone: 'Asia/Ho_Chi_Minh'
  }).format(d);
}

function recordKey(r) {
  return String(
    r.record_id ||
    r.notice_no_en ||
    r.notice_no_cn ||
    `${r.year}|${r.source_url}|${r.title_vi}`
  );
}

function restrictionWindow(r) {
  return {
    start: safeDate(
      r.restriction_start_vn ||
      r.restriction_start_cn
    ),
    end: safeDate(
      r.restriction_end_vn ||
      r.restriction_end_cn
    )
  };
}

function status(r) {
  const now = new Date();
  const {start, end} = restrictionWindow(r);

  if (start && end && now >= start && now <= end) return 'active';
  if (start && now < start) return 'upcoming';
  if (end && now > end) return 'expired';

  return 'unknown';
}

function isActive(r) {
  return status(r) === 'active';
}

function isRecent(r) {
  const d = safeDate(r.first_seen_at);
  if (!d) return false;

  const age = Date.now() - d.getTime();
  return age >= 0 && age <= 48 * 3600 * 1000;
}

function styleFor(st) {
  if (st === 'active') {
    return {
      color:'#f79009',
      fillColor:'#fdb022',
      weight:4,
      fillOpacity:.28
    };
  }

  if (st === 'upcoming') {
    return {
      color:'#7f56d9',
      fillColor:'#9e77ed',
      weight:3,
      fillOpacity:.21
    };
  }

  return {
    color:'#667085',
    fillColor:'#98a2b3',
    weight:2,
    fillOpacity:.12
  };
}

function popup(r) {
  const src = r.source_url
    ? `<a target="_blank" rel="noopener" href="${esc(r.source_url)}">Mở nguồn</a>`
    : '';

  return `
    <b>${esc(r.notice_no_en || r.notice_no_cn)}</b><br>
    ${esc(r.title_vi || '')}<br>
    <small>${esc(r.body_vi || '')}</small>
    <hr>
    <b>Bắt đầu (VN):</b>
    ${fmt(r.restriction_start_vn || r.restriction_start_cn)}<br>
    <b>Kết thúc (VN):</b>
    ${fmt(r.restriction_end_vn || r.restriction_end_cn)}<br>
    ${src}
  `;
}

function draw(r) {
  const g = r.geometry;
  if (!g) return;

  const sty = styleFor(status(r));
  let obj;

  if (g.type === 'Polygon' && Array.isArray(g.coordinates?.[0])) {
    const pts = g.coordinates[0].map(([lon, lat]) => [lat, lon]);

    if (pts.length >= 3) {
      obj = L.polygon(pts, sty);
    }
  }

  if (g.type === 'Point' && Array.isArray(g.coordinates)) {
    const [lon, lat] = g.coordinates;

    if (g.radius_nm) {
      obj = L.circle(
        [lat, lon],
        {...sty, radius: Number(g.radius_nm) * 1852}
      );
    } else {
      obj = L.circleMarker(
        [lat, lon],
        {...sty, radius: 7}
      );
    }
  }

  if (obj) {
    obj.bindPopup(popup(r)).addTo(layer);
  }
}

function passFilter(r) {
  const year = document.querySelector('#year').value;
  const category = document.querySelector('#category').value;
  const from = document.querySelector('#fromDate').value;
  const to = document.querySelector('#toDate').value;

  if (year !== 'all' && String(r.year) !== year) return false;
  if (category !== 'all' && r.category !== category) return false;

  if (activeOnly && !isActive(r)) return false;

  const rawStart =
    r.restriction_start_vn ||
    r.restriction_start_cn ||
    r.issued_at_cn;

  const rawEnd =
    r.restriction_end_vn ||
    r.restriction_end_cn ||
    rawStart;

  const start = safeDate(rawStart);
  const end = safeDate(rawEnd) || start;

  const filterStart = from
    ? safeDate(from + 'T00:00:00+07:00')
    : null;

  const filterEnd = to
    ? safeDate(to + 'T23:59:59+07:00')
    : null;

  if (filterStart && end && end < filterStart) return false;
  if (filterEnd && start && start > filterEnd) return false;

  return true;
}

function render() {
  layer.clearLayers();

  const rows = records.filter(passFilter);
  rows.forEach(draw);

  document.querySelector('#list').innerHTML =
    rows.map(r => {
      const st = status(r);

      const label = {
        active:'ĐANG HIỆU LỰC',
        upcoming:'SẮP HIỆU LỰC',
        expired:'HẾT HIỆU LỰC',
        unknown:'CHƯA RÕ'
      }[st];

      const newTag = isRecent(r)
        ? '<span class="tag new-tag">MỚI GHI NHẬN</span>'
        : '';

      return `
        <article class="card ${st}">
          <h3>
            ${esc(r.notice_no_en || r.notice_no_cn)}
            · ${esc(r.title_vi || '')}
          </h3>

          <div>
            <span class="tag">${label}</span>
            ${newTag}
            ${
              r.area_name_vi
              ? `<span class="tag">${esc(r.area_name_vi)}</span>`
              : ''
            }
          </div>

          <div class="meta">
            Bắt đầu:
            ${fmt(r.restriction_start_vn || r.restriction_start_cn)}
            <br>
            Kết thúc:
            ${fmt(r.restriction_end_vn || r.restriction_end_cn)}
          </div>

          <div class="summary">
            ${esc(r.body_vi || '')}
          </div>
        </article>
      `;
    }).join('') ||
    (
      activeOnly
      ? '<p>Hiện không có cảnh báo nào đang hiệu lực.</p>'
      : '<p>Không có thông báo phù hợp bộ lọc.</p>'
    );
}

function makeExtraUI() {
  const style = document.createElement('style');

  style.textContent = `
    #activeOnly {
      cursor:pointer;
    }

    #activeOnly.on {
      background:#f79009;
      border-color:#f79009;
      color:#fff;
      font-weight:700;
    }

    #newBanner {
      display:none;
      background:#b42318;
      color:#fff;
      padding:12px 14px;
      font-weight:700;
      align-items:center;
      justify-content:space-between;
      gap:10px;
      position:relative;
      z-index:1002;
    }

    #newBanner.show {
      display:flex;
    }

    #newBanner button {
      border:0;
      border-radius:8px;
      padding:7px 10px;
      background:#fff;
      color:#b42318;
      font-weight:700;
      cursor:pointer;
    }

    .new-tag {
      background:#fee4e2 !important;
      color:#b42318;
      font-weight:700;
    }

    #refreshInfo {
      font-size:11px;
      color:#667085;
      align-self:center;
    }
  `;

  document.head.appendChild(style);

  const controls = document.querySelector('.controls');

  const button = document.createElement('button');
  button.id = 'activeOnly';
  button.type = 'button';

  const reset = document.querySelector('#reset');
  controls.insertBefore(button, reset);

  const refreshInfo = document.createElement('span');
  refreshInfo.id = 'refreshInfo';
  refreshInfo.textContent = '↻ Tự làm mới mỗi 5 phút';
  controls.appendChild(refreshInfo);

  const banner = document.createElement('div');
  banner.id = 'newBanner';

  banner.innerHTML = `
    <span id="newBannerText">🚨 CÓ CẢNH BÁO MỚI</span>
    <button id="closeBanner" type="button">Đã xem</button>
  `;

  document.querySelector('header').insertAdjacentElement(
    'afterend',
    banner
  );

  button.addEventListener('click', () => {
    activeOnly = !activeOnly;

    localStorage.setItem(
      ACTIVE_KEY,
      activeOnly ? '1' : '0'
    );

    updateActiveButton();
    render();
  });

  document.querySelector('#closeBanner').addEventListener(
    'click',
    () => {
      banner.classList.remove('show');
      document.title = document.title.replace(/^🚨\s*/, '');
    }
  );

  updateActiveButton();
}

function updateActiveButton() {
  const btn = document.querySelector('#activeOnly');
  if (!btn) return;

  btn.classList.toggle('on', activeOnly);

  btn.textContent = activeOnly
    ? '✓ Chỉ hiện đang hiệu lực'
    : 'Chỉ hiện đang hiệu lực';
}

function findNewRecords(data) {
  const raw = localStorage.getItem(SEEN_KEY);
  const current = data.map(recordKey);

  // Lần đầu mở phiên bản mới:
  // coi dữ liệu hiện tại là mốc, không báo nhầm toàn bộ là mới.
  if (raw === null) {
    localStorage.setItem(
      SEEN_KEY,
      JSON.stringify(current)
    );

    return [];
  }

  let seen = [];

  try {
    seen = JSON.parse(raw);
  } catch {
    seen = [];
  }

  const seenSet = new Set(seen);

  const found = data.filter(
    r => !seenSet.has(recordKey(r))
  );

  current.forEach(k => seenSet.add(k));

  localStorage.setItem(
    SEEN_KEY,
    JSON.stringify([...seenSet])
  );

  return found;
}

function showNewBanner(found) {
  if (!found.length) return;

  const names = found.map(
    r => r.notice_no_en || r.notice_no_cn
  );

  document.querySelector('#newBannerText').textContent =
    `🚨 CÓ CẢNH BÁO MỚI — ${names.join(', ')}`;

  document.querySelector('#newBanner').classList.add('show');

  if (!document.title.startsWith('🚨')) {
    document.title = '🚨 ' + document.title;
  }
}

async function loadData() {
  if (loading) return;

  loading = true;

  try {
    const response = await fetch(
      `data/notices.json?t=${Date.now()}`,
      {cache:'no-store'}
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();

    const found = findNewRecords(data);

    records = data;

    render();

    const ts = records
      .map(x => safeDate(x.updated_at))
      .filter(Boolean)
      .sort((a, b) => b - a)[0];

    document.querySelector('#lastUpdate').textContent =
      ts
      ? 'Cập nhật ' + fmt(ts)
      : `${records.length} thông báo`;

    if (found.length) {
      showNewBanner(found);
    }

  } catch (err) {
    console.error(err);

    document.querySelector('#lastUpdate').textContent =
      'Lỗi tải dữ liệu';
  } finally {
    loading = false;
  }
}

['fromDate','toDate','year','category'].forEach(id => {
  document.querySelector('#' + id)
    .addEventListener('change', render);
});

document.querySelector('#reset').addEventListener('click', () => {
  document.querySelector('#fromDate').value = '';
  document.querySelector('#toDate').value = '';
  document.querySelector('#year').value = 'all';
  document.querySelector('#category').value = 'all';

  activeOnly = false;
  localStorage.setItem(ACTIVE_KEY, '0');

  updateActiveButton();
  render();
});

makeExtraUI();

loadData();

setInterval(loadData, AUTO_REFRESH_MS);

// Khi quay lại tab thì kiểm tra dữ liệu ngay.
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    loadData();
  }
});
