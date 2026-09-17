import os
os.environ['TOMTOM_API_KEYS']='iticas1:'+'A'*32+',iticas2:'+'B'*32+',iticas3:'+'C'*32+',iticas4:'+'D'*32+',iticas5:'+'E'*32
from backend.app.tomtom_keyring import safe_status
st=safe_status(); assert st['credential_count']==5; assert not st['secrets_exposed']
from backend.app.tomtom_traffic import TomTomTrafficClient
assert TomTomTrafficClient.fetch_flow.__name__=='_iticas_stage08_keyring_fetch_flow'
print('KEYRING_STATUS=',st)
print('[PASS] five credentials load without exposing secrets')
print('[PASS] Stage08 wrapper installed')
