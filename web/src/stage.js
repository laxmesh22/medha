import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';

// Studio stage: ACES tone mapping, offline room environment lighting, soft shadow catcher,
// CSS2D labels (techniques from the CodePen anatomy viewer, adapted to run with no CDN/HDR file).
export class Stage {
  constructor(container) {
    this.container = container;
    // preserveDrawingBuffer: screenshots / screen recordings of the station capture the 3D view reliably
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance', preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    container.appendChild(this.renderer.domElement);

    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = 'labels';
    container.appendChild(this.labels.domElement);

    this.scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

    this.camera = new THREE.PerspectiveCamera(32, 1, 0.05, 50);
    this.camera.position.set(2.3, 0.35, 2.6); // oblique: flexion (sagittal) and abduction arcs both readable
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, -0.35, 0);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.minDistance = 1.2;
    this.controls.maxDistance = 7;
    this.controls.maxPolarAngle = Math.PI * 0.55;

    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1.5, 3, 2.5);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.bias = -0.001;
    key.shadow.camera.left = key.shadow.camera.bottom = -1.5;
    key.shadow.camera.right = key.shadow.camera.top = 1.5;
    this.scene.add(key);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 0.6));

    this.floor = new THREE.Mesh(
      new THREE.PlaneGeometry(20, 20).rotateX(-Math.PI / 2),
      new THREE.ShadowMaterial({ opacity: 0.25 }),
    );
    this.floor.receiveShadow = true;
    this.floor.position.y = -1.45;
    this.scene.add(this.floor);

    this.grid = new THREE.GridHelper(6, 24, 0x3a4a5c, 0x243140);
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.5;
    this.grid.position.y = -1.449;
    this.scene.add(this.grid);

    this.onFrame = [];
    this.timer = new THREE.Timer();
    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
    this.renderer.setAnimationLoop((now) => {
      this.timer.update(now);
      const dt = Math.min(this.timer.getDelta(), 0.1);
      for (const f of this.onFrame) f(dt);
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
      this.labels.render(this.scene, this.camera);
    });
  }

  setFloorY(y) {
    this.floor.position.y = y;
    this.grid.position.y = y + 0.001;
  }

  resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }
}
