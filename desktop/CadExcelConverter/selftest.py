import tempfile
from pathlib import Path

import ezdxf
from openpyxl import load_workbook

from converter import scan_layers, convert_selected_layers

def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dxf = root / "sample.dxf"
        xlsx = root / "sample.xlsx"

        doc = ezdxf.new("R2018")
        msp = doc.modelspace()

        pole_block = doc.blocks.new("Pole-Joint")
        pole_block.add_circle((0, 0), 1)
        msp.add_blockref(
            "Pole-Joint",
            (156215.0863507305, 174095.3802128593),
            dxfattribs={"layer": "CN_L_Pole_Pole-Joint"},
        )

        onu_block = doc.blocks.new("ONU")
        onu_block.add_circle((0, 0), 1)
        msp.add_blockref(
            "ONU",
            (156250.0, 174120.0),
            dxfattribs={"layer": "CN_C_ONU"},
        )

        msp.add_lwpolyline(
            [(156215.0, 174095.0), (156225.0, 174105.0), (156235.0, 174115.0)],
            dxfattribs={"layer": "CN_F_Cable_FOC"},
        )
        msp.add_lwpolyline(
            [(156240.0, 174100.0), (156250.0, 174110.0)],
            dxfattribs={"layer": "CN_C_Cable_500F"},
        )
        msp.add_text("TEST", dxfattribs={"layer": "ANNO"}).set_placement((156260.0, 174130.0))
        doc.saveas(dxf)

        layers = scan_layers(str(dxf))
        names = {x.name: x for x in layers}
        assert "CN_L_Pole_Pole-Joint" in names
        assert names["CN_F_Cable_FOC"].count == 1
        assert "LWPOLYLINE" in names["CN_F_Cable_FOC"].types

        selected = ["CN_L_Pole_Pole-Joint", "CN_F_Cable_FOC", "ANNO"]
        stats = convert_selected_layers(str(dxf), str(xlsx), selected, 5174)
        assert stats.layers == 3, stats
        assert stats.entities == 3, stats
        assert stats.rows == 5, stats

        wb = load_workbook(xlsx, data_only=True)
        assert wb.sheetnames[0] == "LAYER_INDEX"
        assert "INFO" in wb.sheetnames

        idx = wb["LAYER_INDEX"]
        mapping = {idx.cell(r,1).value: idx.cell(r,2).value for r in range(2, idx.max_row+1)}
        assert set(mapping) == set(selected)

        pole_ws = wb[mapping["CN_L_Pole_Pole-Joint"]]
        lon = pole_ws.cell(2, 7).value
        lat = pole_ws.cell(2, 8).value
        assert abs(lon - 126.5208008) < 0.0001, lon
        assert abs(lat - 35.0649176) < 0.0001, lat

        fiber_ws = wb[mapping["CN_F_Cable_FOC"]]
        assert fiber_ws.max_row == 4  # header + 3 vertices
        assert fiber_ws.cell(2,1).value == "LWPOLYLINE"

        anno_ws = wb[mapping["ANNO"]]
        assert anno_ws.cell(2,10).value == "TEST"

        print("SELFTEST OK")

if __name__ == "__main__":
    main()
