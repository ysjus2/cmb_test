from pathlib import Path
import re

COUNTIES = {'BS': '보성', 'DY': '담양', 'GR': '구례', 'HP': '함평',
            'HS': '화순', 'JS': '장성', 'NJ': '나주', 'YG': '영광', 'GS': '곡성'}

def drawing_code(source_path):
    if not source_path:
        return ''
    stem = Path(source_path).stem
    match = re.match(r'^CMB_GN_(BS|DY|GR|HP|HS|JS|NJ|YG|GS)(?=$|[^A-Z0-9])', stem, re.IGNORECASE)
    return 'CMB_GN_' + match.group(1).upper() if match else stem

def export_object_id(source_path, handle):
    value = str(handle or '').strip()
    code = drawing_code(source_path)
    if not code or not value:
        return value
    prefix = code + '_'
    return value if value.startswith(prefix) else prefix + value
