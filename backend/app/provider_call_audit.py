from pathlib import Path
TERMS=('tomtom.com','flowSegmentData','calculateRoute','api.tomtom')
def audit(root='backend/app'):
 hits=[]
 for p in Path(root).rglob('*.py'):
  try:s=p.read_text(encoding='utf-8',errors='ignore')
  except:continue
  for i,line in enumerate(s.splitlines(),1):
   if any(t.lower() in line.lower() for t in TERMS):
    hits.append({'file':str(p),'line':i,'text':line.strip()[:180]})
 return {'candidate_provider_call_sites':len(hits),'sites':hits,
 'note':'Candidate inventory for completion audit; presence does not prove an unguarded network call.'}
