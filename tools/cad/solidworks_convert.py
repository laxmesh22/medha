"""Convert the CadQuery STEP parts into native SolidWorks parts (.SLDPRT) through the SolidWorks COM API.

    tools/cad/.venv/Scripts/python.exe tools/cad/solidworks_convert.py hardware/cad/out/step hardware/cad/out/solidworks

Requires a licensed SolidWorks install on this PC. SolidWorks is started invisibly and closed afterwards. Only single
parts are converted (assemblies open fine as STEP in SolidWorks and Fusion 360: File > Open > *.step).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pythoncom
import win32com.client
from win32com.client import VARIANT

SW_DOC_PART = 1


def main():
    src, dst = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    dst.mkdir(parents=True, exist_ok=True)
    pythoncom.CoInitialize()
    t0 = time.time()
    sw = win32com.client.Dispatch("SldWorks.Application")
    sw.Visible = False
    rev = sw.RevisionNumber() if callable(sw.RevisionNumber) else sw.RevisionNumber
    print(f"SolidWorks {rev} started in {time.time() - t0:.0f} s", flush=True)
    done, failed = [], []
    for step in sorted(src.glob("*.step")):
        if step.stem.startswith("unit_"):
            continue
        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        imp = sw.GetImportFileData(str(step))
        model = sw.LoadFile4(str(step), "r", imp, errors)
        if model is None:
            failed.append(f"{step.name} (load error {errors.value})")
            continue
        out = dst / f"{step.stem}.SLDPRT"
        err = model.SaveAs3(str(out), 0, 1)          # 0 = current version, 1 = silent; returns 0 on success
        sw.CloseDoc(model.GetTitle() if callable(model.GetTitle) else model.GetTitle)
        ok = err == 0 and out.exists()
        (done if ok else failed).append(out.name if ok else f"{step.name} (save error {err})")
        print("  ", "ok" if ok else "FAILED", out.name, flush=True)
    sw.ExitApp()
    print(f"converted {len(done)}, failed {len(failed)}: {failed}")


if __name__ == "__main__":
    main()
