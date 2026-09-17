let locations=[],sessionId=null,watchId=null,pointCount=0,lastCatalog=null;
const $=x=>document.getElementById(x);const esc=v=>String(v??"").replace(/[&<>"']/g,s=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[s]));
function id(){return Number($('researchLoc').value)}function days(){return Number($('researchDays').value)}
async function load(){let r=await fetch('/api/locations');locations=await r.json();$('researchLoc').innerHTML=locations.filter(x=>x.latitude!=null&&x.longitude!=null).map(x=>`<option value="${x.id}">${esc(x.name)}${x.road_name&&x.road_name.toLowerCase()!=x.name.toLowerCase()?` · ${esc(x.road_name)}`:''} — ${esc(x.city||'')}, ${esc(x.state||'')}</option>`).join('');await refresh();}
async function workflow(){const r=await fetch(`/api/research/workflow/${id()}?days=${days()}`);const d=await r.json();$('wizard').innerHTML=d.steps.map(x=>`<div class="step ${x.complete?'done':''} ${x.step===d.next_step?'current':''}"><strong>${x.step}</strong><b>${esc(x.name)}</b><small>${x.complete?' ✓ Complete':x.step===d.next_step?' ← Next':' Pending'}</small></div>`).join('');$('probeCount').textContent=d.probe_count;$('probeObs').textContent=d.probe_observations;$('gnssCount').textContent=d.gnss_points;}
async function refresh(){if(!id())return;$('mainMsg').textContent='Evaluating study readiness…';let r=await fetch(`/api/research/catalog/${id()}?days=${days()}`),d=await r.json();if(!r.ok){$('mainMsg').textContent=d.detail||'Evaluation failed.';return;}lastCatalog=d;$('mainMsg').textContent='Study selected. Follow the numbered steps below.';$('objCount').textContent=`${d.objectives.complete_objectives}/${d.objectives.total_objectives}`;$('objectiveRows').innerHTML=d.objectives.objectives.map(o=>`<div class="objective"><strong>${esc(o.objective)}</strong><span class="badge ${o.status==='complete'?'ok':o.status==='not_started'?'bad':'warn'}">${esc(o.status.replaceAll('_',' '))}</span><span>${esc(o.evidence)}</span><span>${esc(o.next_action)}</span></div>`).join('');$('outputGrid').innerHTML=d.outputs.map(o=>`<div class="output"><strong>${esc(o.name)}</strong><br><small>${esc(o.type)} · ${esc(o.availability)}</small></div>`).join('');await workflow();
if($('toolObjectiveOutput')) $('toolObjectiveOutput').textContent=`${d.objectives.complete_objectives}/${d.objectives.total_objectives} objectives complete.`;
if($('toolGnssOutput')) $('toolGnssOutput').textContent=`${d.survey.sessions} survey session(s), ${d.survey.points} GNSS point(s).`;
if($('toolTemporalOutput')) $('toolTemporalOutput').textContent=`Temporal output available for ${days()} day(s); missing hours remain explicit.`;
if($('toolSpatialOutput')) $('toolSpatialOutput').textContent=`Single-road and optional network spatial analysis available subject to evidence gates.`;
}
async function probes(){let r=await fetch(`/api/research/corridor-probes/${id()}?spacing_m=100`,{method:'POST'}),d=await r.json();const count=(d.created||0)+(d.reused||0),action=d.reused?`${d.reused} existing corridor probe(s) safely reused`:`${d.created} corridor probe(s) created`; $('probeMsg').textContent=r.ok?`${action} at ${d.spacing_m} m spacing.${d.reason?' '+d.reason:''}`:(d.detail||'Probe generation failed.');if($('toolRoadOutput'))$('toolRoadOutput').textContent=r.ok?`${count} probes ready; road/probe files are available without deleting historical observations.`:'No valid road output yet.';await workflow();}
async function scan(){
  const msg=$('scanMsg'),btn=$('scanCorridor');
  btn.disabled=true;
  const started=Date.now();
  msg.textContent='Starting remote corridor scan…';
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  const timer=setInterval(()=>{
    const sec=Math.max(1,Math.floor((Date.now()-started)/1000));
    msg.textContent=`Remote corridor scan is running… ${sec}s elapsed. Please keep this page open; GNSS is not required.`;
  },1000);
  try{
    const r=await fetch(`/api/research/corridor-scan/${id()}`,{method:'POST'});
    const d=await r.json();
    clearInterval(timer);
    if(r.ok){
      msg.textContent=`Corridor scan completed independently: ${d.successful||0} successful, ${d.failed||0} failed, ${d.probes||0} probes.`;
      if($('toolScanOutput'))$('toolScanOutput').textContent=`${d.successful||0}/${d.probes||0} probe results acquired; ${d.failed||0} failed.`;
      await workflow();
    }else{
      msg.textContent=d.detail||'Corridor scan failed.';
      if($('toolScanOutput'))$('toolScanOutput').textContent='No valid scan output yet.';
    }
  }catch(e){
    clearInterval(timer);
    msg.textContent=`Corridor scan request failed: ${e.message}`;
  }finally{
    btn.disabled=false;
  }
}
async function analysis(){ $('analysisMsg').textContent='Running corridor and research analysis…'; let r=await fetch(`/api/research/corridor-analysis/${id()}?days=${days()}`),d=await r.json();$('analysisMsg').textContent=r.ok?`Analysis complete: ${d.probe_count} probes, ${d.observation_count} probe observations, ${d.probes_with_repeated_evidence} probes with repeated evidence. Inferential hotspot readiness: ${d.inferential_hotspot_ready?'YES':'NOT YET'}.`:(d.detail||'Analysis failed.');await refresh();}
async function startSurvey(){if(!navigator.geolocation){$('gnssMsg').textContent='This browser/device does not expose GNSS/geolocation.';return;}const payload={name:$('surveyName').value.trim()||`ITICAS GNSS Survey ${new Date().toLocaleString()}`,location_id:id(),operator:$('surveyOperator').value.trim()||null,purpose:'Traffic congestion GNSS/GIS research survey'};let r=await fetch('/api/research/surveys',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),d=await r.json();if(!r.ok){$('gnssMsg').textContent=d.detail||'Survey could not start.';return;}sessionId=d.id;pointCount=0;$('startSurvey').disabled=true;$('stopSurvey').disabled=false;$('gnssMsg').textContent=`GNSS survey ${sessionId} active. Waiting for position…`;watchId=navigator.geolocation.watchPosition(savePoint,e=>$('gnssMsg').textContent=`GNSS error: ${e.message}`,{enableHighAccuracy:true,maximumAge:1000,timeout:15000});}
async function savePoint(pos){if(!sessionId)return;const c=pos.coords,p={latitude:c.latitude,longitude:c.longitude,altitude_m:c.altitude,accuracy_m:c.accuracy,speed_mps:c.speed,heading_deg:c.heading,captured_at:new Date(pos.timestamp).toISOString()};let r=await fetch(`/api/research/surveys/${sessionId}/points`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});let d={};try{d=await r.json()}catch(_){}if(r.ok){pointCount++;$('gnssMsg').textContent=`GNSS survey active: ${pointCount} valid on-corridor point(s) · ${c.latitude.toFixed(6)}, ${c.longitude.toFixed(6)} · accuracy ${c.accuracy?.toFixed(1)??'—'} m`;}else{const why=d.detail||'coordinate is not valid for the selected study corridor.';$('gnssMsg').textContent=`GNSS point rejected: ${why}`;if(r.status===422&&watchId!=null){navigator.geolocation.clearWatch(watchId);watchId=null;$('gnssMsg').textContent+=` Tracking paused. The browser reports the physical device position; ITICAS will never substitute the selected road coordinate for a field-GNSS observation.`;}}}
async function stopSurvey(){if(watchId!=null)navigator.geolocation.clearWatch(watchId);if(sessionId)await fetch(`/api/research/surveys/${sessionId}/stop`,{method:'POST'});$('gnssMsg').textContent=`GNSS survey complete: ${pointCount} point(s) stored.`;if($('toolGnssOutput'))$('toolGnssOutput').textContent=`${pointCount} GNSS point(s) stored in the completed survey.`;sessionId=null;watchId=null;$('startSurvey').disabled=false;$('stopSurvey').disabled=true;await refresh();}
$('evaluate').onclick=refresh;$('researchLoc').onchange=refresh;$('researchDays').onchange=refresh;$('makeProbes').onclick=probes;$('scanCorridor').onclick=scan;$('runAnalysis').onclick=analysis;$('startSurvey').onclick=startSurvey;$('stopSurvey').onclick=stopSurvey;$('viewMap').onclick=()=>location.href='/map';$('downloadResearch').onclick=()=>location.href=`/api/research/package/${id()}?days=${days()}`;load();
function toolDownload(tool){location.href=`/api/research/tool-output/${id()}/${tool}?days=${days()}`;}
document.addEventListener('DOMContentLoaded',()=>{
  const a=$('downloadRoadOutput'); if(a)a.onclick=()=>toolDownload('road');
  const b=$('downloadScanOutput'); if(b)b.onclick=()=>toolDownload('scan');
  const c=$('downloadGnssOutput'); if(c)c.onclick=()=>toolDownload('gnss');
  const d=$('downloadObjectiveOutput'); if(d)d.onclick=()=>toolDownload('objectives');
});
