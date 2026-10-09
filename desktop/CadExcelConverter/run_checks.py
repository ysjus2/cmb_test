from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
checks = ['essenpoly_selftest.py', 'conduit_selftest.py', 'full_layer_selftest.py',
          'navigation_selftest.py', 'selftest.py', 'network_extract_selftest.py',
          'pipe_endpoint_selftest.py', 'identity_selftest.py', 'cache_selftest.py',
          'zoom_selftest.py', 'extract_display_selftest.py', 'current_features_selftest.py']
for check in checks:
    print(f'CHECK {check}', flush=True)
    subprocess.run([sys.executable, str(root / check)], cwd=root, check=True)
print('ALL CURRENT CHECKS PASSED')
