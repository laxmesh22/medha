# Jetson Orin Nano + RealSense D455f setup (Clinic Station)

Target: JetPack **6.2.x** (Ubuntu 22.04, Python 3.10), headless, Super mode. Budget ~2–3 h the first time.
Commands below are a guide. Check each step's output; versions move.

## 1. JetPack
```bash
cat /etc/nv_tegra_release          # R36.4.x = JetPack 6.2.x
```
* On JetPack 6.0/6.1: flash the JetPack 6.2 SD-card image with Balena Etcher (or use SDK Manager).
* On JetPack 5.x / a never-updated kit: do the **QSPI firmware update** in NVIDIA's *Initial Setup Guide for Jetson Orin
  Nano Developer Kit* first, then flash 6.2.
* An NVMe SSD is strongly recommended (TensorRT engine builds and logs are slow on microSD).

## 2. Power mode, headless, hostname
```bash
sudo nvpmodel -q --verbose         # list modes; pick the MAXN SUPER id
sudo nvpmodel -m <MAXN_SUPER_id>
sudo jetson_clocks                 # optional: pin clocks for stable latency during the demo
sudo systemctl set-default multi-user.target   # headless: frees ~1 GB RAM (reboot to apply)
sudo hostnamectl set-hostname physiobuddy      # UI at http://physiobuddy.local:8000 (avahi/mDNS)
```
Keep the fan unobstructed. Log `tegrastats` during a 60-minute run before the showcase.

## 3. librealsense with RSUSB backend + CUDA + Python bindings
```bash
sudo apt update && sudo apt install -y git cmake build-essential libssl-dev libusb-1.0-0-dev \
  libudev-dev pkg-config libgtk-3-dev python3-dev python3-pip python3-venv
git clone https://github.com/IntelRealSense/librealsense.git && cd librealsense
git checkout $(git describe --tags --abbrev=0)      # latest release tag
sudo ./scripts/setup_udev_rules.sh
mkdir build && cd build
cmake .. -DFORCE_RSUSB_BACKEND=ON -DBUILD_WITH_CUDA=ON -DBUILD_PYTHON_BINDINGS=ON \
  -DPYTHON_EXECUTABLE=$(which python3) -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_EXAMPLES=ON -DBUILD_GRAPHICAL_EXAMPLES=OFF
make -j$(nproc) && sudo make install
python3 -c "import pyrealsense2 as rs; print(rs.__version__)"
```
If the import fails, add the install dir to the path, e.g. `export PYTHONPATH=$PYTHONPATH:/usr/local/lib/python3.10/dist-packages`
(check where `make install` put `pyrealsense2*.so`). Plug the D455f into a **USB 3** port, then run `rs-enumerate-devices`.
It should report USB 3.x. Alternative route: JetsonHacks "Jetson Orin RealSense in 5 minutes" (JetPack 6 uses loadable modules,
no kernel rebuild).

## 4. Python environment
```bash
cd ~/medha/hub
python3 -m venv --system-site-packages .venv      # sees the system pyrealsense2
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]" rtmlib "opencv-contrib-python<5"
```
**onnxruntime-gpu:** install the JetPack 6 wheel from NVIDIA's Jetson AI Lab package index (see jetson-ai-lab.io for the
current JP6/CUDA index URL), e.g. `pip install onnxruntime-gpu --index-url <jp6 index>`. Then make sure the CPU-only
`onnxruntime` that rtmlib may pull in is **not** installed alongside it (`pip uninstall onnxruntime`). Check with:
```bash
python -c "import onnxruntime as ort; print(ort.get_available_providers())"   # expect CUDAExecutionProvider
```
If the Jetson wheels were built against NumPy 1.x, pin `pip install "numpy<2"`.

## 5. Models (offline at the venue)
Copy `hub/models/` from a laptop (`python -m physiobuddy_hub fetch-models`) or run `fetch-models` on the Jetson while online.

## 6. Run
```bash
python -m physiobuddy_hub devices                  # camera + gravity check (camera static on tripod!)
python -m physiobuddy_hub run --device cuda --debug-video --log
```
Build the UI on the laptop (`cd web && npm run build`) and copy `hub/physiobuddy_hub/api/static/` across, or install Node on the Jetson.

## 7. Autostart (for the showcase)
`/etc/systemd/system/physiobuddy.service`:
```ini
[Unit]
Description=Physio Buddy hub
After=network-online.target

[Service]
User=<user>
WorkingDirectory=/home/<user>/medha/hub
ExecStart=/home/<user>/medha/hub/.venv/bin/python -m physiobuddy_hub run --device cuda
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now physiobuddy
journalctl -u physiobuddy -f
```

## Next on Jetson (after the pipeline runs)
* ONNX Runtime **TensorRT execution provider** (FP16) for the pose model. The engine must be built on the Jetson itself.
* Measure: fps, `proc_ms` (shown in the UI header), glass-to-screen latency, RAM in `tegrastats`.
