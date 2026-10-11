import os

from online_viewer import Api


class FakeClient:
    def __init__(self):
        self.access_token = "token"
        self.refresh_token = "refresh"

    def online_regions(self):
        return [
            {"id": "CMB_GN_HP", "name": "함평"},
            {"id": "CMB_GN_NJ", "name": "나주"},
        ]

    def online_layers(self, region):
        assert region == "CMB_GN_HP"
        return {
            "layers": [{"group_id": "FIBER", "layer": "F_CABLE"}],
            "bounds": {"west": 126.0, "south": 34.0, "east": 127.0, "north": 36.0},
        }


api = Api()
api.c = FakeClient()
api.user = {"level": 1}

regions = api.regions()
assert regions["ok"] is True
assert regions["count"] == 2
assert regions["items"][0]["id"] == "CMB_GN_HP"

selected = api.select("CMB_GN_HP")
assert selected["ok"] is True
assert selected["layers"][0]["group_id"] == "FIBER"

print("ONLINE_REGION_SELFTEST_OK")
