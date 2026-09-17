from __future__ import annotations
from .request_policy import requires_live
from .request_conservation import event

def authorize(action:str, *, explicit_live:bool=False):
    allowed=requires_live(action, force_live=explicit_live)
    if not allowed:
        event('provider_call_prevented', action, 'non-live operation')
    return {'provider_call_allowed':allowed,'action':action,'explicit_live':explicit_live}

def diagnostics_policy():
    return {'network_provider_probe_default':False,
            'rule':'Diagnostics are passive by default; provider network probes require explicit live diagnostics.'}
