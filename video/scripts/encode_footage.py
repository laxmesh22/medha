"""Encode Blender PNG sequences into MP4s for the Remotion projects, with Remotion's bundled ffmpeg. Near-lossless
H.264 so the Remotion render is the only real compression step.

    hub/.venv/Scripts/python.exe video/scripts/encode_footage.py [shot ...]          film: frames/v2 -> public/footage
    hub/.venv/Scripts/python.exe video/scripts/encode_footage.py --guide [clip ...]  guide: frames/guide -> public/guide/footage

The guide also needs each clip's last frame as a still (held while the step text is read): --guide copies it to
public/guide/stills/<clip>.png, plus the stills of the two film shots it reuses (rail, reveal).
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDERS = ROOT / "hardware" / "renders" / "frames"
PUBLIC = ROOT / "video" / "public"
FILM_SHOTS_IN_GUIDE = ("rail", "reveal")


def encode(src: Path, dst: Path):
    pngs = sorted(src.glob("*.png"))
    if not pngs:
        print("no frames for", src.name)
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["npx", "remotion", "ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-start_number", pngs[0].stem,   # avatar shots keep their timeline frame numbers
           "-i", str(src / "%04d.png"),
           "-c:v", "libx264", "-crf", "12", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True, cwd=ROOT / "video", shell=sys.platform == "win32")
    print(f"{src.name}: {len(pngs)} frames -> {dst}")
    return pngs[-1]


def main():
    args = sys.argv[1:]
    guide = "--guide" in args
    args = [a for a in args if a != "--guide"]
    src_root = RENDERS / ("guide" if guide else "v2")
    out = PUBLIC / ("guide/footage" if guide else "footage")
    shots = args or sorted(p.name for p in src_root.iterdir() if p.is_dir())
    for shot in shots:
        last = encode(src_root / shot, out / f"{shot}.mp4")
        if guide and last:
            stills = PUBLIC / "guide" / "stills"
            stills.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(last, stills / f"{shot}.png")
    if guide:
        for shot in FILM_SHOTS_IN_GUIDE:
            pngs = sorted((RENDERS / "v2" / shot).glob("*.png"))
            if pngs:
                shutil.copyfile(pngs[-1], PUBLIC / "guide" / "stills" / f"{shot}.png")


if __name__ == "__main__":
    main()
