from __future__ import annotations
from io import BytesIO, StringIO
from csv import writer
from datetime import datetime, timezone
from html import escape
from zipfile import ZipFile, ZIP_DEFLATED
import json, math, urllib.request, urllib.parse, os

from PIL import Image, ImageDraw, ImageFont
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from docx import Document
from docx.shared import Inches
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

from .analytics import analyze_location
from .config import settings

TRAFFIC_SEVERITY_COLORS={
 'free':'#2dd4bf','light':'#facc15','moderate':'#fb923c','heavy':'#ef4444','severe':'#b91c1c','blocked':'#7e22ce','unknown':'#64748b'
}

from .database import SessionLocal, TrafficObservation, MonitoringLocation, CorridorProbe, CorridorProbeObservation
from .spatial_intelligence import spatial_summary, haversine_km
from .static_map import render_static_map
from sqlalchemy import select

FORMATS = {"csv","xlsx","docx","pdf","svg","png","json","zip","maps"}

def _filename(a, ext):
    name='-'.join((a['location']['name'] or 'location').lower().replace('/',' ').split())
    return f"ITICAS_{name}_{a['period']['days']}d.{ext}"

def _metadata_rows(a):
    s=a['summary']; q=a['data_quality']; v=a['validation']; loc=a['location']; c=a.get('coverage',{}); rid=a.get('report_identity',{})
    return [
        ("Application", settings.app_name),("Developer", settings.developer_credit),("Scope", "Nigeria"),
        ("Report ID", rid.get('report_id')),("Dataset signature", rid.get('dataset_signature')),("Data origin", q.get('data_origin','observed')),
        ("Location", loc['name']),("Road", loc.get('road_name') or ''),("City", loc.get('city') or ''),("State", loc.get('state') or ''),
        ("Requested period days", a['period']['days']),("Requested from UTC", a['period']['requested_from_utc']),("Requested to UTC", a['period']['requested_to_utc']),
        ("Analysis timezone", a['period'].get('timezone','Africa/Lagos')),("First stored observation UTC", c.get('first_observation_utc')),("Last stored observation UTC", c.get('last_observation_utc')),
        ("Actual observation span hours", c.get('actual_observation_span_hours')),("Observations", q['observations']),("Observations in last 24h", c.get('observations_last_24h')),
        ("Observations older than 24h in selected window", c.get('observations_older_than_24h_in_selected_window')),("Same dataset as last 24h", c.get('same_dataset_as_last_24h')),
        ("Live hourly buckets with data", c.get('hour_buckets_with_data')),("Historical-provider hourly buckets", c.get('historical_provider_hour_buckets')),("Combined hourly buckets with data", c.get('combined_hour_buckets_with_data')),
        ("Hourly buckets requested", c.get('hour_buckets_total')),("Live hourly coverage %", c.get('hourly_coverage_pct')),("Combined hourly coverage %", c.get('combined_hourly_coverage_pct')),("Sample coverage %", c.get('sample_coverage_pct')),
        ("Data sufficiency", q['sufficiency']),("Provider sources", ', '.join(q['provider_sources'])),
        ("Validation status", v['status']),("Independent traffic benchmark", v['independent_traffic_benchmark']),
        ("Mean speed km/h", s['mean_speed_kmh']),("Mean free-flow speed km/h", s['mean_free_flow_speed_kmh']),
        ("Mean congestion index", s['mean_congestion_index']),("Max congestion index", s['max_congestion_index']),
        ("Mean delay seconds", s['mean_delay_seconds']),("Mean speed reduction %", s['mean_speed_reduction_pct']),
        ("Speed variability km/h", s['speed_std_kmh']),
        ("Travel Time Index (TTI)", s.get('travel_time_index')),
        ("Planning Time Index (PTI)", s.get('planning_time_index')),
        ("Buffer Index %", s.get('buffer_index_pct')),
        ("95th percentile travel time (s)", s.get('p95_travel_time_seconds')),
        ("Moderate-or-worse share %", s.get('moderate_plus_share_pct')),
        ("Heavy-or-worse share %", s.get('heavy_plus_share_pct')),
        ("Severe congestion share %", s.get('severe_share_pct')),
        ("Road closure share %", s.get('road_closure_share_pct')),
        ("Mean provider confidence", s.get('mean_provider_confidence')),
        ("ITICAS Decision Priority Score", s.get('iticas_decision_priority_score')),
        ("ITICAS Decision Priority Class", s.get('iticas_decision_priority_class')),
        ("Limitations", ' | '.join(a.get('limitations') or [])),
    ]

def build_csv(a):
    out=StringIO(newline=''); w=writer(out); w.writerow(['ITICAS Traffic Analytics Export']); w.writerows(_metadata_rows(a)); w.writerow([])
    w.writerow(['DAILY-FIRST ANALYSIS — each day is analysed on a fixed 24-hour WAT grid before composite statistics'])
    for d in a.get('day_by_day',[]):
        w.writerow([]); w.writerow(['Date',d.get('date'),'Hours with evidence',d.get('hours_with_evidence'),'Coverage %',d.get('coverage_pct'),'Peak hour',d.get('peak_hour'),'Peak CI',d.get('peak_congestion_index')])
        w.writerow(['Hour WAT','Samples','Data status','Source','Mean speed km/h','Mean free-flow/reference km/h','Mean congestion index','Mean delay seconds'])
        for h,r in enumerate(d.get('hourly') or []): w.writerow([f'{h:02d}:00-{(h+1)%24:02d}:00',r['samples'],r['data_status'],r.get('source'),r['mean_speed_kmh'],r['mean_free_flow_speed_kmh'],r['mean_congestion_index'],r['mean_delay_seconds']])
    w.writerow([]); w.writerow(['COMPOSITE SELECTED-PERIOD HOURLY TIME SERIES — daily results above take precedence for day-specific interpretation']); w.writerow(['Hour start (Africa/Lagos)','Samples','Data status','Source','Mean speed km/h','Mean free-flow/reference km/h','Mean congestion index','Mean delay seconds'])
    for r in a['hourly_timeseries']: w.writerow([r['hour_start'],r['samples'],r['data_status'],r.get('source'),r['mean_speed_kmh'],r['mean_free_flow_speed_kmh'],r['mean_congestion_index'],r['mean_delay_seconds']])
    w.writerow([]); w.writerow(['Raw observed traffic']); w.writerow(['Observed UTC','Observed Nigeria','Current speed km/h','Free-flow km/h','Congestion index','Delay seconds','Confidence','Provider'])
    for r in a['raw_observations']: w.writerow([r['observed_at_utc'],r['observed_at_nigeria'],r['current_speed_kmh'],r['free_flow_speed_kmh'],r['congestion_index'],r['delay_seconds'],r['confidence'],r['provider']])
    return out.getvalue().encode('utf-8-sig')

def build_xlsx(a):
    wb=Workbook(); ws=wb.active; ws.title='Summary'; ws.append(['ITICAS Traffic Analytics Export']); ws['A1'].font=Font(bold=True,size=16)
    for k,v in _metadata_rows(a): ws.append([k,v])
    ws.column_dimensions['A'].width=42; ws.column_dimensions['B'].width=78
    ts=wb.create_sheet('Hourly Time Series'); ts.append(['Hour start (Africa/Lagos)','Samples','Data status','Source','Mean speed km/h','Mean free-flow/reference km/h','Mean congestion index','Mean delay seconds'])
    for r in a['hourly_timeseries']: ts.append([r['hour_start'],r['samples'],r['data_status'],r.get('source'),r['mean_speed_kmh'],r['mean_free_flow_speed_kmh'],r['mean_congestion_index'],r['mean_delay_seconds']])
    day_index=wb.create_sheet('Daily First Index'); day_index.append(['Date','Hours With Evidence','Coverage %','Mean CI','Max CI','Mean Speed','Mean Delay','Peak Time','Peak CI','Peak Category'])
    for d in a.get('day_by_day',[]):
        day_index.append([d.get('date'),d.get('hours_with_evidence'),d.get('coverage_pct'),d.get('mean_congestion_index'),d.get('max_congestion_index'),d.get('mean_speed_kmh'),d.get('mean_delay_seconds'),d.get('peak_hour'),d.get('peak_congestion_index'),d.get('peak_category')])
        ds=wb.create_sheet(('D '+str(d.get('date')))[:31]); ds.append(['Hour WAT','Samples','Status','Source','Mean Speed km/h','Free-flow km/h','CI','Delay s'])
        for h,r in enumerate(d.get('hourly') or []): ds.append([f'{h:02d}:00-{(h+1)%24:02d}:00',r.get('samples'),r.get('data_status'),r.get('source'),r.get('mean_speed_kmh'),r.get('mean_free_flow_speed_kmh'),r.get('mean_congestion_index'),r.get('mean_delay_seconds')])
    raw=wb.create_sheet('Raw Observations'); raw.append(['Observed UTC','Observed Nigeria','Current speed km/h','Free-flow km/h','Congestion index','Delay seconds','Confidence','Road closed','Provider','Source timestamp'])
    for r in a['raw_observations']: raw.append([r['observed_at_utc'],r['observed_at_nigeria'],r['current_speed_kmh'],r['free_flow_speed_kmh'],r['congestion_index'],r['delay_seconds'],r['confidence'],r['road_closed'],r['provider'],r['source_timestamp']])
    hp=wb.create_sheet('Clock Hour Profile'); hp.append(['Clock hour','Mean congestion index','Samples'])
    for r in a['hourly_profile']: hp.append([r['hour'],r['mean_congestion_index'],r['samples']])
    dp=wb.create_sheet('Daily Profile'); dp.append(['Date','Mean congestion index','Samples'])
    for r in a['daily_profile']: dp.append([r['date'],r['mean_congestion_index'],r['samples']])
    wp=wb.create_sheet('Weekday Profile'); wp.append(['Day','Mean congestion index','Samples'])
    for r in a['weekday_profile']: wp.append([r['day'],r['mean_congestion_index'],r['samples']])
    cat=wb.create_sheet('Congestion Classes'); cat.append(['Class','Count'])
    for k,v in a['categories'].items(): cat.append([k,v])
    prov=wb.create_sheet('Provenance'); prov.append(['Validation statement',a['validation']['statement']]); prov.append(['Independent benchmark',a['validation']['independent_traffic_benchmark']]); prov.append(['Dataset signature',a['report_identity']['dataset_signature']]); prov.append(['Generated UTC',datetime.now(timezone.utc).isoformat()])
    dm=wb.create_sheet('Decision Metrics'); dm.append(['Metric','Value','Interpretation']); sm=a['summary']; dm.append(['Travel Time Index',sm.get('travel_time_index'),'Ratio of observed travel time to free-flow travel time; >1 indicates delay.']); dm.append(['Planning Time Index',sm.get('planning_time_index'),'95th percentile travel time divided by free-flow travel time; higher values mean less reliable travel.']); dm.append(['Buffer Index %',sm.get('buffer_index_pct'),'Extra time a traveller should budget above the mean to be on time about 95% of the time.']); dm.append(['Heavy-or-worse share %',sm.get('heavy_plus_share_pct'),'Share of valid observations with congestion index >=0.50.']); dm.append(['ITICAS Decision Priority Score',sm.get('iticas_decision_priority_score'),'Experimental transparent research score combining severity, persistence, delay, variability and coverage; not an external standard.']); dm.append(['Decision Priority Class',sm.get('iticas_decision_priority_class'),'Screening class for intervention prioritisation.'])
    bio=BytesIO(); wb.save(bio); return bio.getvalue()

