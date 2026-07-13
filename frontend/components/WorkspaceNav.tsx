"use client";

import Link from "next/link";
import {usePathname, useRouter} from "next/navigation";

import {clearToken} from "@/lib/api";

const items = [
  ["Datasets", "datasets"],
  ["Runs", "runs"],
  ["Model Benchmarks", "model-benchmarks"],
  ["Settings", "settings"],
] as const;

export function WorkspaceNav({workspaceId}: {workspaceId: string}) {
  const path = usePathname();
  const router = useRouter();
  return (
    <aside className="sidebar">
      <Link className="brand" href={`/w/${workspaceId}/datasets`}>
        <span className="brand-mark">E</span>
        <span>EvalHub</span>
      </Link>
      <nav>
        {items.map(([label, segment]) => {
          const href = `/w/${workspaceId}/${segment}`;
          const active = path.startsWith(href);
          return (
            <Link className={active ? "active" : ""} href={href} key={segment} aria-current={active ? "page" : undefined}>
              {label}
            </Link>
          );
        })}
      </nav>
      <button
        className="ghost logout"
        onClick={() => {
          clearToken();
          router.push("/login");
        }}
      >
        Sign out
      </button>
    </aside>
  );
}
