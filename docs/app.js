'use strict';
const REFRESH_MS=5*60*1000;
const STORAGE_KEY='scs-monitor-v2-seen';
const SOURCE_LABEL={MSA:'Hải sự MSA',MOD:'Bộ Quốc phòng',PLA81:'Quân đội 81.cn',MIRROR:'Nguồn dẫn lại',SEALAGOM:'SeaLagom (tổng hợp)'};
const CATEGORY_LABEL={LIVE_FIRE:'Bắn đạn thật',MILITARY_EXERCISE:'Diễn tập quân sự',JOINT_NAVAL_AIR_EXERCISE:'Liên hợp hải-không',COMBAT_READINESS_PATROL:'Tuần tra sẵn sàng chiến đấu',NAVAL_EXERCISE:'Diễn tập hải quân',AIR_EXERCISE:'Diễn tập không quân',MILITARY_TRAINING:'Huấn luyện quân sự',OTHER_MILITARY:'Hoạt động quân sự khác'};
const palette={active:'#e39426',upcoming:'#8252cf',expired:'#64748b',unknown:'#5590b2',landmark:'#1b8db6'};
const $=(id)=>document.getElementById(id);
const esc=(s)=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const parseDate=(s)=>{if(!s)return null;const d=new Date(s);return isNaN(d.getTime())?null:d;};
const stamp=(s)=>{const d=parseDate(s);return d?new Intl.DateTimeFormat('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',dateStyle:'short',timeStyle:'short'}).format(d):'Chưa có';};
const dateOnly=(s)=>{const d=parseDate(s);return d?new Intl.DateTimeFormat('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',year:'numeric',month:'2-digit',day:'2-digit'}).format(d):'Chưa có';};
const num=(n)=>new Intl.NumberFormat('vi-VN').format(n||0);
const textnorm=(s)=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const validURL=(s)=>{try{const u=new URL(s);return ['https:','http:'].includes(u.protocol)?u.href:null;}catch{return null;}};
let events=[],health=[],indexYears=[],lastDatasetSignature='',lastSuccessfulCheck=null;
let layerById=new Map();
let isFetching=false;

const map=L.map('map',{preferCanvas:true}).setView([14.5,113],5);
const normal=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap',maxZoom:18});
const satellite=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{attribution:'Tiles © Esri, Maxar, Earthstar Geographics',maxZoom:18});
(localStorage.getItem('scs-map-base')==='satellite'?satellite:normal).addTo(map);
L.control.layers({'🗺️ Bản đồ thường':normal,'🛰️ Vệ tinh':satellite},null,{collapsed:true}).addTo(map);
map.on('baselayerchange',e=>localStorage.setItem('scs-map-base',e.layer===satellite?'satellite':'normal'));
const shapes=L.layerGroup().addTo(map);

