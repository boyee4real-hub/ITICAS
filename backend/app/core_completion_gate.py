from pathlib import Path
import importlib
REQUIRED_MODULES=[
'request_conservation','temporal_route_intelligence','spatial_route_intelligence',
'completion_intelligence','provider_enforcement','stage12_research_map'
]
def evaluate():
 root=Path('backend/app'); checks={}
 for m in REQUIRED_MODULES:
  checks['module_'+m]=(root/(m+'.py')).exists()
 try:
  from .request_policy import requires_live
  checks['passive_map_no_live']=requires_live('map_open') is False
  checks['passive_report_no_live']=requires_live('report_export') is False
  checks['explicit_live_available']=requires_live('explicit_live_acquisition') is True
 except Exception: 
  checks['passive_map_no_live']=checks['passive_report_no_live']=checks['explicit_live_available']=False
 try:
  from .provider_enforcement import diagnostics_policy
  checks['passive_diagnostics']=diagnostics_policy().get('network_provider_probe_default') is False
 except Exception: checks['passive_diagnostics']=False
 try:
  from .completion_intelligence import completion
  c=completion(); checks['historical_not_live']=c.get('historical_never_presented_as_live') is True
 except Exception: checks['historical_not_live']=False
 return {'checks':checks,'passed':sum(bool(x) for x in checks.values()),'total':len(checks),
         'core_development_complete':all(checks.values()),
         'next_gate':'publication/report qualification then central deployment/installer'}
