const base = "http://127.0.0.1:8765";
const [viewerResponse, sceneResponse] = await Promise.all([
  fetch(`${base}/viewer.js`), fetch(`${base}/scene.json`),
]);
if (!viewerResponse.ok || !sceneResponse.ok) throw new Error("served artifacts unavailable");
const viewer = await viewerResponse.text();
const manifest = await sceneResponse.json();
const start = viewer.indexOf("function applyContractLighting");
const end = viewer.indexOf("\napplyContractLighting(scene", start);
if (start < 0 || end < 0) throw new Error("served lighting runtime function unavailable");
const source = viewer.slice(start, end);
class Color {
  constructor(value = null) { this.value = value instanceof Color ? value.value : value; }
  set(value) { this.value = value; }
}
class AmbientLight {
  constructor(color = new Color(), intensity = undefined) {
    this.color = color; this.intensity = intensity; this.userData = {};
  }
}
class PointLight {
  constructor(color = new Color(), intensity = undefined) {
    this.color = color; this.intensity = intensity; this.userData = {};
    this.position = {set: (x, y, z) => { this.xyz = {x, y, z}; }};
    this.shadow = {autoUpdate: null}; this.castShadow = null; this.name = "";
  }
}
const THREE = {Color, AmbientLight, PointLight};
const fail = message => { throw new Error(message); };
const apply = new Function("THREE", "fail", `${source}; return applyContractLighting;`)(THREE, fail);
const scene = {lights: [], add(light) { this.lights.push(light); }};
const renderer = {shadowMap: {enabled: false}};
apply(scene, renderer, manifest.lighting, "5");
if (!renderer.shadowMap.enabled) throw new Error("v5 shadow map was not enabled");
if (scene.lights.length !== manifest.lighting.lights.length + 1) throw new Error("light count drift");
if (scene.lights[0].color.value !== manifest.lighting.ambient_color
    || scene.lights[0].intensity !== manifest.lighting.ambient_intensity) throw new Error("ambient drift");
manifest.lighting.lights.forEach((expected, index) => {
  const actual = scene.lights[index + 1];
  if (actual.name !== expected.light_id || actual.color.value !== expected.color
      || actual.intensity !== expected.intensity || JSON.stringify(actual.xyz) !== JSON.stringify(expected.position)
      || actual.userData.temperature !== expected.temperature
      || actual.userData.contractLighting.temperature_kelvin !== expected.temperature
      || actual.castShadow !== expected.cast_shadows
      || actual.shadow.autoUpdate !== expected.cast_shadows) throw new Error(`fixture drift: ${expected.light_id}`);
});
const legacyScene = {lights: [], add(light) { this.lights.push(light); }};
const legacyRenderer = {shadowMap: {enabled: false}};
apply(legacyScene, legacyRenderer, manifest.lighting, "4");
if (legacyRenderer.shadowMap.enabled) throw new Error("v5 shadows leaked into retained v4");
console.log(`served-lighting-smoke: ${manifest.contract_hash} · ${scene.lights.length - 1} fixtures exact`);