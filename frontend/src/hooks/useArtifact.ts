import { useEffect, useState } from "react";
import { api } from "../api";

export function useArtifactUrl(id: string | null | undefined) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!id) return;
    let alive = true;
    let obj: string | null = null;
    api
      .artifactBlob(id)
      .then((b) => {
        if (!alive) return;
        obj = URL.createObjectURL(b);
        setUrl(obj);
      })
      .catch(() => setUrl(null));
    return () => {
      alive = false;
      if (obj) URL.revokeObjectURL(obj);
    };
  }, [id]);
  return url;
}

export function useArtifactJson<T>(id: string | null | undefined): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    setData(null);
    if (!id) return;
    let alive = true;
    api
      .artifactBlob(id)
      .then((b) => b.text())
      .then((t) => alive && setData(JSON.parse(t) as T))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [id]);
  return data;
}


/** 산출물 본문 텍스트 */
export function useArtifactText(id: string | null | undefined): string | null {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    setText(null);
    if (!id) return;
    let alive = true;
    api
      .artifactBlob(id)
      .then((b) => b.text())
      .then((t) => alive && setText(t))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [id]);
  return text;
}
