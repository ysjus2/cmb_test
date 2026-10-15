"""Exercise real client concurrency and UI wiring without a server or Tk window."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import ast

from server_client_windows import CMBServerClient, ServerError
from main import App
from admin_upload import AdminUploadWindow
from session_guard import TkIdleSessionGuard

client = CMBServerClient('https://example.invalid')
client.access_token, client.refresh_token = 'old-access', 'old-refresh'
barrier = Barrier(7)
refreshes = []
expired = []
client.on_session_expired = lambda: expired.append(True)

def raw(method, path, payload=None, auth=True, timeout=60):
    if path == '/auth/refresh':
        assert payload['refresh_token'] == 'old-refresh'
        refreshes.append(payload.copy())
        return {'access_token': 'new-access', 'refresh_token': 'new-refresh'}
    if client.access_token == 'old-access':
        barrier.wait(timeout=10)
        raise ServerError('expired access', status=401)
    assert client.access_token == 'new-access'
    return {'ok': True}

client._raw_request = raw
with ThreadPoolExecutor(max_workers=7) as pool:
    results = list(pool.map(lambda p: client._request('GET', p),
        ['/touch', '/admin/users', '/register', '/regions', '/assign', '/upload', '/extract']))
assert all(r['ok'] for r in results)
assert len(refreshes) == 1 and client.refresh_token == 'new-refresh' and not expired
print('CONCURRENT_ROTATING_SESSION_OK')

bad = CMBServerClient('https://example.invalid')
bad.access_token, bad.refresh_token = 'old', 'refresh'
bad._raw_request = lambda *a, **kw: {}
try:
    bad.refresh()
    raise AssertionError('invalid refresh accepted')
except ServerError:
    assert bad.access_token == 'old'

# Invoke the actual App handlers, intercepting only window construction.
app = object.__new__(App)
app.session_client = client
app.session_user = {'level': 1}
app.input_path = str(Path(__file__).resolve())
app.viewer = SimpleNamespace(scene=object())
app.epsg_var = SimpleNamespace(get=lambda: '5174')
app._require_admin_permission = lambda: True
with patch('main.AdminUploadWindow') as upload, patch('main.UserAdminWindow') as users:
    app._open_admin_upload()
    app._open_user_admin()
    assert all(w.call_args.kwargs['client'] is client for w in (upload, users))
client.session_policy = lambda: {'idle_minutes': 10}
root = SimpleNamespace(bind_all=lambda *a, **k: None, after=lambda *a: None)
guard = TkIdleSessionGuard(root, lambda: None, client=client)
assert guard.client is client
# Nested registration/assignment callbacks must use the same window client.
tree = ast.parse(Path(__file__).with_name('admin_users.py').read_text(encoding='utf-8'))
calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
for method in ('admin_users', 'create_user', 'create_region', 'set_user_regions'):
    matching = [n for n in calls if n.func.attr == method]
    assert matching and all(ast.unparse(n.func.value) == 'self.client' for n in matching)
print('SHARED_SESSION_BEHAVIOR_OK')

class Widget:
    def __init__(self): self.value = ''; self.state = ''; self.values = []
    def set(self, value): self.value = value
    def get(self): return self.value
    def configure(self, **kw): self.state = kw.get('state', self.state)
    def __setitem__(self, key, value): setattr(self, key, value)

win = object.__new__(AdminUploadWindow)
win.client = SimpleNamespace(admin_regions=lambda: [{'id': 'CMB_GN_HP', 'name': '함평'}])
win.source_path = 'CMB_GN_HP.dxf'
for attr in ('region_var', 'region_combo', 'upload_one_btn', 'upload_all_btn', 'status'):
    setattr(win, attr, Widget())
with patch('admin_upload.messagebox.showerror') as error:
    win._load_server_regions()
    assert win._selected_region_code() == 'CMB_GN_HP'
    assert win.upload_one_btn.state == 'normal' and not error.called
    for filename in ('CMB_GN_HP_copy.dxf', 'cmb_gn_hp.dxf', '함평.dxf'):
        win.source_path = filename
        win._load_server_regions()
        assert win.upload_one_btn.state == win.upload_all_btn.state == 'disabled'
        assert not win.region_var.get()
        try: win._selected_region_code()
        except RuntimeError: pass
        else: raise AssertionError('mismatched region accepted')
    win.source_path = 'CMB_GN_HP.dxf'
    win._load_server_regions()
    win.client.admin_regions = lambda: (_ for _ in ()).throw(ServerError('unavailable'))
    win._load_server_regions()
    assert win.upload_one_btn.state == win.upload_all_btn.state == 'disabled'
    assert not win.region_display_to_id
source = Path(__file__).with_name('admin_upload.py').read_text(encoding='utf-8')
assert 'state="disabled",\n            width=52' in source
print('EXACT_UPLOAD_REGION_BEHAVIOR_OK')
