const fmt=(v,d=2)=>v==null?'—':Number(v).toFixed(d);
const esc=v=>String(v??'').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));

async function init(){
  const r=await fetch('/api/locations');const a=await r.json();
  loc.innerHTML=a.map(x=>`<option value="${x.id}">${esc(x.name)} — ${esc(x.city||'')}, ${esc(x.state||'')}</option>`).join('');
  if(a.length)run();
}
function coverageMessage(a){
  const c=a.coverage,q=a.data_quality;
  let text=`Observed-data readiness: <b>${q.sufficiency}</b> · ${q.observations} genuine observations · ${c.combined_hour_buckets_with_data}/${c.hour_buckets_total} requested hourly buckets contain live or historical-provider evidence (${fmt(c.combined_hourly_coverage_pct)}%) · Sources: ${q.provider_sources.join(', ')||'none'}.`;
  if(c.same_dataset_as_last_24h)text+=` <b>This ${a.period.days}-day selection currently contains the same stored live observations as the last 24 hours because there are no older live records in the selected window.</b>`;
  if(a.limitations.length)text+=' '+a.limitations[0];
  return text;
}
function severityColor(ci){
  if(ci==null)return '#64748b';
  if(ci<.2)return '#4ade80';if(ci<.35)return '#86efac';if(ci<.5)return '#facc15';if(ci<.7)return '#fb923c';return '#ef4444';
}
function renderChronological(a){
  const rows=a.hourly_timeseries.filter(x=>x.data_status!=='missing'&&x.mean_congestion_index!=null);
  if(!rows.length)return `<div class="empty-chart">No observed or historical-provider hourly evidence exists in this period. Missing hours are not fabricated.</div>`;
  const W=1200,H=330,L=80,R=30,T=35,B=75,plotW=W-L-R,plotH=H-T-B;
  const start=new Date(a.period.requested_from_nigeria).getTime(),end=new Date(a.period.requested_to_nigeria).getTime();
  const maxCI=Math.max(.25,...rows.map(x=>Number(x.mean_congestion_index)||0));
  const x=t=>L+((new Date(t).getTime()-start)/Math.max(1,end-start))*plotW;
  const y=v=>T+plotH-(Number(v)/maxCI)*plotH;
  let s=`<svg viewBox="0 0 ${W} ${H}" class="temporal-svg" role="img" aria-label="Chronological congestion evidence">`;
  for(let i=0;i<=4;i++){const yy=T+plotH*i/4,lab=(maxCI*(1-i/4)).toFixed(2);s+=`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#26364d"/><text x="${L-12}" y="${yy+5}" text-anchor="end" fill="#91a6c2" font-size="13">${lab}</text>`;}
  s+=`<text x="18" y="${T+plotH/2}" fill="#91a6c2" font-size="13" transform="rotate(-90 18 ${T+plotH/2})">Congestion index</text>`;
  rows.forEach(r=>{const xx=x(r.hour_start),yy=y(r.mean_congestion_index),c=severityColor(r.mean_congestion_index),origin=r.data_status==='historical_provider'?'Historical provider':'Observed live';s+=`<line x1="${xx}" y1="${T+plotH}" x2="${xx}" y2="${yy}" stroke="${c}" stroke-opacity=".35"/><circle cx="${xx}" cy="${yy}" r="5" fill="${c}" stroke="#fff" stroke-width="1"><title>${r.hour_start} · ${origin} · CI ${r.mean_congestion_index} · speed ${r.mean_speed_kmh??'—'} km/h</title></circle>`;});
  const ticks=Math.min(6,Math.max(2,a.period.days+1));for(let i=0;i<ticks;i++){const tm=start+(end-start)*i/(ticks-1),xx=L+plotW*i/(ticks-1),d=new Date(tm);s+=`<line x1="${xx}" y1="${T+plotH}" x2="${xx}" y2="${T+plotH+6}" stroke="#91a6c2"/><text x="${xx}" y="${T+plotH+25}" text-anchor="middle" fill="#91a6c2" font-size="12">${d.toLocaleDateString('en-NG',{day:'2-digit',month:'short'})}</text>`;}
  s+=`<text x="${L}" y="${H-18}" fill="#58e69a" font-size="13">● observed live</text><text x="${L+135}" y="${H-18}" fill="#60a5fa" font-size="13">Historical-provider points retain their own provenance in tables</text>`;
  s+=`</svg><div class="chart-footnote">${rows.length} evidence-bearing hourly bucket(s) plotted across ${a.coverage.hour_buckets_total} requested hours. No line is drawn through missing periods, avoiding false continuity.</div>`;
  return s;
}
function renderClockProfile(a){
  const rows=a.hourly_profile||[];if(!rows.length)return `<div class="empty-chart">Not enough evidence yet for a clock-hour pattern.</div>`;
  const W=1200,H=300,L=70,R=25,T=35,B=55,plotW=W-L-R,plotH=H-T-B,max=Math.max(.15,...rows.map(x=>Number(x.mean_congestion_index)||0));
  const by=new Map(rows.map(x=>[Number(x.hour),x]));let s=`<svg viewBox="0 0 ${W} ${H}" class="temporal-svg">`;
  for(let h=0;h<24;h++){const r=by.get(h),x=L+h*plotW/24+4,w=Math.max(10,plotW/24-8),v=r?Number(r.mean_congestion_index)||0:0,y=T+plotH-(v/max)*plotH,hh=(v/max)*plotH,c=r?severityColor(v):'#233047';s+=`<rect x="${x}" y="${r?y:T+plotH-3}" width="${w}" height="${r?Math.max(3,hh):3}" rx="3" fill="${c}"><title>${String(h).padStart(2,'0')}:00 · CI ${r?.mean_congestion_index??'no evidence'} · n=${r?.samples??0}</title></rect>`;if(h%2===0)s+=`<text x="${x+w/2}" y="${T+plotH+22}" text-anchor="middle" fill="#91a6c2" font-size="11">${String(h).padStart(2,'0')}</text>`;}
  s+=`<text x="${L}" y="${H-8}" fill="#91a6c2" font-size="13">Clock hour (West Africa Time) · bars exist only where evidence is available</text></svg>`;return s;
}
function renderEvidenceTable(a){
  const rows=a.hourly_timeseries.filter(x=>x.data_status!=='missing').slice(-18).reverse();
  if(!rows.length)return '<tr><td colspan="6">No evidence-bearing hours in selected period.</td></tr>';
  return rows.map(r=>`<tr><td>${esc(r.hour_start)}</td><td>${esc(r.data_status)}</td><td>${r.samples}</td><td>${fmt(r.mean_speed_kmh)} km/h</td><td>${fmt(r.mean_congestion_index,3)}</td><td>${fmt(r.mean_delay_seconds)} s</td></tr>`).join('');
}
async function run(){
  const id=loc.value,d=days.value;if(!id)return;
  const [r,n]=await Promise.all([fetch(`/api/analytics/location/${id}?days=${d}`),fetch(`/api/analytics/network?days=${d}`)]);
  const a=await r.json(),net=await n.json();
  quality.innerHTML=`<div class="notice">${coverageMessage(a)}</div>`;
  const s=a.summary,c=a.coverage;
  metrics.innerHTML=[
    ['Mean speed',fmt(s.mean_speed_kmh)+' km/h'],['Mean free-flow',fmt(s.mean_free_flow_speed_kmh)+' km/h'],
    ['Mean congestion index',fmt(s.mean_congestion_index,3)],['Mean delay',fmt(s.mean_delay_seconds)+' s'],
    ['Speed reduction',fmt(s.mean_speed_reduction_pct)+'%'],['Max congestion index',fmt(s.max_congestion_index,3)],
    ['Evidence hours',`${c.combined_hour_buckets_with_data}/${c.hour_buckets_total}`],['Peak clock hour',s.peak_hour?String(s.peak_hour.hour).padStart(2,'0')+':00':'—']
  ].map(x=>`<div class="metric"><small>${x[0]}</small><strong>${x[1]}</strong></div>`).join('');
  hourChart.innerHTML=renderChronological(a);
  clockChart.innerHTML=renderClockProfile(a);
  evidenceBody.innerHTML=renderEvidenceTable(a);
  ranking.innerHTML=net.ranking.map(x=>`<tr><td>${esc(x.location.name)}</td><td>${esc(x.location.state||'—')}</td><td>${x.observations}</td><td>${fmt(x.hourly_coverage_pct)}%</td><td>${fmt(x.mean_congestion_index,3)}</td><td>${fmt(x.mean_speed_kmh)} km/h</td><td>${esc(x.category)}</td></tr>`).join('')||'<tr><td colspan="7">No stored observations in the selected period.</td></tr>';
  validation.textContent=a.validation.statement+' Independent traffic benchmark: '+a.validation.independent_traffic_benchmark+'. Report ID: '+a.report_identity.report_id+' · Dataset signature: '+a.report_identity.dataset_signature+'.';
}
document.getElementById('run').addEventListener('click',run);init();
