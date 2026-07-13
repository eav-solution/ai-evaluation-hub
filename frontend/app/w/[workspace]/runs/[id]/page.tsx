"use client";

import {useParams} from "next/navigation";

import {RunReport} from "@/components/RunReport";

export default function ReportPage() {
  const {workspace, id} = useParams<{workspace: string; id: string}>();
  return <RunReport workspaceId={workspace} runId={id} />;
}