function isActive(e){
 const s=parseDate(e.start_at),t=parseDate(e.end_at),n=new Date();
 if(!(s&&t&&n>=s&&n<=t))return false;
 if(e.date_precision==='DAILY_WINDOWS'&&e.daily_window_cn){
  const hhmm=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(n);
  const {start_cn:a,end_cn:b}=e.daily_window_cn;
  if(!a||!b)return false;
  return a<=b?hhmm>=a&&hhmm<=b:hhmm>=a||hhmm<=b;
 }
 return true;
}
function state(e){const s=parseDate(e.start_at),t=parseDate(e.end_at),n=new Date();if(s&&t&&n>=s&&n<=t)return isActive(e)?'active':'unknown';if(s&&s>n)return 'upcoming';if(t&&t<n)return 'expired';return 'unknown';}
function eventDay(e){return e.start_at||e.published_at||null;}
function sourceNames(e){return [...new Set((e.sources||[]).map(x=>x.source))];}
function matches(e){
 const q=textnorm($('search').value.trim());
 const year=$('year').value,cat=$('category').value,src=$('source').value;
 if(year!=='all'&&String(e.year)!==year)return false;
 if(cat!=='all'&&e.category!==cat)return false;
 if(src!=='all'&&!sourceNames(e).includes(src))return false;
 if($('activeOnly').checked&&!isActive(e))return false;
 if(q){const blob=textnorm([e.title_vi,e.title_zh,e.summary_vi,e.summary_zh,e.place_vi,e.place_zh,e.notice_number,e.event_id].join(' '));if(!blob.includes(q))return false;}
 const from=$('fromDate').value,to=$('toDate').value;
 const a=parseDate(e.start_at||e.published_at),b=parseDate(e.end_at||e.start_at||e.published_at);
 if(from&&b&&b<new Date(from+'T00:00:00+07:00'))return false;
 if(to&&a&&a>new Date(to+'T23:59:59+07:00'))return false;
 return true;
}
function sourceAnchor(e){return (e.sources||[]).map(s=>{const u=validURL(s.url);return u?`<a class="source-link" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(SOURCE_LABEL[s.source]||s.source||'Nguồn')} ↗</a>`:'';}).filter(Boolean).join(' · ');}
function timeNote(e){
 if(e.date_precision==='PUBLICATION_DATE_ONLY')return `Ngày công bố: ${stamp(e.published_at)} (không xác nhận là giờ hoạt động)`;
 if(e.date_precision==='DAILY_WINDOWS')return `Trong khoảng ${stamp(e.start_at)} – ${stamp(e.end_at)}; chỉ hoạt động theo giờ ${esc(e.daily_window_cn?.start_cn||'?')}–${esc(e.daily_window_cn?.end_cn||'?')} (UTC+8). Không phải cấm liên tục.`;
 if(e.date_precision==='DATE_RANGE_DAY_LEVEL'||e.date_precision==='DATE_DAY_LEVEL')return `Từ ${stamp(e.start_at)} – ${stamp(e.end_at)} (chỉ xác định theo ngày)`;
 if(e.start_at||e.end_at)return `Từ: ${stamp(e.start_at)} · Đến: ${stamp(e.end_at)}`;
 return `Ngày công bố: ${stamp(e.published_at)} · Chưa xác định giờ hoạt động`;
}
function popup(e){
 const precision=e.geometry_precision==='LANDMARK_ONLY'?'⚠ Điểm này là mốc địa danh được bài báo nhắc tới, KHÔNG phải vị trí hoặc ranh giới hoạt động.':e.geometry_precision==='MSA_COORDINATES'?'Vùng trích từ tọa độ cảnh báo hàng hải.':e.geometry_precision==='MSA_REPOST_COORDINATES'?'Tọa độ trích từ bản dẫn lại; cần đối chiếu thông báo gốc.':'Vị trí chưa được xác nhận.';
 return `<div><b>${esc(e.title_vi)}</b><p>${esc(e.summary_vi||'')}</p><small>${esc(timeNote(e))}</small><p><b>${esc(precision)}</b></p><div class="popup-zh">${esc(e.title_zh||'')}</div>${sourceAnchor(e)}</div>`;
}
function draw(e){
 const geom=e.geometry;if(!geom)return;
 const landmark=e.geometry_precision==='LANDMARK_ONLY';const clr=landmark?palette.landmark:palette[state(e)];
 let marker=null;
 try{
   if(geom.type==='Polygon'&&Array.isArray(geom.coordinates?.[0])){
     const pts=geom.coordinates[0].map(p=>[p[1],p[0]]);
     if(pts.length>=3)marker=L.polygon(pts,{color:clr,weight:3,fillOpacity:.18});
   }else if(geom.type==='Point'&&Array.isArray(geom.coordinates)){
     const p=[geom.coordinates[1],geom.coordinates[0]];
     if(geom.radius_nm&&!landmark){marker=L.circle(p,{radius:Number(geom.radius_nm)*1852,color:clr,weight:3,fillOpacity:.18});}
     else marker=L.circleMarker(p,{radius:landmark?7:6,color:clr,fillColor:clr,fillOpacity:landmark?.35:.7,weight:2,dashArray:landmark?'4 3':null});
   }
   if(marker){marker.bindPopup(popup(e),{maxWidth:340});marker.addTo(shapes);layerById.set(e.event_id,marker);}
 }catch(err){console.warn('Invalid geometry',e.event_id,err);}
}
function focusEvent(id){const marker=layerById.get(id);if(!marker)return;try{const bounds=marker.getBounds?marker.getBounds():null;if(bounds&&bounds.isValid())map.fitBounds(bounds.pad(.6),{maxZoom:9});else map.setView(marker.getLatLng(),9);marker.openPopup();document.querySelector('.map-panel').scrollIntoView({behavior:'smooth',block:'nearest'});}catch(err){console.warn(err);}}
function render(){
 const filtered=events.filter(matches);
 shapes.clearLayers();layerById.clear();
 for(const e of filtered)draw(e);
 $('metricTotal').textContent=num(events.length);
 $('metricFiltered').textContent=num(filtered.length);
 $('metricActive').textContent=num(filtered.filter(isActive).length);
 $('metricMapped').textContent=num(filtered.filter(e=>!!e.geometry).length);
 $('resultCount').textContent=`${num(filtered.length)} kết quả`;
 const list=$('list');
 list.innerHTML=filtered.slice(0,600).map(e=>{
   const st=state(e);const recent=parseDate(e.first_seen_at)&&Date.now()-parseDate(e.first_seen_at).getTime()<48*3600000;
   const kind=e.translation_status==='machine'?'Dịch máy (cần kiểm tra)':'Tóm tắt theo từ khóa; xem nguyên văn';
   return `<article class="event-item ${st}" tabindex="0" data-id="${esc(e.event_id)}" title="Bấm để xem trên bản đồ (nếu có tọa độ)">
     <div class="event-title">${esc(e.notice_number?e.notice_number+' · ':'')}${esc(e.title_vi)}</div>
     <div><span class="tag ${st==='active'?'live':''}">${esc(st==='active'?'ĐANG HIỆU LỰC':st==='upcoming'?'SẮP TỚI':st==='expired'?'HẾT HẠN':'CHƯA RÕ')}</span><span class="tag">${esc(CATEGORY_LABEL[e.category]||e.category)}</span>${recent?'<span class="tag new">MỚI GHI NHẬN</span>':''}</div>
     <div class="event-meta">${esc(e.place_vi||'Biển Đông')} · ${esc(timeNote(e))}<br>${esc(sourceNames(e).map(s=>SOURCE_LABEL[s]||s).join(', '))} · ${esc(kind)}</div>
     <div class="event-summary">${esc(e.summary_vi||'Chưa có tóm tắt tiếng Việt.')}<br><span class="date-pill">${esc(e.title_zh||'')}</span></div>${sourceAnchor(e)}
   </article>`;
 }).join('')||'<div class="empty">Chưa có sự kiện phù hợp. Dữ liệu lịch sử có thể chưa được thu thập đầy đủ.</div>';
 if(filtered.length>600)list.insertAdjacentHTML('beforeend',`<div class="empty">Đang hiển thị 600/${filtered.length} kết quả. Dùng bộ lọc để thu hẹp.</div>`);
 renderCharts(filtered);
}
function renderCharts(filtered){
 const overall=events.reduce((m,e)=>(m[e.year]=(m[e.year]||0)+1,m),{});
 const years=indexYears.length?indexYears:Array.from({length:new Date().getFullYear()-2019},(_,i)=>2020+i);
 const max=Math.max(1,...Object.values(overall));
 $('yearChart').innerHTML=years.map(y=>`<button type="button" class="year-col ${$('year').value===String(y)?'on':''}" data-year="${y}" aria-label="Lọc năm ${y}, ${overall[y]||0} sự kiện"><span class="value">${overall[y]||0}</span><span class="bar-wrap"><span class="bar" style="height:${Math.max(2,(overall[y]||0)/max*100)}%"></span></span><span class="year">${y}</span></button>`).join('');
 const types=Object.entries(CATEGORY_LABEL).map(([c,name])=>[name,filtered.filter(e=>e.category===c).length]).sort((a,b)=>b[1]-a[1]);
 const maxT=Math.max(1,...types.map(x=>x[1]));
 $('typeChart').innerHTML=types.map(([name,n])=>`<div class="type-row"><span>${esc(name)}</span><span class="track"><span class="fill" style="width:${Math.max(n?2:0,n/maxT*100)}%;display:block"></span></span><strong>${n}</strong></div>`).join('');
 const y=$('year').value==='all'?new Date().getFullYear():Number($('year').value);
 $('monthYearLabel').textContent=y;
 const monthly=Array.from({length:12},(_,i)=>filtered.filter(e=>{const s=parseDate(eventDay(e));return s&&s.getFullYear()===y&&s.getMonth()===i;}).length);
 const mx=Math.max(1,...monthly);
 $('monthChart').innerHTML=monthly.map((n,i)=>`<div class="month-col"><strong>${n}</strong><div class="bar-track"><div class="bar" style="height:${Math.max(n?2:0,n/mx*100)}%"></div></div><span>T${i+1}</span></div>`).join('');
}
function renderHealth(progress){
 const sources=['MSA','SEALAGOM','MOD','PLA81'];
 $('health').innerHTML=`<div class="health-grid">${sources.map(src=>{
   const h=health.find(x=>x.source===src);
   if(!h)return `<div class="health-source"><strong>${esc(SOURCE_LABEL[src])}</strong><small>Chưa có lần kiểm tra ghi nhận.</small></div>`;
   const bad=!h.last_success||!!h.last_error;
   return `<div class="health-source"><strong>${esc(SOURCE_LABEL[src])}</strong><small class="${bad?'warning':''}">${bad?'⚠ Cần kiểm tra nguồn':'● Đã thu thập tài liệu'}</small><small>Lần thử: ${stamp(h.last_attempt)}</small><small>Lần lấy được: ${stamp(h.last_success)}</small><small>URL tìm thấy / tài liệu phù hợp: ${num(h.discovered)} / ${num(h.processed)}</small>${h.last_error?`<small class="warning">${esc(String(h.last_error).slice(0,170))}</small>`:''}</div>`;
 }).join('')}</div>`;
 const count=(progress?.attempted_jobs||[]).length;
 $('coverageNote').textContent=`Đã thử truy vấn lịch sử ${count} tháng. Số tháng được thử không bảo đảm dữ liệu đầy đủ. Trạng thái nguồn thể hiện lần kiểm tra đã ghi lại; các 403/422 hoặc lỗi lập chỉ mục có thể làm thiếu sự kiện.`;
}
function newRecordBanner(data){
 const keys=data.map(e=>e.event_id),raw=localStorage.getItem(STORAGE_KEY);
 if(raw===null){localStorage.setItem(STORAGE_KEY,JSON.stringify(keys));return;}
 let seen;try{seen=new Set(JSON.parse(raw));}catch{seen=new Set(keys);}
 const added=data.filter(e=>!seen.has(e.event_id));keys.forEach(k=>seen.add(k));
 localStorage.setItem(STORAGE_KEY,JSON.stringify([...seen]));
 if(!added.length)return;
 $('bannerDetails').textContent=`${added.length} mục mới: ${added.slice(0,5).map(x=>x.notice_number||x.title_vi).join(' · ')}${added.length>5?'…':''}`;
 $('newBanner').hidden=false;
 document.title='🚨 '+document.title.replace(/^🚨\s*/, '');
}
async function getJSON(path){const res=await fetch(`${path}?t=${Date.now()}`,{cache:'no-store'});if(!res.ok)throw Error(`${path}: HTTP ${res.status}`);return await res.json();}
async function load(){
 if(isFetching)return;isFetching=true;
 try{
   const [idx,he,progress]=await Promise.all([getJSON('data/events-index.json'),getJSON('data/health.json'),getJSON('data/backfill-progress.json')]);
   const yr=idx.years||[];
   const sets=await Promise.all(yr.map(y=>getJSON('data/events-'+y+'.json')));
   const newEvents=sets.flat().filter(e=>e&&e.event_id);
   newRecordBanner(newEvents);
   const sig=JSON.stringify(newEvents.map(x=>[x.event_id,x.updated_at]));
   events=newEvents;indexYears=yr;health=he.sources||[];
   updateYearOptions();updateCategoryOptions();
   render();renderHealth(progress);
   lastSuccessfulCheck=new Date();
   $('lastUpdate').textContent=`${num(events.length)} mục · Kiểm tra ${stamp(lastSuccessfulCheck.toISOString())}`;
   lastDatasetSignature=sig;
 }catch(err){console.error('SCS data update failed',err);$('lastUpdate').textContent=`⚠ Không tải được dữ liệu mới${lastSuccessfulCheck?', giữ bản gần nhất':''}`;}
 finally{isFetching=false;}
}
function updateYearOptions(){
 const old=$('year').value;
 $('year').innerHTML='<option value="all">2020 – nay</option>'+indexYears.slice().reverse().map(y=>`<option value="${y}">${y}</option>`).join('');
 if([...$('year').options].some(o=>o.value===old))$('year').value=old;
}
function updateCategoryOptions(){
 const old=$('category').value;
 $('category').innerHTML='<option value="all">Tất cả loại</option>'+Object.entries(CATEGORY_LABEL).map(([v,t])=>`<option value="${v}">${esc(t)}</option>`).join('');
 if([...$('category').options].some(o=>o.value===old))$('category').value=old;
}
['year','category','source','fromDate','toDate','activeOnly'].forEach(id=>$(id).addEventListener('change',render));
let searchTimeout;
$('search').addEventListener('input',()=>{clearTimeout(searchTimeout);searchTimeout=setTimeout(render,150);});
$('reset').addEventListener('click',()=>{
 for(const id of ['search','fromDate','toDate'])$(id).value='';
 for(const id of ['year','category','source'])$(id).value='all';
 $('activeOnly').checked=false;render();
});
$('yearChart').addEventListener('click',e=>{const target=e.target.closest('[data-year]');if(target){$('year').value=target.dataset.year;render();}});
$('list').addEventListener('click',e=>{if(e.target.closest('a'))return;const card=e.target.closest('[data-id]');if(card)focusEvent(card.dataset.id);});
$('list').addEventListener('keydown',e=>{if(e.key==='Enter'){const card=e.target.closest('[data-id]');if(card)focusEvent(card.dataset.id);}});
$('closeBanner').addEventListener('click',()=>{$('newBanner').hidden=true;document.title=document.title.replace(/^🚨\s*/, '');});
load();
setInterval(load,REFRESH_MS);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
setInterval(()=>{if(events.length)render();},60000);
