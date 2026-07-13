"use client";

import {useParams} from "next/navigation";

import {SettingsPanel} from "@/components/SettingsPanel";

export default function SettingsPage() {
  const {workspace} = useParams<{workspace: string}>();
  return (
    <div className="stack">
      <header className="page-header"><div><p className="eyebrow">Workspace controls</p><h1>Settings</h1><p className="muted">Manage judge credentials and who can run evaluations.</p></div></header>
      <SettingsPanel workspaceId={workspace} />
    </div>
  );
}
