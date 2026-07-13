"use client";

import {useParams} from "next/navigation";

import {GenerateWizard} from "@/components/GenerateWizard";

export default function GenerateDatasetPage() {
  const {workspace} = useParams<{workspace: string}>();
  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">Dataset generation</p>
          <h1>Generate from documents</h1>
          <p className="muted">Upload source documents and let an LLM draft grounded question-answer records.</p>
        </div>
      </header>
      <GenerateWizard workspaceId={workspace} />
    </div>
  );
}
