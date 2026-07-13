"use client";

import {FormEvent, useEffect, useState} from "react";

import {api} from "@/lib/api";
import type {ConnectionType, ProviderConnection} from "@/lib/types";

type Member = {email: string; role: string};

const TYPE_LABELS: Record<ConnectionType, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  openai_compatible: "OpenAI-compatible",
};

export function SettingsPanel({workspaceId}: {workspaceId: string}) {
  const [connections, setConnections] = useState<ProviderConnection[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState("");

  const [connectionType, setConnectionType] = useState<ConnectionType>("openai");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  const isCustom = connectionType === "openai_compatible";

  async function refresh() {
    try {
      const [nextConnections, nextMembers] = await Promise.all([
        api<ProviderConnection[]>(`/api/workspaces/${workspaceId}/provider-connections`),
        api<Member[]>(`/api/workspaces/${workspaceId}/members`),
      ]);
      setConnections(nextConnections);
      setMembers(nextMembers);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load settings");
    }
  }

  useEffect(() => {
    refresh();
  }, [workspaceId]);

  async function saveConnection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setFormError("");
    try {
      const body = isCustom
        ? {
            connection_type: connectionType,
            name,
            base_url: baseUrl,
            api_key: apiKey || undefined,
          }
        : {connection_type: connectionType, api_key: apiKey};
      await api(`/api/workspaces/${workspaceId}/provider-connections`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setName("");
      setBaseUrl("");
      setApiKey("");
      refresh();
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : "Could not save connection");
    } finally {
      setBusy(false);
    }
  }

  async function addMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api(`/api/workspaces/${workspaceId}/members`, {
      method: "POST",
      body: JSON.stringify({email: form.get("email"), role: form.get("role")}),
    });
    event.currentTarget.reset();
    refresh();
  }

  return (
    <div className="settings-grid">
      {error && <p className="notice error">{error}</p>}
      <section className="panel">
        <p className="step">Judge &amp; generator providers</p>
        <h2>Provider connections</h2>
        <p className="muted">Keys are encrypted before they reach persistent storage.</p>
        <div className="item-list">
          {connections.map((connection) => (
            <div className="list-row" key={connection.id}>
              <span>
                <strong>{connection.name}</strong>
                <small>
                  {TYPE_LABELS[connection.connection_type]}
                  {connection.base_url ? ` · ${connection.base_url}` : ""}
                  {connection.has_key ? ` · key ${connection.key_hint}` : " · no key"}
                </small>
              </span>
              <button
                className="ghost"
                onClick={async () => {
                  await api(
                    `/api/workspaces/${workspaceId}/provider-connections/${connection.id}`,
                    {method: "DELETE"},
                  );
                  refresh();
                }}
              >
                Remove
              </button>
            </div>
          ))}
          {!connections.length && <p className="empty">No connections yet.</p>}
        </div>

        <form className="stack" onSubmit={saveConnection}>
          <label>
            Connection type
            <select
              value={connectionType}
              onChange={(event) => setConnectionType(event.target.value as ConnectionType)}
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="openai_compatible">OpenAI-compatible</option>
            </select>
          </label>
          {isCustom && (
            <>
              <input
                placeholder="Connection name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
              <input
                placeholder="Base URL (e.g. http://localhost:11434/v1)"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                required
              />
              <p className="muted">
                From a Docker deployment, reach a service on the host via{" "}
                <code>http://host.docker.internal:11434/v1</code>, not{" "}
                <code>localhost</code>.
              </p>
              <input
                type="password"
                placeholder="API key (optional)"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
              />
            </>
          )}
          {!isCustom && (
            <input
              type="password"
              placeholder="API key"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              required
              minLength={4}
            />
          )}
          {formError && <p className="notice error">{formError}</p>}
          <button className="primary" disabled={busy}>
            {busy ? "Verifying…" : "Save connection"}
          </button>
        </form>
      </section>

      <section className="panel">
        <p className="step">Workspace access</p>
        <h2>Members</h2>
        <div className="item-list">
          {members.map((member) => (
            <div className="list-row" key={member.email}>
              <span><strong>{member.email}</strong><small>{member.role}</small></span>
            </div>
          ))}
        </div>
        <form className="inline-form" onSubmit={addMember}>
          <input name="email" type="email" placeholder="Existing user email" required />
          <select name="role"><option value="member">Member</option><option value="owner">Owner</option></select>
          <button className="primary">Add member</button>
        </form>
      </section>
    </div>
  );
}
