from pathlib import Path
import tempfile

from essenpoly_recovery import recover_essenpoly_polylines


def main():
    sample = """  0\nSECTION\n  2\nENTITIES\n  0\nESSENPOLY\n  5\nABC1\n100\nAcDbEntity\n  8\nCN_F_Cable_FOC\n300\nCABLE-A\n101\nEmbedded Object\n100\nAcDbEntity\n  8\nCN_F_Cable_FOC\n100\nAcDbPolyline\n 90\n        3\n 70\n     0\n 10\n100.0\n 20\n200.0\n 10\n110.0\n 20\n205.0\n 10\n120.0\n 20\n210.0\n  0\nENDSEC\n  0\nEOF\n"""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sample.dxf"
        path.write_text(sample, encoding="utf-8")
        rows = recover_essenpoly_polylines(path)
        assert len(rows) == 1, rows
        row = rows[0]
        assert row["handle"] == "ABC1", row
        assert row["layer"] == "CN_F_Cable_FOC", row
        assert row["points"] == [(100.0, 200.0), (110.0, 205.0), (120.0, 210.0)], row
        assert row["attributes"]["ESSEN_300"] == "CABLE-A", row
    print("ESSENPOLY recovery self-test OK")


if __name__ == "__main__":
    main()
