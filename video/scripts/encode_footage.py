"""Encode the Blender PNG sequences (hardware/renders/frames/v2/<shot>/####.png) into video/public/footage/<shot>.mp4
with Remotion's bundled ffmpeg. Near-lossless H.264 so the Remotion render is the only real compression step.

    hub/.venv/Scripts/python.exe video/scripts/encode_footage.py [shot ...]
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRAMES = ROOT / "hardware" / "renders" / "frames" / "v2"
OUT = ROOT / "video" / "public" / "footage"


def main():
    shots = sys.argv[1:] or sorted(p.name for p in FRAMES.iterdir() if p.is_dir())
    OUT.mkdir(parents=True, exist_ok=True)
    for shot in shots:
        src = FRAMES / shot
        n = len(list(src.glob("*.png")))
        if not n:
            print("no frames for", shot)
            continue
        dst = OUT / f"{shot}.mp4"
        cmd = ["npx", "remotion", "ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-i", str(src / "%04d.png"),
               "-c:v", "libx264", "-crf", "12", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
        subprocess.run(cmd, check=True, cwd=ROOT / "video", shell=sys.platform == "win32")
        print(f"{shot}: {n} frames -> {dst}")


if __name__ == "__main__":
    main()
