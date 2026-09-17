import os
class AzureTraffic:
 def __init__(self,key=None): self.key=key or os.getenv("AZURE_MAPS_SUBSCRIPTION_KEY")
 @property
 def configured(self): return bool(self.key)
 def status(self): return {"provider":"azure_maps","configured":self.configured,"status":"configured" if self.configured else "not_configured","note":"Optional; credential remains server-side."}
