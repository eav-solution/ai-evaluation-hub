"use client";

import {useParams} from "next/navigation";

import {RunWizard} from "@/components/RunWizard";

export default function NewRunPage() {
  const {workspace} = useParams<{workspace: string}>();
  return (
    <div className="stack">
      <header className="page-header"><div><p className="eyebrow">New benchmark</p><h1>Build an evaluation</h1><p className="muted">The wizard only offers metrics your dataset can support.</p></div></header>
      <RunWizard workspaceId={workspace} />
    </div>
  );
}
