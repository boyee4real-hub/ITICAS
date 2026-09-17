from .stage11_ui_bridge import latest
def dashboard(study_id='stage10_ibadan'):
    d=latest(study_id)
    d['source_status']={'provider':'TomTom','evidence_type':'Traffic-aware routing','direct_point_speed':False,'provenance_note':'Route-level traffic evidence; not direct point-speed.'}
    return d
