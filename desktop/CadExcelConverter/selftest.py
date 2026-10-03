import tempfile
from pathlib import Path

import ezdxf
from openpyxl import load_workbook

from converter import convert_file, list_layers

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
        doc.saveas(dxf)

        layers = dict(list_layers(str(dxf)))
        assert layers["CN_L_Pole_Pole-Joint"] == 1
        assert layers["CN_C_ONU"] == 1
        assert layers["CN_F_Cable_FOC"] == 1
        assert layers["CN_C_Cable_500F"] == 1

        chosen = ["CN_L_Pole_Pole-Joint", "CN_F_Cable_FOC"]
        stats = convert_file(str(dxf), str(xlsx), 5174, selected_layers=chosen)
        assert stats.layers == 2, stats
        assert stats.entities == 2, stats
        assert stats.rows == 4, stats

        wb = load_workbook(xlsx, data_only=True)
        assert "INFO" in wb.sheetnames
        assert "LAYER_INDEX" in wb.sheetnames
        assert "CN_L_Pole_Pole-Joint" in wb.sheetnames
        assert "CN_F_Cable_FOC" in wb.sheetnames
        assert "CN_C_ONU" not in wb.sheetnames

        ws = wb["CN_L_Pole_Pole-Joint"]
        lon = ws.cell(2, 9).value
        lat = ws.cell(2, 10).value
        assert abs(lon - 126.5208008) < 0.0001, lon
        assert abs(lat - 35.0649176) < 0.0001, lat

        line_ws = wb["CN_F_Cable_FOC"]
        assert line_ws.max_row == 4
        assert line_ws.cell(2, 6).value == 1
        assert line_ws.cell(4, 6).value == 3

        print("SELFTEST OK")

if __name__ == "__main__":
    main()
