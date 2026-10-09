from pathlib import Path

def drawing_code(source_path):
    """DXF 파일명(확장자 제외)을 지역 코드로 그대로 사용한다."""
    if not source_path:
        return ""
    return Path(source_path).stem.strip()

def export_object_id(source_path, handle):
    value = str(handle or "").strip()
    code = drawing_code(source_path)
    if not code or not value:
        return value
    prefix = code + "_"
    return value if value.startswith(prefix) else prefix + value
