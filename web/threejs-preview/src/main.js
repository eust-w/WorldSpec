import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const status = document.querySelector("#status");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.1;
document.body.append(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1117);
scene.add(new THREE.HemisphereLight(0xcfe8ff, 0x18212c, 2.2));
const key = new THREE.DirectionalLight(0xffffff, 3);
key.position.set(3, 5, 4);
scene.add(key);

const camera = new THREE.PerspectiveCamera(
  48,
  window.innerWidth / window.innerHeight,
  0.01,
  1000,
);

const grid = new THREE.GridHelper(10, 20, 0x30445b, 0x1d2938);
scene.add(grid);

function render() {
  renderer.render(scene, camera);
}

function fitCamera(object) {
  const bounds = new THREE.Box3().setFromObject(object);
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const radius = Math.max(size.length() * 0.75, 0.5);
  camera.position.copy(center).add(new THREE.Vector3(radius, radius * 0.8, radius * 1.4));
  camera.lookAt(center);
  camera.near = Math.max(radius / 1000, 0.001);
  camera.far = Math.max(radius * 20, 20);
  camera.updateProjectionMatrix();
  return { center: center.toArray(), size: size.toArray() };
}

const parameters = new URLSearchParams(window.location.search);
const bundle = parameters.get("scene") || "/bundle/scene.glb";
new GLTFLoader().load(
  bundle,
  (gltf) => {
    scene.add(gltf.scene);
    const bounds = fitCamera(gltf.scene);
    render();
    const stableIds = [];
    gltf.scene.traverse((object) => {
      if (object.userData.worldspecId) stableIds.push(object.userData.worldspecId);
    });
    window.__WORLDSPEC_PREVIEW__ = {
      ready: true,
      scene: bundle,
      nodes: gltf.scene.children.length,
      stableIds,
      bounds,
      renderer: renderer.getContext().getParameter(renderer.getContext().VERSION),
    };
    status.textContent = `ready · ${stableIds.length} stable ID(s)`;
    status.dataset.state = "ready";
  },
  undefined,
  (error) => {
    window.__WORLDSPEC_PREVIEW__ = {
      ready: false,
      error: String(error),
    };
    status.textContent = `failed · ${String(error)}`;
    status.dataset.state = "failed";
  },
);

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  render();
});
