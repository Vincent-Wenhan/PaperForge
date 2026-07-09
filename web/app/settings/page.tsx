"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Settings {
  llm_provider?: string;
  orchestrator_model?: string;
  composer_model?: string;
  planner_model?: string;
  parser_model?: string;
  generator_model?: string;
  verifier_model?: string;
  docker_available?: boolean;
  sandbox_base_port?: number;
  max_iterations?: number;
  llm_max_retries?: number;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setSettings(s as Settings);
        setError(null);
      })
      .catch((err) => setError(err.message || "Failed to load settings"));
  }, []);

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center text-destructive">
        {error}
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="flex h-screen items-center justify-center text-muted-foreground">
        Loading settings...
      </div>
    );
  }

  return (
    <div className="min-h-screen p-6 max-w-2xl mx-auto">
      <h1 className="text-2xl font-semibold mb-6">Settings</h1>

      <section className="mb-8">
        <h2 className="text-lg font-medium mb-3">LLM Provider</h2>
        <dl className="divide-y divide-border border border-border rounded">
          <SettingRow label="Provider" value={settings.llm_provider} />
          <SettingRow label="Orchestrator Model" value={settings.orchestrator_model} />
          <SettingRow label="Parser Model" value={settings.parser_model} />
          <SettingRow label="Composer Model" value={settings.composer_model} />
          <SettingRow label="Planner Model" value={settings.planner_model} />
          <SettingRow label="Generator Model" value={settings.generator_model} />
          <SettingRow label="Verifier Model" value={settings.verifier_model} />
        </dl>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-medium mb-3">Sandbox</h2>
        <dl className="divide-y divide-border border border-border rounded">
          <SettingRow
            label="Docker Available"
            value={settings.docker_available ? "Yes" : "No"}
          />
          <SettingRow
            label="Base Port"
            value={settings.sandbox_base_port?.toString()}
          />
        </dl>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-medium mb-3">Orchestrator</h2>
        <dl className="divide-y divide-border border border-border rounded">
          <SettingRow
            label="Max Iterations"
            value={settings.max_iterations?.toString()}
          />
          <SettingRow
            label="LLM Max Retries"
            value={settings.llm_max_retries?.toString()}
          />
        </dl>
      </section>
    </div>
  );
}

function SettingRow({ label, value }: { label: string; value?: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-3">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{value || "—"}</dd>
    </div>
  );
}
