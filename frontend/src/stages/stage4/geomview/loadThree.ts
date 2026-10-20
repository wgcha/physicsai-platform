// three.js 장면 모듈을 3D 패널을 열 때만 적재한다(동적 import → 별도 청크, geometry-view.md §7.1). 한 번 받은 모듈은 재사용.
type ThreeMod = typeof import("./threeScene");
let mod: Promise<ThreeMod> | null = null;

export function loadThree(): Promise<ThreeMod> {
  mod ??= import("./threeScene").catch((e) => {
    mod = null;
    throw e;
  });
  return mod;
}
