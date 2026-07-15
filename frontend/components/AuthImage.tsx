"use client";

import {useEffect, useState} from "react";

import {getToken} from "@/lib/api";

export function AuthImage({path, alt}: {path: string; alt: string}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let createdUrl: string | null = null;
    let cancelled = false;
    setObjectUrl(null);
    setFailed(false);
    fetch(path, {headers: {Authorization: `Bearer ${getToken() ?? ""}`}})
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        createdUrl = URL.createObjectURL(blob);
        setObjectUrl(createdUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [path]);

  if (failed) return <span className="muted">Image unavailable</span>;
  if (!objectUrl) return <span className="muted">Loading image…</span>;
  return <img src={objectUrl} alt={alt} style={{maxWidth: "100%"}} />;
}
