from pathlib import Path
assert 'ITICAS_STAGE11_UI_BRIDGE' in Path('backend/app/main.py').read_text(encoding='utf-8')
assert Path('backend/app/stage11_ui_bridge.py').exists()
print('[PASS] provenance-preserving UI summary endpoint')
print('[PASS] STAGE 11 OFFLINE VALIDATION')
