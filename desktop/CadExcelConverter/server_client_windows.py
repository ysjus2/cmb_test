from __future__ import annotations
import json, os, ssl, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path

BASE_URL="https://192.168.246.54:8443"
DEV_TOKEN=os.getenv("CMB_ACCESS_TOKEN","cmb-local-test").strip()

def resource_path(name):
    root=getattr(sys,"_MEIPASS",None)
    return os.path.join(root,name) if root else str(Path(__file__).resolve().with_name(name))

class ServerError(RuntimeError): pass

class CMBServerClient:
    def __init__(self,base_url=BASE_URL):
        self.base_url=base_url.rstrip("/")
        ca=resource_path("cmb_dev_ca.crt")
        self.ssl_context=ssl.create_default_context(cafile=ca) if os.path.exists(ca) else ssl.create_default_context()
        self.access_token=DEV_TOKEN
    def _request(self,method,path,payload=None,auth=True):
        body=None;headers={"Accept":"application/json"}
        if payload is not None:
            body=json.dumps(payload,ensure_ascii=False).encode("utf-8")
            headers["Content-Type"]="application/json; charset=utf-8"
        if auth and self.access_token: headers["Authorization"]="Bearer "+self.access_token
        req=urllib.request.Request(self.base_url+path,data=body,headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,context=self.ssl_context,timeout=30) as resp:
                raw=resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail=e.read().decode("utf-8","replace")
            raise ServerError(f"HTTP {e.code}: {detail or e.reason}") from e
        except Exception as e:
            raise ServerError(str(e)) from e
    def health(self): return self._request("GET","/health",auth=False)
    def regions(self): return self._request("GET","/regions")
    def region_datasets(self,region): return self._request("GET","/regions/"+urllib.parse.quote(region)+"/datasets")
    def layers(self,dataset): return self._request("GET","/datasets/"+urllib.parse.quote(dataset)+"/layers")
    def objects(self,dataset,bbox):
        return self._request("GET","/datasets/"+urllib.parse.quote(dataset)+"/objects?bbox="+urllib.parse.quote(bbox,safe=",.-")+"&limit=5000")
    def upload_group(self,payload): return self._request("POST","/admin/drawings/upload",payload)
    def revisions(self,region): return self._request("GET","/admin/drawings/"+urllib.parse.quote(region)+"/revisions")