def build_svg(a):
    rows=a['hourly_profile']; width,height=1100,620; left,bottom,top=90,520,70; chart_h=bottom-top; chart_w=width-left-50
    vals=[r['mean_congestion_index'] for r in rows] or [0]; vmax=max(max(vals),0.1)
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="white"/>',f'<text x="{left}" y="35" font-family="Arial" font-size="22" font-weight="bold">ITICAS Hourly Congestion Profile</text>',
           f'<text x="{left}" y="58" font-family="Arial" font-size="13">{escape(a["location"]["name"])} · {a["period"]["days"]} days · validation: provider reference</text>',
           f'<line x1="{left}" y1="{bottom}" x2="{width-50}" y2="{bottom}" stroke="#334155"/><line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#334155"/>']
    if rows:
        step=chart_w/max(24,len(rows)); bw=max(8,step*0.62)
        for i,r in enumerate(rows):
            x=left+i*step+step*0.18; bh=(r['mean_congestion_index']/vmax)*chart_h; y=bottom-bh
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" fill="#20c997"/>')
            parts.append(f'<text x="{x+bw/2:.1f}" y="{bottom+18}" text-anchor="middle" font-family="Arial" font-size="10">{r["hour"]:02d}</text>')
    else: parts.append(f'<text x="{left+50}" y="{top+100}" font-family="Arial" font-size="18">No hourly profile available.</text>')
    parts.append(f'<text x="{left}" y="590" font-family="Arial" font-size="11">{escape(settings.developer_credit)} · Generated {datetime.now(timezone.utc).isoformat()}</text></svg>')
    return ''.join(parts).encode('utf-8')

def _pil_font(size=28,bold=False):
    candidates=[]
    if bold:
        candidates += [r"C:\Windows\Fonts\arialbd.ttf",r"C:\Windows\Fonts\calibrib.ttf"]
    else:
        candidates += [r"C:\Windows\Fonts\arial.ttf",r"C:\Windows\Fonts\calibri.ttf"]
    candidates += ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for name in candidates:
        try:return ImageFont.truetype(name,size)
        except Exception:pass
    return ImageFont.load_default()

def build_png(a):
    W,H=1800,1100
    img=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(img)
    title=_pil_font(44,True); sub=_pil_font(24); axis=_pil_font(20); small=_pil_font(17); note=_pil_font(16)
    loc=a['location']; sm=a['summary']; cov=a['coverage']
    d.text((110,55),'ITICAS HOURLY CONGESTION PROFILE',fill=(15,23,42),font=title)
    d.text((110,118),f"{loc['name']} — {loc.get('city') or ''}, {loc.get('state') or ''} | Last {a['period']['days']} day(s)",fill=(51,65,85),font=sub)
    d.text((110,158),f"Observed hours: {cov.get('hour_buckets_with_data',0)} | Historical-provider hours: {cov.get('historical_provider_hour_buckets',0)} | Combined coverage: {cov.get('combined_hourly_coverage_pct',0)}%",fill=(71,85,105),font=small)
    left,top,right,bottom=170,255,1680,870
    # grid and y labels from 0 to 1
    for i in range(6):
        y=bottom-(bottom-top)*i/5
        d.line((left,y,right,y),fill=(220,226,234),width=2)
        d.text((95,y-12),f"{i/5:.1f}",fill=(71,85,105),font=axis)
    d.line((left,top,left,bottom),fill=(30,41,59),width=3);d.line((left,bottom,right,bottom),fill=(30,41,59),width=3)
    rows={r['hour']:r for r in a['hourly_profile']}; step=(right-left)/24
    for h in range(24):
        r=rows.get(h); x=left+h*step+6; x2=left+(h+1)*step-6
        if r:
            ci=max(0,min(1,float(r['mean_congestion_index']))); y=bottom-ci*(bottom-top)
            if ci>=.7: color=(190,30,45)
            elif ci>=.5: color=(230,108,35)
            elif ci>=.35: color=(235,179,45)
            elif ci>=.2: color=(84,165,98)
            else: color=(54,134,220)
            d.rectangle((x,y,x2,bottom),fill=color)
            d.text((x,y-28),f"{ci:.2f}",fill=(35,45,58),font=small)
        if h%2==0:d.text((x,bottom+16),f"{h:02d}:00",fill=(71,85,105),font=small)
    d.text((20,(top+bottom)/2-80),'Mean congestion index',fill=(30,41,59),font=axis)
    d.text((760,925),'Hour of day — West Africa Time (UTC+1)',fill=(30,41,59),font=axis)
    # legend
    legend=[('Free flow <0.20',(54,134,220)),('Light 0.20–0.35',(84,165,98)),('Moderate 0.35–0.50',(235,179,45)),('Heavy 0.50–0.70',(230,108,35)),('Severe ≥0.70',(190,30,45))]
    lx=180;ly=985
    for label,c in legend:
        d.rectangle((lx,ly,lx+24,ly+24),fill=c);d.text((lx+34,ly-2),label,fill=(45,55,72),font=small);lx+=290
    d.text((110,1040),f"Validation: {a['validation']['status']} | Independent traffic benchmark: {a['validation']['independent_traffic_benchmark']} | Report ID: {a['report_identity']['report_id']}",fill=(60,72,90),font=note)
    d.text((110,1070),settings.developer_credit,fill=(25,95,65),font=note)
    bio=BytesIO();img.save(bio,format='PNG',dpi=(300,300));return bio.getvalue()

def build_daily_hourly_figure(day, location_name):
    W,H=1800,1000;img=Image.new('RGB',(W,H),'white');d=ImageDraw.Draw(img);title=_pil_font(40,True);sub=_pil_font(22);small=_pil_font(15);axis=_pil_font(18)
    d.text((100,45),f'DAILY HOURLY CONGESTION — {location_name}',fill=(15,23,42),font=title);d.text((100,103),f"{day.get('date')} · 24-hour WAT timeline · missing hours shown as gaps",fill=(60,72,90),font=sub)
    L,T,R,B=170,210,1660,820;PW=R-L;PH=B-T
    for i in range(5):y=T+PH*i/4;v=1-i/4;d.line((L,y,R,y),fill=(224,229,236),width=2);d.text((105,y-10),f'{v:.2f}',fill=(70,80,95),font=axis)
    pts=[]
    for h in range(24):
        x=L+PW*h/23;r=(day.get('hourly') or [])[h] if h<len(day.get('hourly') or []) else None;ci=(r or {}).get('mean_congestion_index')
        if ci is None:
            if len(pts)>1:d.line(pts,fill=(25,130,210),width=5)
            pts=[]
        else:
            y=B-max(0,min(1,float(ci)))*PH;pts.append((x,y));c=(45,212,191) if ci<.2 else (250,204,21) if ci<.35 else (251,146,60) if ci<.5 else (239,68,68) if ci<.7 else (185,28,28);d.ellipse((x-7,y-7,x+7,y+7),fill=c)
        if h%2==0:d.text((x-22,B+18),f'{h:02d}:00',fill=(70,80,95),font=small)
    if len(pts)>1:d.line(pts,fill=(25,130,210),width=5)
    if day.get('peak_hour'):
        try:
            from zoneinfo import ZoneInfo
            ph=datetime.fromisoformat(str(day['peak_hour'])).astimezone(ZoneInfo('Africa/Lagos')).hour;px=L+PW*ph/23;d.line((px,T,px,B),fill=(220,25,65),width=3);d.text((min(px+8,R-220),T+12),f'Peak {ph:02d}:00 WAT · CI {day.get("peak_congestion_index")}',fill=(160,20,50),font=small)
        except Exception:pass
    d.text((650,900),'Hour of day — West Africa Time (00:00–23:00)',fill=(40,50,65),font=axis);bio=BytesIO();img.save(bio,'PNG',dpi=(300,300));return bio.getvalue()

