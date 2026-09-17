from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from typing import Any

from sqlalchemy import select

from .database import SessionLocal, TrafficObservation


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "prediction").strip())
    return value.strip("_") or "prediction"


def _csv_bytes(headers: list[str], rows: list[list[Any]]) -> bytes:
    out = io.StringIO(newline="")
    w = csv.writer(out)
    w.writerow(headers)
    for row in rows:
        w.writerow(row)
    return out.getvalue().encode("utf-8-sig")


def _color(ci: float | None) -> str:
    if ci is None:
        return "#64748b"
    if ci < 0.10:
        return "#2dd4bf"
    if ci < 0.25:
        return "#facc15"
    if ci < 0.45:
        return "#fb923c"
    if ci < 0.65:
        return "#ef4444"
    return "#b91c1c"


def _svg_wrap(title: str, subtitle: str, body: str, width: int = 1400, height: int = 900) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#ffffff"/>
<style>text{{font-family:Arial,Helvetica,sans-serif;fill:#111827}} .muted{{fill:#526070}} .grid{{stroke:#dbe3ec;stroke-width:1}} .axis{{stroke:#64748b;stroke-width:1.2}}</style>
<text x="70" y="62" font-size="34" font-weight="700">{escape(title)}</text>
<text x="70" y="98" font-size="18" class="muted">{escape(subtitle)}</text>
{body}
<line x1="70" y1="840" x2="1330" y2="840" stroke="#9aa8b8"/>
<text x="70" y="875" font-size="15" class="muted">ITICAS predictive decision support · uncertainty and provenance should accompany operational use.</text>
</svg>'''


def _line_chart_svg(result: dict[str, Any], metric: str = "ci") -> str:
    rows = result.get("forecast") or []
    loc = result.get("location") or {}
    W, H = 1400, 900
    L, R, T, B = 105, 70, 160, 170
    PW, PH = W-L-R, H-T-B
    if metric == "speed":
        vals = [r.get("predicted_speed_kmh") for r in rows if r.get("predicted_speed_kmh") is not None]
        ymax = max(vals + [10.0]) * 1.15 if vals else 100
        ylabel, title = "Predicted speed (km/h)", f"PREDICTED SPEED PROFILE — {loc.get('name','Selected road')}"
        getter = lambda r: r.get("predicted_speed_kmh")
        subtitle = "Forecast road speed across the selected future period"
    else:
        ymax = max([float(r.get("ci_upper_90") or 0) for r in rows] + [0.5])
        ymax = min(1.0, max(0.5, ymax*1.15))
        ylabel, title = "Predicted congestion index", f"CONGESTION FORECAST + UNCERTAINTY — {loc.get('name','Selected road')}"
        getter = lambda r: r.get("predicted_congestion_index")
        subtitle = "Holdout-selected forecast with empirical residual uncertainty"
    def x(i): return L + (PW/2 if len(rows)<=1 else i*PW/(len(rows)-1))
    def y(v): return T+PH-(float(v or 0)/ymax)*PH
    body=[]
    for i in range(6):
        v=ymax*i/5; yy=T+PH-i*PH/5
        body.append(f'<line class="grid" x1="{L}" y1="{yy:.1f}" x2="{W-R}" y2="{yy:.1f}"/><text x="{L-15}" y="{yy+5:.1f}" text-anchor="end" font-size="14" class="muted">{v:.2f}</text>')
    body.append(f'<line class="axis" x1="{L}" y1="{T}" x2="{L}" y2="{T+PH}"/><line class="axis" x1="{L}" y1="{T+PH}" x2="{W-R}" y2="{T+PH}"/>')
    if metric == "ci" and rows:
        upper=' '.join(f'{x(i):.1f},{y(r.get("ci_upper_90")):.1f}' for i,r in enumerate(rows))
        lower=' '.join(f'{x(i):.1f},{y(rows[i].get("ci_lower_90")):.1f}' for i in range(len(rows)-1,-1,-1))
        body.append(f'<polygon points="{upper} {lower}" fill="#38bdf8" fill-opacity="0.16"/>')
    points=[]
    for i,r in enumerate(rows):
        v=getter(r)
        if v is None: continue
        points.append(f'{x(i):.1f},{y(v):.1f}')
    body.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="#0284c7" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>')
    if rows:
        for k in range(min(7,len(rows))):
            idx=round((len(rows)-1)*k/max(1,min(7,len(rows))-1)); dt=str(rows[idx].get('predicted_for_wat') or rows[idx].get('predicted_for') or '')
            lbl=dt[5:16].replace('T',' ')
            body.append(f'<text x="{x(idx):.1f}" y="{T+PH+34}" text-anchor="middle" font-size="13" class="muted">{escape(lbl)}</text>')
    body.append(f'<text x="{L+PW/2}" y="{H-112}" text-anchor="middle" font-size="17">Forecast time (WAT)</text>')
    body.append(f'<text x="28" y="{T+PH/2}" text-anchor="middle" font-size="17" transform="rotate(-90 28 {T+PH/2})">{escape(ylabel)}</text>')
    return _svg_wrap(title,subtitle,'\n'.join(body),W,H)


def _severity_svg(result: dict[str, Any]) -> str:
    rows=result.get('forecast') or []
    loc=result.get('location') or {}
    order=['Free flow','Light','Moderate','Heavy','Severe']
    counts=Counter(str(r.get('predicted_category') or 'Unknown') for r in rows)
    # map common labels case-insensitively
    normalized={k.lower():v for k,v in counts.items()}
    vals=[]
    for name in order:
        aliases=[name.lower()]
        if name=='Free flow': aliases+=['free','free/low']
        vals.append(sum(normalized.get(a,0) for a in aliases))
    mx=max(vals+[1]); W,H=1400,900; L,R,T,B=120,80,170,180; PW,PH=W-L-R,H-T-B; bw=PW/len(order)*.58
    body=[]
    for i in range(5):
        v=mx*i/4; yy=T+PH-i*PH/4;body.append(f'<line class="grid" x1="{L}" y1="{yy}" x2="{W-R}" y2="{yy}"/><text x="{L-14}" y="{yy+5}" text-anchor="end" font-size="14" class="muted">{int(v)}</text>')
    for i,(name,val) in enumerate(zip(order,vals)):
        cx=L+(i+.5)*PW/len(order); h=PH*val/mx; x=cx-bw/2; y=T+PH-h; ci=[.05,.17,.35,.55,.75][i]
        body.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{h}" fill="{_color(ci)}"/><text x="{cx}" y="{y-12}" text-anchor="middle" font-size="16" font-weight="700">{val}</text><text x="{cx}" y="{T+PH+34}" text-anchor="middle" font-size="15">{name}</text>')
    body.append(f'<text x="{L+PW/2}" y="{H-112}" text-anchor="middle" font-size="17">Predicted congestion severity class</text><text x="30" y="{T+PH/2}" text-anchor="middle" font-size="17" transform="rotate(-90 30 {T+PH/2})">Forecast intervals (count)</text>')
    return _svg_wrap(f"PREDICTED CONGESTION SEVERITY DISTRIBUTION — {loc.get('name','Selected road')}","Distribution across the requested forecast horizon",'\n'.join(body),W,H)


def _model_svg(result: dict[str, Any]) -> str:
    models=(result.get('validation') or {}).get('models') or []
    loc=result.get('location') or {}; W,H=1400,900; L,R,T,B=150,80,170,210; PW,PH=W-L-R,H-T-B
    mx=max([float(m.get('ci_mae') or 0) for m in models]+[0.1])*1.15
    body=[]
    for i in range(5):
        v=mx*i/4; yy=T+PH-i*PH/4;body.append(f'<line class="grid" x1="{L}" y1="{yy}" x2="{W-R}" y2="{yy}"/><text x="{L-14}" y="{yy+5}" text-anchor="end" font-size="14" class="muted">{v:.3f}</text>')
    n=max(1,len(models)); bw=PW/n*.52
    for i,m in enumerate(models):
        v=float(m.get('ci_mae') or 0); cx=L+(i+.5)*PW/n; h=PH*v/mx; y=T+PH-h; selected=m.get('model')==((result.get('model') or {}).get('selected'))
        body.append(f'<rect x="{cx-bw/2}" y="{y}" width="{bw}" height="{h}" fill="{"#06b6d4" if selected else "#94a3b8"}"/><text x="{cx}" y="{y-10}" text-anchor="middle" font-size="15" font-weight="700">{v:.4f}</text><text x="{cx}" y="{T+PH+38}" text-anchor="middle" font-size="14">{escape(str(m.get("model") or "").replace("_"," "))}</text>')
    body.append(f'<text x="{L+PW/2}" y="{H-120}" text-anchor="middle" font-size="17">Candidate prediction model</text><text x="32" y="{T+PH/2}" text-anchor="middle" font-size="17" transform="rotate(-90 32 {T+PH/2})">Holdout congestion-index MAE</text>')
    return _svg_wrap(f"PREDICTION MODEL VALIDATION — {loc.get('name','Selected road')}","Lower holdout error is better; selected model is highlighted",'\n'.join(body),W,H)


def _latest_segment_geometry(location_id: int) -> list[tuple[float,float]]:
    with SessionLocal() as db:
        row=db.scalar(select(TrafficObservation).where(TrafficObservation.location_id==location_id, TrafficObservation.segment_geometry_json.is_not(None)).order_by(TrafficObservation.observed_at.desc(), TrafficObservation.id.desc()))
    if not row or not row.segment_geometry_json:
        return []
    try: obj=json.loads(row.segment_geometry_json)
    except Exception: return []
    coords=obj.get('coordinates') or obj.get('coordinate') or [] if isinstance(obj,dict) else []
    out=[]
    for p in coords:
        if isinstance(p,(list,tuple)) and len(p)>=2:
            lon,lat=float(p[0]),float(p[1]);out.append((lat,lon))
        elif isinstance(p,dict) and p.get('latitude') is not None and p.get('longitude') is not None:
            out.append((float(p['latitude']),float(p['longitude'])))
    return out


def _map_svg(result: dict[str,Any]) -> str:
    loc=result.get('location') or {}; lid=int(loc.get('id') or 0); pts=_latest_segment_geometry(lid) if lid else []
    peak=result.get('peak_forecast') or {}; ci=float(peak.get('predicted_congestion_index') or 0)
    W,H=1400,900; L,R,T,B=100,80,170,170; PW,PH=W-L-R,H-T-B
    body=[]
    if pts:
        lats=[p[0] for p in pts];lons=[p[1] for p in pts]; mnlat,mxlat=min(lats),max(lats);mnlon,mxlon=min(lons),max(lons);dlat=max(mxlat-mnlat,1e-5);dlon=max(mxlon-mnlon,1e-5)
        pad=.08;mnlat-=dlat*pad;mxlat+=dlat*pad;mnlon-=dlon*pad;mxlon+=dlon*pad
        def xy(p):
            lat,lon=p; return L+(lon-mnlon)/(mxlon-mnlon)*PW, T+(mxlat-lat)/(mxlat-mnlat)*PH
        for i in range(6):
            xx=L+i*PW/5; yy=T+i*PH/5; body.append(f'<line class="grid" x1="{xx}" y1="{T}" x2="{xx}" y2="{T+PH}"/><line class="grid" x1="{L}" y1="{yy}" x2="{W-R}" y2="{yy}"/>')
        poly=' '.join(f'{xy(p)[0]:.1f},{xy(p)[1]:.1f}' for p in pts);body.append(f'<polyline points="{poly}" fill="none" stroke="#ffffff" stroke-width="12"/><polyline points="{poly}" fill="none" stroke="{_color(ci)}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>')
        mid=pts[len(pts)//2];x,y=xy(mid);body.append(f'<circle cx="{x}" cy="{y}" r="9" fill="#06b6d4" stroke="#ffffff" stroke-width="3"/><text x="{x+15}" y="{y+5}" font-size="18" font-weight="700">{escape(loc.get("name") or "Selected road")}</text>')
        body.append(f'<text x="{L+PW/2}" y="{H-112}" text-anchor="middle" font-size="17">Longitude</text><text x="28" y="{T+PH/2}" text-anchor="middle" font-size="17" transform="rotate(-90 28 {T+PH/2})">Latitude</text>')
    else:
        body.append(f'<rect x="{L}" y="{T}" width="{PW}" height="{PH}" fill="#f4f7fa" stroke="#cbd5e1"/><text x="{L+PW/2}" y="{T+PH/2-15}" text-anchor="middle" font-size="24" font-weight="700">{escape(loc.get("name") or "Selected road")}</text><text x="{L+PW/2}" y="{T+PH/2+22}" text-anchor="middle" font-size="17" class="muted">No recent provider segment geometry was stored; map does not invent road geometry.</text>')
    body.append(f'<rect x="1020" y="185" width="280" height="125" fill="#ffffff" stroke="#94a3b8"/><text x="1040" y="218" font-size="17" font-weight="700">Forecast road context</text><text x="1040" y="248" font-size="15">Peak predicted CI: {ci:.3f}</text><text x="1040" y="276" font-size="15">Peak class: {escape(str(peak.get("predicted_category") or "—"))}</text>')
    return _svg_wrap(f"FORECAST ROAD DECISION MAP — {loc.get('name','Selected road')}",f"{loc.get('city') or ''}, {loc.get('state') or ''}, Nigeria · segment coloured by peak forecast severity",'\n'.join(body),W,H)


def _decision_metrics(result: dict[str,Any]) -> dict[str,Any]:
    rows=result.get('forecast') or []
    cis=[float(r.get('predicted_congestion_index') or 0) for r in rows]
    speeds=[float(r['predicted_speed_kmh']) for r in rows if r.get('predicted_speed_kmh') is not None]
    if not rows:
        return {}
    moderate=sum(v>=.25 for v in cis)/len(cis)*100
    heavy=sum(v>=.45 for v in cis)/len(cis)*100
    uncertainty=[float(r.get('ci_upper_90') or 0)-float(r.get('ci_lower_90') or 0) for r in rows]
    peak=max(rows,key=lambda r:float(r.get('predicted_congestion_index') or 0))
    return {
        'mean_predicted_ci':round(sum(cis)/len(cis),4),'peak_predicted_ci':round(max(cis),4),'peak_time_wat':peak.get('predicted_for_wat'),
        'minimum_predicted_speed_kmh':round(min(speeds),2) if speeds else None,'moderate_or_worse_share_pct':round(moderate,2),
        'heavy_or_worse_share_pct':round(heavy,2),'mean_uncertainty_width_ci':round(sum(uncertainty)/len(uncertainty),4),
        'forecast_intervals':len(rows)
    }


def _recommendations(result: dict[str,Any], metrics: dict[str,Any]) -> list[str]:
    peak=float(metrics.get('peak_predicted_ci') or 0); moderate=float(metrics.get('moderate_or_worse_share_pct') or 0)
    out=[]
    if peak>=.65: out.append('Severe congestion is forecast: prepare active traffic management, incident response and route-diversion messaging for the peak window.')
    elif peak>=.45: out.append('Heavy congestion is forecast: consider targeted junction control, enforcement and traveller-information measures during the peak window.')
    elif peak>=.25: out.append('Moderate congestion is forecast: maintain monitoring and prepare targeted operational measures around the predicted peak.')
    else: out.append('Forecast conditions are predominantly free/light; maintain monitoring and use the period as a baseline for deterioration detection.')
    if moderate>=25: out.append('A material share of forecast intervals is moderate-or-worse; prioritize peak-window surveillance rather than relying on all-day averages.')
    validation=result.get('validation') or {}
    if validation.get('ci_mae') is not None: out.append(f"Interpret decisions alongside holdout CI MAE {float(validation['ci_mae']):.4f} and the displayed 90% uncertainty envelope.")
    out.append('Re-run the forecast when incidents, road works, major events or weather conditions materially change.')
    return out


def _context_svg(result: dict[str, Any]) -> str:
    c=result.get("external_context") or {}; w=c.get("weather_summary") or {}; inc=c.get("incidents") or {}; pr=c.get("corridor_probes") or {}; dt=c.get("day_type") or {}; loc=result.get("location") or {}
    items=[
        ("Forecast weather hours", w.get("forecast_hours")),
        ("Rain forecast hours", w.get("rain_hours")),
        ("Max hourly precipitation (mm)", w.get("maximum_hourly_precipitation_mm")),
        ("Active incidents", inc.get("active_count")),
        ("Recent corridor probes", pr.get("probes_with_recent_data")),
        ("Probe moderate+ share (%)", pr.get("moderate_or_worse_probe_share_pct")),
        ("Weekday days", dt.get("weekday_days")),
        ("Weekend days", dt.get("weekend_days")),
    ]
    body=[]; x0,y0=110,180
    for i,(label,val) in enumerate(items):
        col=i%2; row=i//2; x=x0+col*610; y=y0+row*125
        body.append(f'<rect x="{x}" y="{y}" width="540" height="92" rx="12" fill="#f4f7fa" stroke="#cbd5e1"/><text x="{x+22}" y="{y+32}" font-size="15" class="muted">{escape(label)}</text><text x="{x+22}" y="{y+67}" font-size="26" font-weight="700">{escape(str(val if val is not None else "—"))}</text>')
    body.append('<text x="110" y="730" font-size="16" class="muted">Context is advisory unless a road-specific effect is empirically calibrated and validated.</text>')
    return _svg_wrap(f"PREDICTION CONTEXT DASHBOARD — {loc.get('name','Selected road')}", "Weather, incidents, corridor probes and day-type context", '\n'.join(body), 1400, 900)


def _context_rows(result: dict[str, Any]) -> list[list[Any]]:
    c=result.get("external_context") or {}; out=[]
    for section in ("weather_summary","incidents","corridor_probes","day_type"):
        obj=c.get(section) or {}
        for k,v in obj.items():
            if isinstance(v,(str,int,float,bool)) or v is None: out.append([section,k,v])
    return out


def _explainability_rows(result: dict[str, Any]) -> list[list[Any]]:
    e=((result.get("model") or {}).get("explainability") or {}); out=[]
    for k,v in e.items():
        if isinstance(v,dict):
            for sk,sv in v.items(): out.append([k,sk,sv])
        elif not isinstance(v,(list,tuple)): out.append([k,"",v])
    return out



def _calibration_rows(result: dict[str, Any]) -> list[list[Any]]:
    c=result.get("context_calibration") or {}; out=[]
    for section in ("rain","incident"):
        obj=c.get(section) or {}
        for k,v in obj.items():
            if isinstance(v,(str,int,float,bool)) or v is None: out.append([section,k,v])
    return out

def _verification_rows(result: dict[str, Any]) -> list[list[Any]]:
    v=result.get("post_forecast_monitoring") or {}; out=[]
    for k,val in v.items():
        if k == "recent_matches": continue
        if isinstance(val,(str,int,float,bool)) or val is None: out.append([k,val])
    return out

def _scenario_rows(result: dict[str, Any]) -> list[list[Any]]:
    s=result.get("scenario_comparison") or {}
    return [[k,v] for k,v in s.items() if isinstance(v,(str,int,float,bool)) or v is None]

def _verification_svg(result: dict[str,Any]) -> str:
    v=result.get("post_forecast_monitoring") or {}; rows=v.get("recent_matches") or []; loc=result.get("location") or {}
    if not rows:
        return _svg_wrap(f"POST-FORECAST VERIFICATION — {loc.get('name','Selected road')}","No realized prediction/observation matches are available yet.",'<text x="110" y="220" font-size="20" class="muted">Awaiting matching observed traffic after forecast times.</text>',1400,700)
    W,H=1400,760; left,right,top,bottom=120,70,170,120; pw=W-left-right; ph=H-top-bottom
    vals=[float(x.get("observed_ci") or 0) for x in rows]+[float(x.get("predicted_ci") or 0) for x in rows]; ymax=max(.25,max(vals)+.08)
    def xy(i,y): return left+(pw*i/max(1,len(rows)-1)), top+ph-(float(y)/ymax)*ph
    pred=' '.join(f'{xy(i,r.get("predicted_ci") or 0)[0]:.1f},{xy(i,r.get("predicted_ci") or 0)[1]:.1f}' for i,r in enumerate(rows))
    obs=' '.join(f'{xy(i,r.get("observed_ci") or 0)[0]:.1f},{xy(i,r.get("observed_ci") or 0)[1]:.1f}' for i,r in enumerate(rows))
    body=[f'<line x1="{left}" y1="{top+ph}" x2="{W-right}" y2="{top+ph}" stroke="#94a3b8"/><line x1="{left}" y1="{top}" x2="{left}" y2="{top+ph}" stroke="#94a3b8"/>',f'<polyline points="{pred}" fill="none" stroke="#0284c7" stroke-width="4"/>',f'<polyline points="{obs}" fill="none" stroke="#16a34a" stroke-width="4"/>',f'<text x="{left+pw/2}" y="{H-42}" text-anchor="middle" font-size="18">Matched prediction sequence</text>',f'<text x="34" y="{top+ph/2}" transform="rotate(-90 34 {top+ph/2})" text-anchor="middle" font-size="18">Congestion index</text>',f'<text x="{left}" y="{top-35}" font-size="15" fill="#0284c7">Predicted</text><text x="{left+120}" y="{top-35}" font-size="15" fill="#16a34a">Observed</text>']
    return _svg_wrap(f"POST-FORECAST VERIFICATION — {loc.get('name','Selected road')}",f"Realized CI MAE {v.get('ci_mae','—')} · drift status {v.get('drift_status','—')}",'\n'.join(body),W,H)

def _daily_forecast_svg(day: dict[str,Any], location_name: str) -> str:
    rows=day.get("intervals") or []; W,H=1400,760;L,R,T,B=105,60,150,125;PW=W-L-R;PH=H-T-B
    def x(i):return L+(PW/2 if len(rows)<=1 else i*PW/(len(rows)-1))
    def y(v):return T+PH-(max(0,min(1,float(v or 0)))*PH)
    body=[]
    for i in range(5):
        val=1-i/4;yy=T+PH*i/4;body.append(f'<line class="grid" x1="{L}" y1="{yy}" x2="{W-R}" y2="{yy}"/><text x="{L-12}" y="{yy+5}" text-anchor="end" font-size="13" class="muted">{val:.2f}</text>')
    pts=' '.join(f'{x(i):.1f},{y(r.get("predicted_congestion_index")):.1f}' for i,r in enumerate(rows));body.append(f'<polyline points="{pts}" fill="none" stroke="#0284c7" stroke-width="4"/>')
    tick_every=max(1,len(rows)//10)
    for i,r in enumerate(rows):
        if i%tick_every==0 or i==len(rows)-1:
            try:dt=datetime.fromisoformat(str(r.get("predicted_for_wat") or r.get("predicted_for")));lab=dt.strftime("%H:%M")
            except Exception:lab=str(r.get("predicted_for_wat") or '')[-14:-9]
            body.append(f'<text x="{x(i):.1f}" y="{T+PH+30}" text-anchor="middle" font-size="12" class="muted">{escape(lab)}</text>')
    peak=day.get("peak_time")
    if peak:
        try:
            idx=min(range(len(rows)),key=lambda i:abs(datetime.fromisoformat(str(rows[i].get("predicted_for"))).timestamp()-datetime.fromisoformat(str(peak)).timestamp()));px=x(idx);body.append(f'<line x1="{px:.1f}" y1="{T}" x2="{px:.1f}" y2="{T+PH}" stroke="#e11d48" stroke-width="2" stroke-dasharray="6 4"/><text x="{min(px+8,W-260):.1f}" y="{T+18}" fill="#be123c" font-size="14">Peak {escape(str(rows[idx].get("predicted_for_wat") or peak))}</text>')
        except Exception:pass
    body.append(f'<text x="{L+PW/2}" y="{H-42}" text-anchor="middle" font-size="17">Forecast time — West Africa Time</text>')
    return _svg_wrap(f"DAILY TRAFFIC FORECAST — {location_name} — {day.get('date')}","Daily intervals first; composite horizon follows after all daily outputs",'\n'.join(body),W,H)

def prediction_decision_package(result: dict[str,Any]) -> tuple[str,bytes,str]:
    loc=result.get('location') or {}; rows=result.get('forecast') or []
    if not rows:
        raise ValueError('A completed forecast with prediction records is required before exporting the decision package.')
    metrics=_decision_metrics(result); recs=_recommendations(result,metrics)
    basename=f"ITICAS_prediction_{_slug(str(loc.get('name') or 'road'))}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('00_prediction_result.json',json.dumps(result,indent=2,default=str))
        z.writestr('tables/01_forecast_records.csv',_csv_bytes(
            ['predicted_for_wat','predicted_speed_kmh','predicted_free_flow_speed_kmh','predicted_congestion_index','ci_lower_90','ci_upper_90','predicted_category'],
            [[r.get('predicted_for_wat'),r.get('predicted_speed_kmh'),r.get('predicted_free_flow_speed_kmh'),r.get('predicted_congestion_index'),r.get('ci_lower_90'),r.get('ci_upper_90'),r.get('predicted_category')] for r in rows]))
        models=(result.get('validation') or {}).get('models') or []
        z.writestr('tables/02_model_validation.csv',_csv_bytes(['model','ci_mae','ci_rmse','speed_mae_kmh','validation_points'],[[m.get('model'),m.get('ci_mae'),m.get('ci_rmse'),m.get('speed_mae_kmh'),m.get('validation_points')] for m in models]))
        z.writestr('tables/03_decision_metrics.csv',_csv_bytes(['metric','value'],[[k,v] for k,v in metrics.items()]))
        top=sorted(rows,key=lambda r:float(r.get('predicted_congestion_index') or 0),reverse=True)[:10]
        z.writestr('tables/04_peak_windows.csv',_csv_bytes(['rank','predicted_for_wat','predicted_ci','speed_kmh','class'],[[i+1,r.get('predicted_for_wat'),r.get('predicted_congestion_index'),r.get('predicted_speed_kmh'),r.get('predicted_category')] for i,r in enumerate(top)]))
        z.writestr('tables/05_external_context.csv',_csv_bytes(['section','metric','value'],_context_rows(result)))
        z.writestr('tables/06_model_explainability.csv',_csv_bytes(['component','subcomponent','value'],_explainability_rows(result)))
        weights=((result.get('model') or {}).get('ensemble_weights') or {})
        z.writestr('tables/07_ensemble_weights.csv',_csv_bytes(['model','weight'],[[k,v] for k,v in weights.items()]))
        z.writestr('tables/08_context_calibration.csv',_csv_bytes(['effect','metric','value'],_calibration_rows(result)))
        z.writestr('tables/09_post_forecast_verification.csv',_csv_bytes(['metric','value'],_verification_rows(result)))
        z.writestr('tables/10_scenario_comparison.csv',_csv_bytes(['metric','value'],_scenario_rows(result)))
        for day in result.get('daily_forecast') or []:
            ds=str(day.get('date')); intervals=day.get('intervals') or []
            z.writestr(f'01_DAILY_FORECAST/{ds}/hourly_or_interval_forecast.csv',_csv_bytes(['predicted_for_wat','predicted_speed_kmh','predicted_free_flow_speed_kmh','predicted_congestion_index','ci_lower_90','ci_upper_90','predicted_category','weather_condition','precipitation_mm','cause'],[[r.get('predicted_for_wat'),r.get('predicted_speed_kmh'),r.get('predicted_free_flow_speed_kmh'),r.get('predicted_congestion_index'),r.get('ci_lower_90'),r.get('ci_upper_90'),r.get('predicted_category'),(r.get('weather_context') or {}).get('condition'),(r.get('weather_context') or {}).get('precipitation_mm'),(r.get('cause_assessment') or {}).get('cause')] for r in intervals]))
            z.writestr(f'01_DAILY_FORECAST/{ds}/daily_congestion_timeline.svg',_daily_forecast_svg(day,str(loc.get('name') or 'Selected road')))
        z.writestr('02_COMPOSITE_FORECAST/figures/01_congestion_forecast_uncertainty.svg',_line_chart_svg(result,'ci'))
        z.writestr('02_COMPOSITE_FORECAST/figures/02_speed_forecast.svg',_line_chart_svg(result,'speed'))
        z.writestr('02_COMPOSITE_FORECAST/figures/03_severity_distribution.svg',_severity_svg(result))
        z.writestr('02_COMPOSITE_FORECAST/figures/04_model_validation.svg',_model_svg(result))
        z.writestr('02_COMPOSITE_FORECAST/figures/05_prediction_context_dashboard.svg',_context_svg(result))
        z.writestr('02_COMPOSITE_FORECAST/figures/06_post_forecast_verification.svg',_verification_svg(result))
        z.writestr('02_COMPOSITE_FORECAST/maps/01_forecast_road_decision_map.svg',_map_svg(result))
        brief=''.join(f'<li>{escape(x)}</li>' for x in recs)
        metrics_html=''.join(f'<tr><td>{escape(k.replace("_"," ").title())}</td><td>{escape(str(v))}</td></tr>' for k,v in metrics.items())
        html=f'''<!doctype html><html><head><meta charset="utf-8"><title>ITICAS Prediction Decision Brief</title><style>body{{font-family:Arial,sans-serif;max-width:1000px;margin:40px auto;color:#172033;line-height:1.5}}h1{{font-size:30px}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #ccd5df;padding:9px;text-align:left}}.note{{background:#eef6fb;padding:14px;border-left:4px solid #0284c7}}</style></head><body><h1>ITICAS Prediction Decision Brief — {escape(str(loc.get('name') or 'Selected road'))}</h1><p>{escape(str(loc.get('city') or ''))}, {escape(str(loc.get('state') or ''))}, Nigeria</p><div class="note">Selected model: <b>{escape(str((result.get('model') or {}).get('selected') or '—'))}</b> · Evidence grade: <b>{escape(str((result.get('readiness') or {}).get('grade') or '—'))}</b></div><h2>Decision metrics</h2><table>{metrics_html}</table><h2>Decision signals</h2><ul>{brief}</ul><h2>External context</h2><p>Weather, incident, corridor-probe and day-type context is included in the package. ITICAS keeps this context separate from the validated traffic-history forecast mean unless a road-specific effect has been empirically calibrated.</p><h2>Scientific limitations</h2><ul>{''.join(f'<li>{escape(str(x))}</li>' for x in result.get('limitations') or [])}</ul><p><b>Developed by Dr. Oyeyode A.O. MNIS, MGEOSON, MNAG</b></p></body></html>'''
        z.writestr('02_COMPOSITE_FORECAST/reports/01_prediction_decision_brief.html',html)
        z.writestr('README.txt',"ITICAS prediction decision package\n\nContains forecast tables, model validation, decision metrics, peak windows, external-context tables, model explainability, ensemble weights, road-specific context calibration, post-forecast verification/drift monitoring, scenario comparison, forecast graphs, a context dashboard, a verification graph, a road decision map and an executive decision brief. Forecasts are model outputs, not observed traffic. Use uncertainty, validation error and provenance when making decisions.\n")
    return basename+'.zip',out.getvalue(),'application/zip'
