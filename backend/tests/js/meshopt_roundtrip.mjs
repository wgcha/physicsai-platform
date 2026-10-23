// V-C3F-8 왕복(Node): three 동봉 MeshoptDecoder·GLTFLoader로 Python 인코딩 결과를 푼다.
// 사용: node meshopt_roundtrip.mjs <three 패키지 폴더> <job.json>
//   job = {"buffers": [{"file", "count", "stride", "mode", "out"}], "glbs": [{"file", "out"}]}
//   buffers → decodeGltfBuffer 결과 바이트를 out에, glbs → GLTFLoader.parse 결과 요약 JSON을 out에 쓴다(오류는 out + ".err").
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [threeDir, jobPath] = process.argv.slice(2);
const url = (p) => pathToFileURL(join(threeDir, p)).href;
const { MeshoptDecoder } = await import(url('examples/jsm/libs/meshopt_decoder.module.js'));
const { GLTFLoader } = await import(url('examples/jsm/loaders/GLTFLoader.js'));
await MeshoptDecoder.ready;
const job = JSON.parse(readFileSync(jobPath, 'utf8'));

for (const j of job.buffers || []) {
  try {
    const src = new Uint8Array(readFileSync(j.file));
    const target = new Uint8Array(j.count * j.stride);
    MeshoptDecoder.decodeGltfBuffer(target, j.count, j.stride, src, j.mode, 'NONE');
    writeFileSync(j.out, target);
  } catch (e) {
    writeFileSync(j.out + '.err', String(e));
  }
}

const b64 = (a) => Buffer.from(a.buffer, a.byteOffset, a.byteLength).toString('base64');
for (const g of job.glbs || []) {
  try {
    const data = readFileSync(g.file);
    const ab = data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
    const loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    const gltf = await new Promise((res, rej) => loader.parse(ab, '', res, rej));
    let mesh = null;
    gltf.scene.traverse((o) => { if (o.isMesh && !mesh) mesh = o; });
    const geo = mesh.geometry;
    const pos = geo.getAttribute('position');
    const p = new Int16Array(pos.count * 3);
    for (let i = 0; i < pos.count; i++) {
      // 정규화 해제 전 정수값(InterleavedBufferAttribute: stride 8)
      const base = pos.isInterleavedBufferAttribute ? pos.data.array : pos.array;
      const stride = pos.isInterleavedBufferAttribute ? pos.data.stride : 3;
      const off = pos.isInterleavedBufferAttribute ? pos.offset : 0;
      for (let k = 0; k < 3; k++) p[i * 3 + k] = base[i * stride + off + k];
    }
    const attrs = {};
    for (const name of Object.keys(geo.attributes)) {
      if (name === 'position') continue;
      attrs[name] = b64(new Uint32Array(geo.getAttribute(name).array));
    }
    const out = {
      count: pos.count, normalized: pos.normalized, position: b64(p), attrs,
      index: b64(new Uint32Array(geo.index.array)), translation: mesh.position.toArray(), scale: mesh.scale.toArray(),
      hasNormal: !!geo.getAttribute('normal'), name: mesh.parent ? mesh.parent.name : null,
    };
    writeFileSync(g.out, JSON.stringify(out));
  } catch (e) {
    writeFileSync(g.out + '.err', String(e && e.stack || e));
  }
}
