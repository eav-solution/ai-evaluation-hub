import type {ReactNode} from "react";

import {WorkspaceNav} from "@/components/WorkspaceNav";

export default async function WorkspaceLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{workspace: string}>;
}) {
  const {workspace} = await params;
  return (
    <div className="app-shell">
      <WorkspaceNav workspaceId={workspace} />
      <main className="workspace-main">{children}</main>
    </div>
  );
}
