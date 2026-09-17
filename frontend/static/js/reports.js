async function init(){
  const r=await fetch('/api/locations'); const a=await r.json();
  loc.innerHTML=a.map(x=>`<option value="${x.id}">${x.name} — ${x.city||''}, ${x.state||''}</option>`).join('');
  status.textContent=a.length?`${a.length} monitoring locations available. Reports combine observed live traffic with ingested historical-provider hourly evidence where available; provenance remains explicit.`:'No monitoring locations are configured.';
  if(a.length) await preview();
}
async function preview(){
  const id=loc.value;if(!id)return;
  try{
    const r=await fetch(`/api/analytics/location/${id}?days=${days.value}`); if(!r.ok)return;
    const a=await r.json(), q=a.data_quality||{}, c=a.coverage||{}, s=a.summary||{};
    rpLive.textContent=q.observations??0;
    rpHist.textContent=c.historical_provider_hour_buckets??0;
    rpCoverage.textContent=`${c.combined_hourly_coverage_pct??0}%`;
    rpGrade.textContent=s.evidence_grade||q.sufficiency||'—';
    rpValidation.textContent=a.validation?.status||'provider_reference';
    status.textContent=`Requested ${days.value} day(s): ${q.observations||0} live observations + ${c.historical_provider_hour_buckets||0} historical-provider hours. Combined hourly coverage ${c.combined_hourly_coverage_pct||0}%. Missing hours are never fabricated.`;
  }catch(e){}
}
async function download(fmt){
  const id=loc.value;if(!id)return;status.textContent=`Preparing ${fmt.toUpperCase()} export…`;
  const r=await fetch(`/api/reports/location/${id}/export?days=${days.value}&format=${fmt}`);
  if(!r.ok){let m='Export failed';try{const x=await r.json();m=x.detail||m}catch{}status.textContent=typeof m==='string'?m:JSON.stringify(m);return;}
  const b=await r.blob(),cd=r.headers.get('content-disposition')||'',m=cd.match(/filename="?([^";]+)"?/i),name=m?m[1]:`iticas-export.${fmt}`;
  const u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(u);
  status.textContent=`${name} generated successfully. Validation, provenance and decision-intelligence metadata included.`;
}
document.querySelectorAll('[data-format]').forEach(b=>b.addEventListener('click',()=>download(b.dataset.format)));
loc.addEventListener('change',preview);days.addEventListener('change',preview);init();