def _recommendations(a):
    sm=a['summary']; q=a['data_quality']; rec=[]
    ci=sm.get('mean_congestion_index') or 0; delay=sm.get('mean_delay_seconds') or 0
    heavy=sm.get('heavy_plus_share_pct') or 0; cov=a['coverage'].get('combined_hourly_coverage_pct') or 0
    if ci>=.5 or heavy>=30: rec.append('Prioritise corridor-level operational review, intersection control assessment and recurring bottleneck diagnosis.')
    if delay>=180: rec.append('Investigate signal timing, turning conflicts, loading/parking friction and demand-management options because average delay is operationally material.')
    if sm.get('buffer_index_pct') is not None and sm['buffer_index_pct']>=25: rec.append('Travel-time reliability is weak; publish reliability-aware travel information and examine recurrent vs incident-driven variability.')
    if cov<40: rec.append('Increase observation coverage and/or acquire legitimate historical-provider data before making strong long-period causal claims.')
    if not rec: rec.append('Maintain monitoring and use the current period as a baseline for detecting deterioration, recovery and incident-related deviations.')
    return rec

def _plot_series_png(a, kind='speed'):
    W,H=1800,1050; img=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(img)
    title=_pil_font(40,True); sub=_pil_font(22); small=_pil_font(16); axis=_pil_font(18)
    loc=a['location']; left,top,right,bottom=170,210,1660,850
    if kind=='speed':
        d.text((100,45),'ITICAS SPEED VS FREE-FLOW PROFILE',fill=(15,23,42),font=title)
        d.text((100,103),f"{loc['name']} — hourly evidence within last {a['period']['days']} day(s)",fill=(60,72,90),font=sub)
        rows=[r for r in a['hourly_timeseries'] if r['data_status']!='missing' and r['mean_speed_kmh'] is not None]
        vals=[r['mean_speed_kmh'] for r in rows]+[r['mean_free_flow_speed_kmh'] for r in rows if r['mean_free_flow_speed_kmh'] is not None]
        ymax=max(vals or [100])*1.1
        for i in range(6):
            y=bottom-(bottom-top)*i/5; d.line((left,y,right,y),fill=(224,229,236),width=2); d.text((95,y-10),f"{ymax*i/5:.0f}",fill=(70,80,95),font=axis)
        if rows:
            xs=[]; obs=[]; free=[]
            for i,r in enumerate(rows):
                x=left+(right-left)*(i/max(1,len(rows)-1)); xs.append(x); obs.append((x,bottom-(r['mean_speed_kmh']/ymax)*(bottom-top)))
                if r['mean_free_flow_speed_kmh'] is not None: free.append((x,bottom-(r['mean_free_flow_speed_kmh']/ymax)*(bottom-top)))
            if len(obs)>1:d.line(obs,fill=(30,115,190),width=5)
            if len(free)>1:d.line(free,fill=(35,160,95),width=4)
        d.text((710,905),'Chronological observed / historical-provider hourly buckets',fill=(40,50,65),font=axis)
        d.line((1050,960,1110,960),fill=(30,115,190),width=5);d.text((1120,948),'Traffic speed',fill=(40,50,65),font=small)
        d.line((1280,960,1340,960),fill=(35,160,95),width=5);d.text((1350,948),'Free-flow/reference',fill=(40,50,65),font=small)
    elif kind=='daily':
        d.text((100,45),'ITICAS DAILY CONGESTION TREND',fill=(15,23,42),font=title)
        d.text((100,103),f"{loc['name']} — daily mean congestion index",fill=(60,72,90),font=sub)
        rows=a['daily_profile'];
        for i in range(6):
            y=bottom-(bottom-top)*i/5; d.line((left,y,right,y),fill=(224,229,236),width=2);d.text((105,y-10),f"{i/5:.1f}",fill=(70,80,95),font=axis)
        pts=[]
        for i,r in enumerate(rows):
            x=left+(right-left)*(i/max(1,len(rows)-1)); y=bottom-float(r['mean_congestion_index'])*(bottom-top);pts.append((x,y));d.ellipse((x-6,y-6,x+6,y+6),fill=(190,55,65))
        if len(pts)>1:d.line(pts,fill=(190,55,65),width=4)
        d.text((730,905),'Calendar day — West Africa Time',fill=(40,50,65),font=axis)
    elif kind=='coverage':
        d.text((100,45),'ITICAS DATA COMPLETENESS MAP',fill=(15,23,42),font=title)
        d.text((100,103),f"{loc['name']} — requested hourly evidence status",fill=(60,72,90),font=sub)
        rows=a['hourly_timeseries']; cell=22; cols=24; startx=250; starty=220
        days=max(1,(len(rows)+23)//24)
        max_rows=min(days,30)
        for idx,r in enumerate(rows[-max_rows*24:]):
            rr=idx//24; cc=idx%24; state=r['data_status']; c=(55,165,95) if state=='observed_live' else ((70,125,210) if state=='historical_provider' else (225,229,235))
            x=startx+cc*cell;y=starty+rr*cell;d.rectangle((x,y,x+cell-2,y+cell-2),fill=c)
        for h in range(0,24,3):d.text((startx+h*cell,starty-30),f'{h:02d}',fill=(60,70,85),font=small)
        d.text((600,920),'Green: observed live   Blue: historical provider   Grey: missing',fill=(40,50,65),font=axis)
    d.line((left,bottom,right,bottom),fill=(30,41,59),width=2);d.line((left,top,left,bottom),fill=(30,41,59),width=2)
    d.text((100,1010),f"{settings.developer_credit} | Report ID {a['report_identity']['report_id']}",fill=(25,95,65),font=small)
    bio=BytesIO();img.save(bio,format='PNG',dpi=(300,300));return bio.getvalue()


def _report_font(size=26,bold=False):
    candidates=[]
    if bold:
        candidates += [r"C:\Windows\Fonts\segoeuib.ttf",r"C:\Windows\Fonts\arialbd.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    else:
        candidates += [r"C:\Windows\Fonts\segoeui.ttf",r"C:\Windows\Fonts\arial.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for f in candidates:
        try:
            return ImageFont.truetype(f,size)
        except Exception: pass
    return ImageFont.load_default()

def _latest_segment_coords(location_id):
    with SessionLocal() as db:
        row=db.scalar(select(TrafficObservation).where(TrafficObservation.location_id==location_id,TrafficObservation.segment_geometry_json.is_not(None)).order_by(TrafficObservation.observed_at.desc()))
    if not row or not row.segment_geometry_json:return []
    try:
        obj=json.loads(row.segment_geometry_json);pts=obj.get('coordinate') or obj.get('coordinates') or [];out=[]
        for q in pts:
            if isinstance(q,dict):lat=q.get('latitude');lon=q.get('longitude')
            elif isinstance(q,(list,tuple)) and len(q)>=2:lon,lat=q[0],q[1]
            else:continue
            if lat is not None and lon is not None:out.append((float(lon),float(lat)))
        return out
    except Exception:return []

def _static_basemap(bbox,width,height):
    """Render a resilient basemap through the ITICAS cached map stack.

    Test runs deliberately avoid external map I/O. Production rendering uses a
    reduced tile canvas and upscales it so report generation is not held hostage
    by dozens of network tile requests.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    try:
        minx,miny,maxx,maxy=bbox
        center_lon=(minx+maxx)/2; center_lat=(miny+maxy)/2
        rw=min(960,max(640,int(width*.60))); rh=min(620,max(420,int(height*.60)))
        chosen=6
        for z in range(18,3,-1):
            def wp(lon,lat):
                lat=max(-85.05112878,min(85.05112878,lat)); n=256*(2**z)
                x=(lon+180.0)/360.0*n; ss=math.sin(math.radians(lat))
                y=(0.5-math.log((1+ss)/(1-ss))/(4*math.pi))*n
                return x,y
            x0,y1=wp(minx,miny); x1,y0=wp(maxx,maxy)
            if abs(x1-x0)<=rw*.78 and abs(y1-y0)<=rh*.78:
                chosen=z; break
        raw,_provider=render_static_map(center_lat,center_lon,chosen,rw,rh)
        if not _provider or str(_provider).lower()=='unavailable':
            return None
        return Image.open(BytesIO(raw)).convert('RGB').resize((width,height))
    except Exception:
        return None

def _bbox_from_points(points,pad=.18):
    if not points:return (2.0,3.0,15.0,14.8)
    xs=[p[0] for p in points];ys=[p[1] for p in points];dx=max(max(xs)-min(xs),.01);dy=max(max(ys)-min(ys),.01)
    return (min(xs)-dx*pad,min(ys)-dy*pad,max(xs)+dx*pad,max(ys)+dy*pad)

def _project(lon,lat,bbox,left,top,w,h):
    minx,miny,maxx,maxy=bbox
    x=left+(lon-minx)/max(1e-9,maxx-minx)*w;y=top+(maxy-lat)/max(1e-9,maxy-miny)*h
    return int(x),int(y)

def _cartographic_base(title,subtitle,bbox,width=1800,height=1200):
    margin=90; top=175; mapw=width-2*margin; maph=height-top-150
    base=_static_basemap(bbox,mapw,maph)
    img=Image.new('RGB',(width,height),'white');d=ImageDraw.Draw(img)
    if base:img.paste(base,(margin,top))
    else:
        d.rectangle((margin,top,margin+mapw,top+maph),fill=(247,246,237),outline=(70,80,90),width=2)
        for i in range(1,6):
            x=margin+i*mapw/6;y=top+i*maph/6
            d.line((x,top,x,top+maph),fill=(218,220,216),width=1);d.line((margin,y,margin+mapw,y),fill=(218,220,216),width=1)
    d.text((margin,32),title,font=_report_font(44,True),fill=(10,18,30));d.text((margin,95),subtitle,font=_report_font(23),fill=(70,80,95))
    d.rectangle((margin,top,margin+mapw,top+maph),outline=(35,45,55),width=2)
    # north arrow
    nx=margin+50;ny=top+70;d.polygon([(nx,ny-38),(nx-16,ny+18),(nx,ny+8),(nx+16,ny+18)],fill=(15,23,42));d.text((nx-11,ny-68),'N',font=_report_font(24,True),fill=(15,23,42))
    return img,d,(margin,top,mapw,maph)

def _footer_map(d,width,height,caption):
    d.line((90,height-105,width-90,height-105),fill=(160,170,180),width=2)
    d.text((90,height-87),caption,font=_report_font(18),fill=(60,70,80))
    d.text((90,height-54),settings.developer_credit,font=_report_font(17,True),fill=(15,70,55))

def build_route_map(a):
    loc=a['location']; seg=_latest_segment_coords(loc['id']); center=[]
    with SessionLocal() as db:
        ml=db.get(MonitoringLocation,loc['id'])
        if ml and ml.longitude is not None:center=[(float(ml.longitude),float(ml.latitude))]
    pts=seg or center; bbox=_bbox_from_points(pts or [(8.6753,9.082)],pad=.28)
    sm=a['summary']; cov=a['coverage']
    img,d,geo=_cartographic_base(
        f"SELECTED ROAD / SEGMENT CONTEXT — {loc['name']}",
        f"{loc.get('city') or ''}, {loc.get('state') or ''}, Nigeria · traffic segment geometry, direction, evidence point and performance context",
        bbox
    );left,top,w,h=geo
    # Geographic graticule labels
    minx,miny,maxx,maxy=bbox
    for i in range(5):
        lon=minx+(maxx-minx)*i/4; x=left+w*i/4
        d.text((x-40,top+h+8),f"{lon:.4f}°E",font=_report_font(14),fill=(55,65,78))
        lat=maxy-(maxy-miny)*i/4; y=top+h*i/4
        d.text((left-82,y-8),f"{lat:.4f}°N",font=_report_font(14),fill=(55,65,78))
    seg_km=0.0
    if len(seg)>1:
        for p0,p1 in zip(seg,seg[1:]):
            seg_km+=haversine_km(p0[1],p0[0],p1[1],p1[0])
        xy=[_project(x,y,bbox,left,top,w,h) for x,y in seg]
        d.line(xy,fill=(255,255,255),width=15);d.line(xy,fill=(220,55,55),width=9)
        # Start / end and direction
        sx,sy=xy[0];ex,ey=xy[-1]
        d.ellipse((sx-10,sy-10,sx+10,sy+10),fill=(45,185,95),outline='white',width=3);d.text((sx+14,sy-14),'START',font=_report_font(16,True),fill=(20,30,40))
        d.rectangle((ex-9,ey-9,ex+9,ey+9),fill=(35,95,210),outline='white',width=3);d.text((ex+14,ey-14),'END',font=_report_font(16,True),fill=(20,30,40))
        mid=max(1,min(len(xy)-2,len(xy)//2)); x0,y0=xy[mid-1];x1,y1=xy[mid+1]
        ang=math.atan2(y1-y0,x1-x0);cx,cy=xy[mid];size=20
        tri=[(cx+math.cos(ang)*size,cy+math.sin(ang)*size),
             (cx+math.cos(ang+2.5)*size*.72,cy+math.sin(ang+2.5)*size*.72),
             (cx+math.cos(ang-2.5)*size*.72,cy+math.sin(ang-2.5)*size*.72)]
        d.polygon(tri,fill=(20,30,45))
    for x,y in center:
        px,py=_project(x,y,bbox,left,top,w,h);d.ellipse((px-10,py-10,px+10,py+10),fill=(35,210,120),outline='white',width=3)
        d.text((px+14,py-12),'ITICAS evidence point',font=_report_font(16,True),fill=(20,25,30))
    # Dynamic scale bar
    if pts:
        lat=sum(y for _,y in pts)/len(pts);target_km=max(.1,round(max(seg_km/4,.5),1));deg=target_km/(111.32*max(.2,math.cos(math.radians(lat))))
        x0,y0=_project(bbox[0]+.08*(bbox[2]-bbox[0]),bbox[1]+.08*(bbox[3]-bbox[1]),bbox,left,top,w,h)
        x1,_=_project(bbox[0]+.08*(bbox[2]-bbox[0])+deg,bbox[1]+.08*(bbox[3]-bbox[1]),bbox,left,top,w,h)
        d.line((x0,y0,x1,y0),fill='black',width=5);d.text((x0,y0-30),f'{target_km:g} km',font=_report_font(17,True),fill='black')
    # Decision context box
    bx=left+w-455;by=top+35;d.rectangle((bx,by,bx+425,by+300),fill=(255,255,255),outline=(95,105,115),width=2)
    metrics=[
        ('Road / location',loc.get('road_name') or loc['name']),('Segment length',f'{seg_km:.2f} km' if seg_km else 'geometry unavailable'),
        ('Mean speed',f"{sm.get('mean_speed_kmh')} km/h"),('Free-flow',f"{sm.get('mean_free_flow_speed_kmh')} km/h"),
        ('Mean CI',sm.get('mean_congestion_index')),('Mean delay',f"{sm.get('mean_delay_seconds')} s"),
        ('TTI / PTI',f"{sm.get('travel_time_index')} / {sm.get('planning_time_index')}"),('Evidence hours',f"{cov.get('combined_hour_buckets_with_data')}/{cov.get('hour_buckets_total')}"),
    ]
    yy=by+16;d.text((bx+16,yy),'Selected-road context',font=_report_font(22,True),fill=(20,25,35));yy+=40
    for k,v in metrics:
        txt=f"{k}: {v if v is not None else '—'}";d.text((bx+16,yy),txt,font=_report_font(16),fill=(35,45,55));yy+=29
    _footer_map(d,img.width,img.height,f"WGS84 geographic · selected road only · Report ID {a['report_identity']['report_id']} · validation: {a['validation']['status']}")
    bio=BytesIO();img.save(bio,'PNG',dpi=(300,300));return bio.getvalue()

def _local_spatial_points(a,days):
    loc=a['location'];with_all=spatial_summary(days,5.0).get('points',[])
    with SessionLocal() as db:
        m=db.get(MonitoringLocation,loc['id']);lat=float(m.latitude) if m and m.latitude is not None else None;lon=float(m.longitude) if m and m.longitude is not None else None
    if lat is None:return with_all
    nearby=[p for p in with_all if haversine_km(lat,lon,p['lat'],p['lon'])<=30]
    return nearby if len(nearby)>=3 else [p for p in with_all if p.get('state')==loc.get('state')] or with_all

def _parse_report_dt(value):
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        dt=value
    else:
        try:
            dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _probe_spatial_evidence(a):
    """Aggregate point-specific corridor-probe observations for the report period.

    This is descriptive intra-road evidence, not Getis-Ord Gi* significance.  It
    is used only when the selected road has actual probe observations.
    """
    loc_id=a['location']['id']
    start=_parse_report_dt(a.get('period',{}).get('requested_from_utc'))
    end=_parse_report_dt(a.get('period',{}).get('requested_to_utc'))
    with SessionLocal() as db:
        probes=list(db.scalars(select(CorridorProbe).where(CorridorProbe.location_id==loc_id).order_by(CorridorProbe.chainage_m)).all())
        obs=list(db.scalars(select(CorridorProbeObservation).where(CorridorProbeObservation.location_id==loc_id)).all())
    by_probe={}
    for o in obs:
        if o.congestion_index is None or (o.provider_status and str(o.provider_status).lower() not in {'ok','success','completed'}):
            continue
        odt=_parse_report_dt(o.observed_at)
        if start and odt and odt < start: continue
        if end and odt and odt > end: continue
        by_probe.setdefault(o.probe_id,[]).append(o)
    rows=[]
    for p in probes:
        vals=by_probe.get(p.id,[])
        if not vals: continue
        cis=[float(o.congestion_index) for o in vals if o.congestion_index is not None]
        delays=[float(o.delay_seconds) for o in vals if o.delay_seconds is not None]
        if not cis: continue
        rows.append({
            'probe_id':p.id,'sequence_no':p.sequence_no,'chainage_m':float(p.chainage_m or 0),
            'lat':float(p.latitude),'lon':float(p.longitude),'samples':len(cis),
            'mean_ci':sum(cis)/len(cis),'max_ci':max(cis),
            'mean_delay':(sum(delays)/len(delays) if delays else None),
        })
    if not rows:
        return {'rows':[],'hotspots':[],'threshold':None,'note':'No point-specific corridor-probe observations are available for this report period.'}
    sorted_means=sorted(r['mean_ci'] for r in rows)
    qidx=max(0,min(len(sorted_means)-1,math.ceil(.75*len(sorted_means))-1))
    threshold=max(.20,sorted_means[qidx])
    hotspots=[r for r in rows if r['mean_ci'] >= threshold]
    return {
        'rows':rows,'hotspots':hotspots,'threshold':threshold,
        'note':f"Descriptive probe hotspots use the upper-quartile mean CI with a floor of 0.20 (threshold {threshold:.3f}); they are not Gi* significance tests."
    }


def _ci_color(ci):
    ci=float(ci or 0)
    if ci < .10: return (55,190,105)
    if ci < .20: return (115,205,120)
    if ci < .40: return (245,205,70)
    if ci < .65: return (245,135,55)
    return (205,50,60)


def _draw_axis_title_y(img, text, x, y_center, size=18):
    font=_report_font(size,True)
    # Render on a transparent label canvas then rotate, so the title reads as a
    # conventional vertical y-axis label without disturbing the plot geometry.
    box=font.getbbox(text); w=max(1,box[2]-box[0]+12); h=max(1,box[3]-box[1]+12)
    lab=Image.new('RGBA',(w,h),(255,255,255,0)); ld=ImageDraw.Draw(lab)
    ld.text((6,6),text,font=font,fill=(55,65,78,255))
    lab=lab.rotate(90,expand=True)
    img.paste(lab,(int(x-lab.width/2),int(y_center-lab.height/2)),lab)


def _draw_axis_title_x(d, text, x_center, y, size=18):
    font=_report_font(size,True); box=d.textbbox((0,0),text,font=font)
    d.text((x_center-(box[2]-box[0])/2,y),text,font=font,fill=(55,65,78))

def build_hotspot_map(a):
    """Selected-road congestion map with evidence-gated intra-road hotspots.

    If corridor-probe observations exist, each probe is mapped using its own
    measured mean congestion index and upper-quartile moderate-or-worse probes
    are haloed as descriptive hotspots.  If point-specific data do not exist,
    the map falls back to the road-wide mean and explicitly says so.
    """
    loc=a['location']; seg=_latest_segment_coords(loc['id']); center=[]
    with SessionLocal() as db:
        ml=db.get(MonitoringLocation,loc['id'])
        if ml and ml.longitude is not None:center=[(float(ml.longitude),float(ml.latitude))]
    pe=_probe_spatial_evidence(a)
    probe_pts=[(r['lon'],r['lat']) for r in pe['rows']]
    pts=(seg or center)+probe_pts; bbox=_bbox_from_points(pts or [(8.6753,9.082)])
    sm=a['summary']; ci=sm.get('mean_congestion_index') or 0
    severity='Free/low' if ci<.2 else 'Moderate' if ci<.4 else 'Heavy' if ci<.65 else 'Severe'
    img,d,geo=_cartographic_base(f"SINGLE-ROAD CONGESTION HOTSPOTS — {loc['name']}",f"{loc.get('city') or ''}, {loc.get('state') or ''}, Nigeria · point-specific probe evidence where available",bbox);left,top,w,h=geo
    # Base road geometry.
    if seg:
        xy=[_project(x,y,bbox,left,top,w,h) for x,y in seg];d.line(xy,fill=(255,255,255),width=16);d.line(xy,fill=(120,130,140),width=10)
    # Draw measured probe-to-probe sections using local mean CI.
    if len(pe['rows']) >= 2:
        ordered=sorted(pe['rows'],key=lambda r:r['chainage_m'])
        for a0,a1 in zip(ordered,ordered[1:]):
            p0=_project(a0['lon'],a0['lat'],bbox,left,top,w,h);p1=_project(a1['lon'],a1['lat'],bbox,left,top,w,h)
            col=_ci_color((a0['mean_ci']+a1['mean_ci'])/2)
            d.line((p0,p1),fill=(255,255,255),width=15);d.line((p0,p1),fill=col,width=9)
        for r in ordered:
            px,py=_project(r['lon'],r['lat'],bbox,left,top,w,h); col=_ci_color(r['mean_ci'])
            if r in pe['hotspots']:
                d.ellipse((px-18,py-18,px+18,py+18),outline=(205,45,55),width=5)
            d.ellipse((px-8,py-8,px+8,py+8),fill=col,outline='white',width=2)
    elif seg:
        xy=[_project(x,y,bbox,left,top,w,h) for x,y in seg];d.line(xy,fill=(255,255,255),width=16);d.line(xy,fill=_ci_color(ci),width=10)
    for x,y in center:
        px,py=_project(x,y,bbox,left,top,w,h);d.ellipse((px-11,py-11,px+11,py+11),fill=(35,210,120),outline='white',width=3);d.text((px+16,py-12),loc['name'],font=_report_font(21,True),fill=(20,25,30))
    bx=left+w-470;by=top+35;d.rectangle((bx,by,bx+440,by+330),fill=(255,255,255),outline=(100,110,120))
    lines=[('Road-wide mean CI',sm.get('mean_congestion_index')),('Road-wide class',severity),('Mean delay (s)',sm.get('mean_delay_seconds')),('Probe points with data',len(pe['rows'])),('Descriptive hotspots',len(pe['hotspots'])),('Hotspot CI threshold',f"{pe['threshold']:.3f}" if pe['threshold'] is not None else '—'),('TTI',sm.get('travel_time_index')),('Evidence grade',sm.get('evidence_grade'))]
    yy=by+18;d.text((bx+16,yy),'Selected-road hotspot evidence',font=_report_font(20,True),fill=(20,25,35));yy+=40
    for k,v in lines:d.text((bx+16,yy),f"{k}: {v if v is not None else '—'}",font=_report_font(16),fill=(35,45,55));yy+=27
    # Legend for local probe severity.
    ly=top+h-48; lx=left+25
    for lab,col in [('Free',(55,190,105)),('Light',(115,205,120)),('Moderate',(245,205,70)),('Heavy',(245,135,55)),('Severe',(205,50,60))]:
        d.rectangle((lx,ly,lx+18,ly+18),fill=col);d.text((lx+25,ly-2),lab,font=_report_font(13),fill=(30,40,50));lx+=125
    if pe['hotspots']:
        d.ellipse((lx,ly-2,lx+22,ly+20),outline=(205,45,55),width=4);d.text((lx+30,ly-2),'Hotspot probe',font=_report_font(13,True),fill=(30,40,50))
    note=pe['note']
    _footer_map(d,img.width,img.height,note)
    bio=BytesIO();img.save(bio,'PNG',dpi=(300,300));return bio.getvalue()

def build_kernel_map(a):
    """Selected-road day-hour congestion heatmap.

    A one-road report does not have enough independent spatial observations for
    a defensible kernel surface along the road.  This figure therefore shows
    temporal congestion concentration for that road.  Network KDE remains an
    optional multi-route product in Spatial Intelligence.
    """
    rows=[r for r in a['hourly_timeseries'] if r['data_status']!='missing']
    width,height=1800,1150;img=Image.new('RGB',(width,height),'white');d=ImageDraw.Draw(img)
    d.text((90,35),f"ROAD CONGESTION DAY–HOUR HEATMAP — {a['location']['name']}",font=_report_font(42,True),fill=(10,18,30));d.text((90,96),"Selected road only · observed/historical-provider hourly evidence",font=_report_font(23),fill=(70,80,95))
    left,top=220,190;cw=56;ch=34
    dates=sorted({str(r['hour_start'])[:10] for r in rows})[-24:]
    matrix={(str(r['hour_start'])[:10],int(str(r['hour_start'])[11:13])):r.get('mean_congestion_index') for r in rows if len(str(r['hour_start']))>=13}
    for h in range(24):d.text((left+h*cw+12,top-34),str(h),font=_report_font(15,True),fill=(40,50,65))
    _draw_axis_title_x(d,'Hour of day (WAT)',left+12*cw,top-72,17)
    _draw_axis_title_y(img,'Date',12,top+max(1,len(dates))*ch/2,17)
    for iy,date in enumerate(dates):
        d.text((55,top+iy*ch+7),date,font=_report_font(15),fill=(50,60,70))
        for h in range(24):
            v=matrix.get((date,h));x0=left+h*cw;y0=top+iy*ch
            if v is None:c=(230,234,238)
            elif v<.2:c=(70,190,105)
            elif v<.4:c=(245,205,70)
            elif v<.65:c=(245,135,55)
            else:c=(205,50,60)
            d.rectangle((x0,y0,x0+cw-2,y0+ch-2),fill=c)
    ly=top+max(1,len(dates))*ch+45;d.text((left,ly),'Legend: green free/low · yellow moderate · orange heavy · red severe · grey missing',font=_report_font(18),fill=(40,50,60))
    d.text((left,ly+38),f"Evidence shown: {len(rows)} hourly buckets. Missing hours are not fabricated.",font=_report_font(18),fill=(40,50,60))
    _footer_map(d,width,height,"Single-road temporal concentration figure. Historical-provider hours, when present, remain provenance-labelled in the accompanying tables.")
    bio=BytesIO();img.save(bio,'PNG',dpi=(300,300));return bio.getvalue()

def _figure_base(title,subtitle,width=1800,height=1050):
    img=Image.new('RGB',(width,height),'white');d=ImageDraw.Draw(img)
    d.text((90,35),title,font=_report_font(42,True),fill=(10,18,30))
    d.text((90,96),subtitle,font=_report_font(22),fill=(70,80,95))
    return img,d

def build_delay_reliability_figure(a):
    rows=[r for r in a['hourly_timeseries'] if r['data_status']!='missing' and r.get('mean_delay_seconds') is not None]
    img,d=_figure_base(f"DELAY & TRAVEL-TIME RELIABILITY — {a['location']['name']}","Chronological evidence points · no interpolation across missing hours")
    L,T,R,B=150,190,1650,820;vals=[float(r['mean_delay_seconds']) for r in rows];ymax=max(vals+[60])*1.15
    for i in range(6):
        y=B-(B-T)*i/5;d.line((L,y,R,y),fill=(225,230,235),width=2);d.text((72,y-10),f"{ymax*i/5:.0f}",font=_report_font(15),fill=(65,75,88))
    if rows:
        n=max(1,len(rows)-1)
        for i,r in enumerate(rows):
            x=L+(R-L)*i/n;y=B-(float(r['mean_delay_seconds'])/ymax)*(B-T);c=(45,145,210) if r['data_status']=='observed_live' else (95,105,200)
            d.line((x,B,x,y),fill=(210,220,230),width=2);d.ellipse((x-6,y-6,x+6,y+6),fill=c,outline='white',width=2)
    sm=a['summary'];bx=1120;by=205;d.rectangle((bx,by,bx+500,by+205),fill=(255,255,255),outline=(100,110,120))
    for j,(k,v) in enumerate([('Mean delay (s)',sm.get('mean_delay_seconds')),('P85 delay (s)',sm.get('delay_p85_seconds')),('P95 delay (s)',sm.get('delay_p95_seconds')),('TTI',sm.get('travel_time_index')),('PTI',sm.get('planning_time_index')),('Buffer Index %',sm.get('buffer_index_pct'))]):
        d.text((bx+18,by+18+j*29),f"{k}: {v if v is not None else '—'}",font=_report_font(17),fill=(35,45,55))
    _draw_axis_title_x(d,'Evidence sequence', (L+R)/2, B+36,18)
    _draw_axis_title_y(img,'Delay (seconds)',24,(T+B)/2,18)
    d.text((L,B+76),'Observed live + historical-provider evidence, if available',font=_report_font(16),fill=(55,65,80))
    _footer_map(d,img.width,img.height,"Reliability indicators should be interpreted with evidence coverage and provider provenance.")
    bio=BytesIO();img.save(bio,'PNG',dpi=(300,300));return bio.getvalue()

def build_severity_distribution_figure(a):
    img,d=_figure_base(f"CONGESTION SEVERITY DISTRIBUTION — {a['location']['name']}","Observed live traffic classes in the selected period")
    cats=['Free flow','Light','Moderate','Heavy','Severe'];counts=[int(a.get('categories',{}).get(k,0)) for k in cats];total=sum(counts)
    colors_=[(70,190,105),(115,205,120),(245,205,70),(245,135,55),(205,50,60)]
    L,T,R,B=170,200,1640,800;barw=(R-L)/len(cats)*.62
    maxv=max(counts+[1])
    for i,(lab,cnt,col) in enumerate(zip(cats,counts,colors_)):
        x=L+(R-L)*(i+.5)/len(cats);h=(cnt/maxv)*(B-T);d.rectangle((x-barw/2,B-h,x+barw/2,B),fill=col)
        pct=(100*cnt/total) if total else 0;d.text((x-45,B-h-38),f"{cnt} ({pct:.1f}%)",font=_report_font(18,True),fill=(30,40,50));d.text((x-55,B+18),lab,font=_report_font(17),fill=(45,55,68))
    _draw_axis_title_x(d,'Congestion severity class',(L+R)/2,B+62,18)
    _draw_axis_title_y(img,'Observations (count)',24,(T+B)/2,18)
    sm=a['summary'];d.text((170,880),f"Moderate-or-worse: {sm.get('moderate_plus_share_pct')}%   Heavy-or-worse: {sm.get('heavy_plus_share_pct')}%   Severe: {sm.get('severe_share_pct')}%",font=_report_font(20,True),fill=(35,45,60))
    _footer_map(d,img.width,img.height,"Severity shares are based on available live observations; missing hours do not enter the denominator.")
    bio=BytesIO();img.save(bio,'PNG',dpi=(300,300));return bio.getvalue()

def build_clock_hour_figure(a):
    img,d=_figure_base(f"CLOCK-HOUR CONGESTION PROFILE — {a['location']['name']}","Mean congestion index by West Africa Time hour, using available evidence only")
    rows={int(r['hour']):r for r in a.get('hourly_profile',[])};L,T,R,B=130,190,1680,800;maxv=max([float(r['mean_congestion_index']) for r in rows.values()]+[.2])
    step=(R-L)/24
    for h in range(24):
        r=rows.get(h);v=float(r['mean_congestion_index']) if r else 0;x=L+h*step+4;bw=step-8;hh=(v/maxv)*(B-T)
        col=(220,225,232) if not r else ((70,190,105) if v<.2 else (245,205,70) if v<.5 else (245,135,55) if v<.7 else (205,50,60))
        d.rectangle((x,B-max(3,hh),x+bw,B),fill=col)
        if h%2==0:d.text((x+3,B+16),f"{h:02d}",font=_report_font(14),fill=(55,65,78))
        if r:d.text((x+2,B-max(3,hh)-28),str(r.get('samples',0)),font=_report_font(13),fill=(60,70,82))
    _draw_axis_title_x(d,'Hour of day (WAT)',(L+R)/2,B+50,18)
    _draw_axis_title_y(img,'Mean congestion index',24,(T+B)/2,18)
    d.text((130,880),'Numbers above bars = evidence samples contributing to each clock-hour estimate.',font=_report_font(18),fill=(55,65,78))
    _footer_map(d,img.width,img.height,"Clock-hour screening helps identify recurrent peak windows; sparse hours should not be over-interpreted.")
    bio=BytesIO();img.save(bio,'PNG',dpi=(300,300));return bio.getvalue()

def build_evidence_timeline_figure(a):
    rows=a['hourly_timeseries'];img,d=_figure_base(f"DATA COMPLETENESS & PROVENANCE — {a['location']['name']}","Requested hours classified as observed live, historical provider or missing")
    dates=[];by={}
    for r in rows:
        ds=str(r['hour_start'])[:10]
        if ds not in by:dates.append(ds);by[ds]={}
        try:hh=int(str(r['hour_start'])[11:13])
        except Exception:continue
        by[ds][hh]=r['data_status']
    dates=dates[-31:];L,T=230,190;cw=54;ch=25
    for h in range(24):d.text((L+h*cw+10,T-28),f"{h:02d}",font=_report_font(13,True),fill=(55,65,78))
    cmap={'observed_live':(65,185,105),'historical_provider':(70,125,210),'missing':(226,230,236)}
    _draw_axis_title_x(d,'Hour of day (WAT)',L+12*cw,T-68,17)
    _draw_axis_title_y(img,'Date',18,T+max(1,len(dates))*ch/2,17)
    for iy,ds in enumerate(dates):
        d.text((45,T+iy*ch+4),ds,font=_report_font(14),fill=(55,65,78))
        for h in range(24):
            st=by.get(ds,{}).get(h,'missing');x=L+h*cw;y=T+iy*ch;d.rectangle((x,y,x+cw-2,y+ch-2),fill=cmap.get(st,cmap['missing']))
    ly=T+max(1,len(dates))*ch+38
    for i,(lab,col) in enumerate([('Observed live',cmap['observed_live']),('Historical provider',cmap['historical_provider']),('Missing',cmap['missing'])]):
        x=L+i*300;d.rectangle((x,ly,x+25,ly+25),fill=col);d.text((x+35,ly+1),lab,font=_report_font(17),fill=(45,55,68))
    cov=a['coverage'];d.text((L,ly+55),f"Combined hourly coverage: {cov.get('combined_hourly_coverage_pct')}% · evidence hours: {cov.get('combined_hour_buckets_with_data')}/{cov.get('hour_buckets_total')}",font=_report_font(19,True),fill=(35,45,60))
    _footer_map(d,img.width,img.height,"Grey cells are genuinely missing evidence; ITICAS does not silently impute them in observed-data reporting.")
    bio=BytesIO();img.save(bio,'PNG',dpi=(300,300));return bio.getvalue()

def build_decision_dashboard_figure(a):
    img,d=_figure_base(f"ROAD DECISION DASHBOARD — {a['location']['name']}","Traffic performance, reliability, congestion burden and evidence readiness")
    sm=a['summary'];cov=a['coverage'];comb=a.get('combined_evidence_summary',{})
    cards=[
        ('Mean speed',f"{sm.get('mean_speed_kmh')} km/h"),('Speed reduction',f"{sm.get('mean_speed_reduction_pct')}%"),
        ('Mean CI',sm.get('mean_congestion_index')),('Mean delay',f"{sm.get('mean_delay_seconds')} s"),
        ('TTI',sm.get('travel_time_index')),('PTI',sm.get('planning_time_index')),('Buffer Index',f"{sm.get('buffer_index_pct')}%"),
        ('Heavy+ share',f"{sm.get('heavy_plus_share_pct')}%"),('Congestion episodes',sm.get('congestion_episode_count')),
        ('Longest episode',f"{sm.get('longest_congestion_episode_hours')} h"),('Evidence grade',sm.get('evidence_grade')),
        ('Combined coverage',f"{cov.get('combined_hourly_coverage_pct')}%")
    ]
    x0,y0=100,180;cw,ch=390,145;gapx,gapy=35,30
    for i,(k,v) in enumerate(cards):
        col=i%4;row=i//4;x=x0+col*(cw+gapx);y=y0+row*(ch+gapy)
        d.rounded_rectangle((x,y,x+cw,y+ch),radius=18,fill=(245,248,250),outline=(190,200,210),width=2)
        d.text((x+22,y+20),k,font=_report_font(17),fill=(70,80,95));d.text((x+22,y+65),str(v if v is not None else '—'),font=_report_font(29,True),fill=(15,25,42))
    recs=_recommendations_expanded(a)[:4];y=735;d.text((100,y),'Decision signals',font=_report_font(23,True),fill=(20,30,45));y+=42
    for r in recs:d.text((120,y),'• '+r[:150],font=_report_font(16),fill=(45,55,70));y+=34
    _footer_map(d,img.width,img.height,"Decision dashboard is evidence-screening support, not a substitute for engineering design or field validation.")
    bio=BytesIO();img.save(bio,'PNG',dpi=(300,300));return bio.getvalue()

def _recommendations_expanded(a):
    sm=a['summary'];c=a['coverage'];out=list(_recommendations(a))
    if sm.get('peak_am'):out.append(f"AM peak screening identifies {sm['peak_am']['hour']:02d}:00 as the strongest observed morning congestion hour; examine signal timing, curb activity and junction capacity during this window.")
    if sm.get('peak_pm'):out.append(f"PM peak screening identifies {sm['peak_pm']['hour']:02d}:00 as the strongest observed afternoon/evening congestion hour; compare directional demand and incident exposure.")
    if (sm.get('congestion_episode_count') or 0)>0:out.append(f"{sm.get('congestion_episode_count')} congestion episode(s) were detected in available hourly evidence; longest observed episode={sm.get('longest_congestion_episode_hours')} h. Prioritise recurrent windows for field validation/intervention testing.")
    if c.get('combined_hourly_coverage_pct',0)<50:out.append("Increase temporal evidence coverage and complete historical-provider backfill before treating long-period rankings as definitive.")
    out.append("Use before/after evaluation when traffic management interventions are implemented so changes in speed, delay, reliability and congestion persistence are quantified rather than described qualitatively.")
    out.append("Where multiple routes serve the same OD movement, compare route reliability and congestion burden before recommending diversion or traveller-information strategies.")
    return out

def build_docx(a):
    doc=Document(); sec=doc.sections[0]; sec.top_margin=Inches(.6);sec.bottom_margin=Inches(.6);sec.left_margin=Inches(.7);sec.right_margin=Inches(.7)
    loc=a['location'];sm=a['summary'];cov=a['coverage'];comb=a.get('combined_evidence_summary',{});q=a['data_quality']
    doc.add_heading(settings.app_name,0);doc.add_heading('Comprehensive Traffic Performance, Spatial & Decision Intelligence Report',1);doc.add_paragraph(f"Study location: {loc['name']} — {loc.get('city') or ''}, {loc.get('state') or ''}, Nigeria");doc.add_paragraph(f"Requested period: last {a['period']['days']} day(s) | Report ID: {a['report_identity']['report_id']}");doc.add_paragraph(settings.developer_credit)
    doc.add_heading('1. Executive Decision Summary',1);doc.add_paragraph(f"ITICAS analysed {q['observations']} live observations and {q.get('historical_provider_samples',0)} historical-provider hourly samples. Combined hourly coverage is {cov.get('combined_hourly_coverage_pct')}% (evidence grade {sm.get('evidence_grade')}). Live mean speed is {sm.get('mean_speed_kmh')} km/h versus {sm.get('mean_free_flow_speed_kmh')} km/h free-flow/reference. Combined hourly evidence mean speed is {comb.get('mean_speed_kmh')} km/h and combined mean congestion index is {comb.get('mean_congestion_index')}. Travel-time reliability indicators are TTI={sm.get('travel_time_index')}, PTI={sm.get('planning_time_index')}, Buffer Index={sm.get('buffer_index_pct')}%.")
    doc.add_heading('2. Data Sources, Provenance, Coverage & Readiness',1);t=doc.add_table(rows=0,cols=2);t.style='Table Grid'
    for k,v in _metadata_rows(a):r=t.add_row().cells;r[0].text=str(k);r[1].text='' if v is None else str(v)
    doc.add_paragraph(f"Historical-provider hours used in combined evidence: {comb.get('historical_provider_hour_count',0)}. Combined evidence uses live observations whenever present and historical provider statistics only for otherwise-missing hours.")
    doc.add_heading('3. Day-by-Day Hourly Analysis (Primary)',1);doc.add_paragraph('Each selected calendar day is analysed independently on a fixed 00:00–23:00 West Africa Time axis before any composite multi-day interpretation. Missing hours are shown as missing and are not interpolated.')
    for dday in a.get('day_by_day',[]):
        doc.add_heading(str(dday.get('date')),2);doc.add_paragraph(f"Evidence: {dday.get('hours_with_evidence')}/24 h | Coverage: {dday.get('coverage_pct')}% | Mean CI: {dday.get('mean_congestion_index')} | Peak: {dday.get('peak_hour')} | Peak CI: {dday.get('peak_congestion_index')} ({dday.get('peak_category')})")
        doc.add_picture(BytesIO(build_daily_hourly_figure(dday,loc['name'])),width=Inches(6.8))
        tbl=doc.add_table(rows=1,cols=5);tbl.style='Table Grid';
        for i,h in enumerate(['Hour WAT','Status','Speed km/h','CI','Delay s']):tbl.rows[0].cells[i].text=h
        for hh,r in enumerate(dday.get('hourly') or []):
            c=tbl.add_row().cells;vals=[f'{hh:02d}:00-{(hh+1)%24:02d}:00',r.get('data_status'),r.get('mean_speed_kmh'),r.get('mean_congestion_index'),r.get('mean_delay_seconds')]
            for i,v in enumerate(vals):c[i].text='' if v is None else str(v)
    doc.add_heading('4. Composite Multi-Day Traffic Performance',1)
    for label,key in [('Mean traffic speed','mean_speed_kmh'),('Median traffic speed','median_speed_kmh'),('Mean free-flow speed','mean_free_flow_speed_kmh'),('Mean congestion index','mean_congestion_index'),('Maximum congestion index','max_congestion_index'),('Mean delay seconds','mean_delay_seconds'),('Mean speed reduction %','mean_speed_reduction_pct')]:doc.add_paragraph(f"{label}: {sm.get(key)}",style='List Bullet')
    doc.add_heading('4. Speed Distribution & Variability',1);doc.add_paragraph(f"Speed percentiles P05/P15/P50/P85/P95: {sm.get('speed_p05_kmh')} / {sm.get('speed_p15_kmh')} / {sm.get('speed_p50_kmh')} / {sm.get('speed_p85_kmh')} / {sm.get('speed_p95_kmh')} km/h. Speed coefficient of variation: {sm.get('speed_coefficient_of_variation_pct')}%. ITICAS Temporal Stability Score: {sm.get('iticas_temporal_stability_score')} (experimental).")
    doc.add_heading('5. Travel-Time Reliability',1);doc.add_paragraph(f"TTI={sm.get('travel_time_index')}; PTI={sm.get('planning_time_index')}; Buffer Index={sm.get('buffer_index_pct')}%; 95th-percentile travel time={sm.get('p95_travel_time_seconds')} s. Delay percentiles P50/P85/P95={sm.get('delay_p50_seconds')} / {sm.get('delay_p85_seconds')} / {sm.get('delay_p95_seconds')} s.")
    doc.add_heading('6. Congestion Severity, Persistence & Episodes',1);doc.add_paragraph(f"Moderate-or-worse share={sm.get('moderate_plus_share_pct')}%; heavy-or-worse={sm.get('heavy_plus_share_pct')}%; severe={sm.get('severe_share_pct')}%. Available evidence contains {sm.get('congestion_episode_count')} congestion episode(s), longest={sm.get('longest_congestion_episode_hours')} h. Experimental ITICAS Congestion Burden Index={sm.get('iticas_congestion_burden_index')}.")
    doc.add_heading('7. Peak-Period & Day-Type Dynamics',1);doc.add_paragraph(f"Peak AM evidence: {sm.get('peak_am')}; Peak PM evidence: {sm.get('peak_pm')}; weekday mean CI={sm.get('weekday_mean_congestion_index')}; weekend mean CI={sm.get('weekend_mean_congestion_index')}; daily CI trend slope={sm.get('daily_congestion_trend_slope')} per evidence day.")
    doc.add_heading('8. Combined Historical + Live Evidence',1);doc.add_paragraph(f"Combined hourly evidence count={comb.get('hourly_evidence_count')}; historical-provider hours={comb.get('historical_provider_hour_count')}; combined mean speed={comb.get('mean_speed_kmh')} km/h; combined mean free-flow={comb.get('mean_free_flow_speed_kmh')} km/h; combined mean CI={comb.get('mean_congestion_index')}. Historical-provider-only mean speed={comb.get('historical_provider_mean_speed_kmh')} km/h and mean CI={comb.get('historical_provider_mean_congestion_index')}.")
    doc.add_heading('9. Publication Cartography & Spatial Evidence',1)
    for title,img in [('Selected road / segment context map',build_route_map(a)),('Single-road congestion evidence map',build_hotspot_map(a)),('Road day-hour congestion heatmap',build_kernel_map(a)),('Delay and travel-time reliability',build_delay_reliability_figure(a)),('Congestion severity distribution',build_severity_distribution_figure(a)),('Clock-hour congestion profile',build_clock_hour_figure(a)),('Data completeness and provenance',build_evidence_timeline_figure(a)),('Road decision dashboard',build_decision_dashboard_figure(a))]:
        doc.add_heading(title,2);doc.add_picture(BytesIO(img),width=Inches(6.8));doc.add_paragraph('Interpret this figure together with temporal coverage, provider provenance and statistical limitations.')
    doc.add_heading('10. Observed and Historical Hours with Evidence',1);doc.add_paragraph('Full 24/7 hourly grid, including missing hours, is retained in XLSX/CSV. This document lists only hours containing observed or historical-provider evidence so missing-data rows do not inflate the report.')
    rows=[r for r in a['hourly_timeseries'] if r['data_status']!='missing'];t=doc.add_table(rows=1,cols=7);t.style='Table Grid';heads=['Hour (Nigeria)','Origin','Samples','Speed','Free-flow','CI','Delay'];
    for i,h in enumerate(heads):t.rows[0].cells[i].text=h
    for r in rows[:500]:
        c=t.add_row().cells;vals=[r['hour_start'],r['data_status'],r['samples'],r['mean_speed_kmh'],r['mean_free_flow_speed_kmh'],r['mean_congestion_index'],r['mean_delay_seconds']]
        for i,v in enumerate(vals):c[i].text='' if v is None else str(v)
    doc.add_heading('11. Spatial/Intervention Priority Interpretation',1);doc.add_paragraph(f"Experimental Decision Priority Score={sm.get('iticas_decision_priority_score')} ({sm.get('iticas_decision_priority_class')}). This score is screening support, not an external standard. Spatial hotspot significance applies to the configured monitoring network and should not be interpreted as a census of all roads in Nigeria.")
    doc.add_heading('12. Decision Recommendations',1)
    for r in _recommendations_expanded(a):doc.add_paragraph(r,style='List Bullet')
    doc.add_heading('13. Validation, Uncertainty & Limitations',1);doc.add_paragraph(a['validation']['statement'])
    for item in a.get('limitations') or ['No additional limitation recorded.']:doc.add_paragraph(item,style='List Bullet')
    doc.add_heading('14. Methodological Notes',1);doc.add_paragraph('CI = 1 − current speed/free-flow speed. TTI, PTI and Buffer Index quantify travel-time performance/reliability. Single-road reports use selected-road context, temporal concentration, reliability, severity and evidence-completeness graphics. Getis-Ord Gi* and congestion-weighted kernel exposure are reserved for optional multi-route/network screening and are evidence-gated. Experimental ITICAS scores are transparent research indices and are not presented as external standards. Historical-provider values are never relabelled as live ITICAS observations.')
    doc.add_heading('15. Reproducibility Metadata',1);doc.add_paragraph(f"Dataset signature: {a['report_identity']['dataset_signature']}; generated UTC: {a['report_identity']['generated_at_utc']}; stage/version: {settings.stage}/{settings.version}; developer: {settings.developer_credit}.")
    bio=BytesIO();doc.save(bio);return bio.getvalue()

def build_pdf(a):
    bio=BytesIO();styles=getSampleStyleSheet();doc=SimpleDocTemplate(bio,pagesize=A4,rightMargin=32,leftMargin=32,topMargin=32,bottomMargin=32);sm=a['summary'];cov=a['coverage'];comb=a.get('combined_evidence_summary',{});loc=a['location']
    story=[Paragraph('ITICAS Comprehensive Traffic Performance, Spatial & Decision Intelligence Report',styles['Title']),Paragraph(escape(f"{loc['name']} — {loc.get('city') or ''}, {loc.get('state') or ''}, Nigeria"),styles['Heading2']),Paragraph(escape(settings.developer_credit),styles['Normal']),Spacer(1,10)]
    story += [Paragraph('Executive Decision Summary',styles['Heading1']),Paragraph(escape(f"Live observations={a['data_quality']['observations']}; historical-provider samples={a['data_quality'].get('historical_provider_samples',0)}; combined hourly coverage={cov.get('combined_hourly_coverage_pct')}%; evidence grade={sm.get('evidence_grade')}; live mean speed={sm.get('mean_speed_kmh')} km/h; combined evidence mean speed={comb.get('mean_speed_kmh')} km/h; mean CI={sm.get('mean_congestion_index')}; TTI={sm.get('travel_time_index')}; PTI={sm.get('planning_time_index')}; Buffer Index={sm.get('buffer_index_pct')}%."),styles['BodyText'])]
    metrics=[['Indicator','Value'],['Mean speed km/h',sm.get('mean_speed_kmh')],['Combined evidence speed km/h',comb.get('mean_speed_kmh')],['Mean congestion index',sm.get('mean_congestion_index')],['Combined evidence CI',comb.get('mean_congestion_index')],['Mean delay s',sm.get('mean_delay_seconds')],['Speed CV %',sm.get('speed_coefficient_of_variation_pct')],['P95 travel time s',sm.get('p95_travel_time_seconds')],['Congestion episodes',sm.get('congestion_episode_count')],['Longest episode h',sm.get('longest_congestion_episode_hours')],['Decision priority',sm.get('iticas_decision_priority_score')],['Evidence grade',sm.get('evidence_grade')]]
    t=Table(metrics,colWidths=[250,160]);t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dff7ec'))]));story += [Spacer(1,8),t,Spacer(1,10),Paragraph('Decision Recommendations',styles['Heading1'])]
    for r in _recommendations_expanded(a):story.append(Paragraph('• '+escape(r),styles['BodyText']))
    story += [Paragraph('Validation and Limitations',styles['Heading1']),Paragraph(escape(a['validation']['statement']),styles['BodyText'])]
    for item in a.get('limitations') or []:story.append(Paragraph('• '+escape(item),styles['BodyText']))
    story += [Paragraph('Cartographic deliverables',styles['Heading1']),Paragraph('Publication-quality selected-road context, congestion evidence, day-hour heatmap, reliability, severity, clock-hour, completeness/provenance and decision-dashboard graphics are included in the complete ZIP research package and DOCX report. Full hourly/missing-data tables are supplied in XLSX/CSV for reproducibility.',styles['BodyText'])]
    doc.build(story);return bio.getvalue()

def export_bytes(location_id:int, days:int, fmt:str):
    a=analyze_location(location_id,days)
    if a is None: raise KeyError('Location not found')
    fmt=fmt.lower();
    if fmt not in FORMATS: raise ValueError('Unsupported export format')
    if fmt=='json':
        return json.dumps(a,indent=2,default=str).encode('utf-8'), 'application/json', _filename(a,'json')
    if fmt=='maps':
        bio=BytesIO();stem=_filename(a,'zip')[:-4]
        with ZipFile(bio,'w',ZIP_DEFLATED) as z:
            z.writestr(stem+'_01_selected_road_context_map.png',build_route_map(a))
            z.writestr(stem+'_02_single_road_congestion_evidence.png',build_hotspot_map(a))
            z.writestr(stem+'_03_day_hour_congestion_heatmap.png',build_kernel_map(a))
            z.writestr(stem+'_04_delay_reliability_profile.png',build_delay_reliability_figure(a))
            z.writestr(stem+'_05_congestion_severity_distribution.png',build_severity_distribution_figure(a))
            z.writestr(stem+'_06_clock_hour_congestion_profile.png',build_clock_hour_figure(a))
            z.writestr(stem+'_07_data_completeness_provenance.png',build_evidence_timeline_figure(a))
            z.writestr(stem+'_08_road_decision_dashboard.png',build_decision_dashboard_figure(a))
            z.writestr(stem+'_DECISION_ATLAS_README.txt',('ITICAS selected-road decision atlas\n\nEach graphic answers a different question: geographic context, road performance, day-hour concentration, reliability/delay, severity mix, clock-hour pattern, evidence completeness/provenance and intervention decision signals. Network-wide hotspot/KDE analysis remains a separate optional Spatial Intelligence workflow. Missing hours are never fabricated.\n').encode('utf-8'))
        return bio.getvalue(),'application/zip',stem+'_decision_atlas.zip'
    builders={'csv':(build_csv,'text/csv'),'xlsx':(build_xlsx,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),'docx':(build_docx,'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),'pdf':(build_pdf,'application/pdf'),'svg':(build_svg,'image/svg+xml'),'png':(build_png,'image/png')}
    if fmt in builders:
        fn,mime=builders[fmt]; return fn(a),mime,_filename(a,fmt)
    bio=BytesIO()
    with ZipFile(bio,'w',ZIP_DEFLATED) as z:
        for ext in ('csv','xlsx','docx','pdf','svg','png','json'):
            data,mime,name=export_bytes(location_id,days,ext); z.writestr(name,data)
        stem=_filename(a,'zip')[:-4]
        z.writestr(stem+'_figure_02_speed_vs_freeflow.png',_plot_series_png(a,'speed'))
        z.writestr(stem+'_figure_03_daily_congestion.png',_plot_series_png(a,'daily'))
        z.writestr(stem+'_figure_04_data_completeness.png',_plot_series_png(a,'coverage'))
        z.writestr(stem+'_map_05_selected_road_context.png',build_route_map(a))
        z.writestr(stem+'_map_06_single_road_congestion_evidence.png',build_hotspot_map(a))
        z.writestr(stem+'_figure_07_day_hour_congestion_heatmap.png',build_kernel_map(a))
        z.writestr(stem+'_figure_08_delay_reliability.png',build_delay_reliability_figure(a))
        z.writestr(stem+'_figure_09_severity_distribution.png',build_severity_distribution_figure(a))
        z.writestr(stem+'_figure_10_clock_hour_profile.png',build_clock_hour_figure(a))
        z.writestr(stem+'_figure_11_completeness_provenance.png',build_evidence_timeline_figure(a))
        z.writestr(stem+'_figure_12_road_decision_dashboard.png',build_decision_dashboard_figure(a))
        for dday in a.get('day_by_day',[]): z.writestr(f"01_DAILY_ANALYSIS/{dday.get('date')}/{stem}_{dday.get('date')}_hourly_congestion.png",build_daily_hourly_figure(dday,a['location']['name']))
        z.writestr(stem+'_README.txt',('ITICAS research package\n\nFigures are publication-oriented analytical graphics. Missing hours are explicit. Historical-provider data are labelled separately from observed live data. The experimental ITICAS Decision Priority Score is a transparent research screening metric and is not an external standard.\n').encode('utf-8'))
    return bio.getvalue(),'application/zip',_filename(a,'zip')
