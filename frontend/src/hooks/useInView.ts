// 칸이 화면(뷰포트)에 보이는가 — IntersectionObserver threshold 0. 지원하지 않는 환경(구형·jsdom)은 항상 보임으로 본다.
// 결과 3D 컨투어 자동 요청의 "칸이 보임 = 엶"(contour3d-default C3D-3) 판정에 쓴다. 콜백 ref(el 변경 대응) 형태로 돌려준다.
import { useEffect, useState } from "react";

export function useInView(): [boolean, (el: Element | null) => void] {
  const [el, setEl] = useState<Element | null>(null);
  const [seen, setSeen] = useState(typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => {
      const last = entries[entries.length - 1];
      if (last) setSeen(last.isIntersecting);
    }, { threshold: 0 });
    io.observe(el);
    return () => io.disconnect();
  }, [el]);
  return [seen, setEl];
}
