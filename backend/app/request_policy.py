NON_LIVE_ACTIONS={'page_open','tab_change','browser_refresh','report_export','csv_export','historical_analysis','temporal_analysis','spatial_analysis','research_workbench_open','map_open'}
def requires_live(action,force_live=False):
 if force_live:return True
 return str(action or '').strip().lower() not in NON_LIVE_ACTIONS
def policy():
 return {'default':'reuse_stored_or_cached_before_provider','non_live_actions':sorted(NON_LIVE_ACTIONS),
 'live_rule':'provider acquisition only when fresh traffic is explicitly required',
 'historical_never_relabelled_live':True}
