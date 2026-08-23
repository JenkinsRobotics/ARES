import { FolderOpen, Plus, Trash2, RefreshCw, CheckCircle2, AlertCircle } from "lucide-react";
import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ToggleSwitch } from "@/components/ui/toggle-switch";

import type { RAGSource, RAGSourcesConfig, RAGScanResult } from "@/shared/ares-api";
import { getRAGSources, setRAGSources, scanRAGSources } from "@/shared/ares-api";

export function RAGSourcesSection() {
  const [config, setConfig] = useState<RAGSourcesConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanResults, setScanResults] = useState<RAGScanResult[] | null>(null);
  const [newPath, setNewPath] = useState("");

  const loadConfig = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getRAGSources();
      setConfig(data);
      setError(null);
    } catch (e) {
      setError(`Failed to load RAG sources: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useState(() => {
    void loadConfig();
  });

  const updateConfig = async (patch: Partial<RAGSourcesConfig>) => {
    if (!config) return;
    try {
      setBusy("saving");
      const next = { ...config, ...patch };
      await setRAGSources(next);
      setConfig(next);
    } catch (e) {
      setError(`Failed to save: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const addSource = async () => {
    if (!newPath.trim() || !config) return;
    const source: RAGSource = {
      path: newPath.trim(),
      include: ["*.md", "*.txt", "*.json", "*.yaml", "*.yml", "*.toml"],
      index: ["fts", "vector"],
    };
    await updateConfig({ sources: [...config.sources, source] });
    setNewPath("");
  };

  const removeSource = async (index: number) => {
    if (!config) return;
    const next = config.sources.filter((_, i) => i !== index);
    await updateConfig({ sources: next });
  };

  const doScan = async () => {
    if (!config?.enabled) {
      setError("Enable RAG sources first");
      return;
    }
    try {
      setScanning(true);
      setScanResults(null);
      const result = await scanRAGSources();
      setScanResults(result.results || []);
    } catch (e) {
      setError(`Scan failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setScanning(false);
    }
  };

  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading RAG sources…</p>;
  }

  if (!config) {
    return <p className="text-sm text-muted-foreground">No RAG configuration found.</p>;
  }

  return (
    <div className="grid gap-6">
      <div>
        <h3 className="text-lg font-semibold">Document Sources (RAG)</h3>
        <p className="text-sm text-muted-foreground">
          Index your documents for semantic search. Supports .md, .txt, .json, .yaml, .yml, .toml.
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Settings</CardTitle>
          <CardDescription>Enable/disable indexing and embedding.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex items-center justify-between">
            <Label htmlFor="rag-enabled">Enable RAG indexing</Label>
            <ToggleSwitch
              id="rag-enabled"
              checked={config.enabled}
              onCheckedChange={(v) => void updateConfig({ enabled: v === true })}
              disabled={busy === "saving"}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="rag-model">Embedding model</Label>
            <Input
              id="rag-model"
              value={config.embedding_model || "nomic-embed-text"}
              onChange={(e) => void updateConfig({ embedding_model: e.target.value })}
              disabled={busy === "saving"}
            />
            <p className="text-xs text-muted-foreground">Ollama-compatible endpoint. Must be installed.</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base">Sources</CardTitle>
              <CardDescription>Folders to index for search.</CardDescription>
            </div>
            <Button
              size="sm"
              onClick={doScan}
              disabled={scanning || !config.enabled}
              className="gap-2"
            >
              <RefreshCw className={`size-4 ${scanning ? "animate-spin" : ""}`} />
              {scanning ? "Scanning…" : "Scan Now"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex gap-2">
            <Input
              placeholder="/path/to/folder or ~/Notes"
              value={newPath}
              onChange={(e) => setNewPath(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void addSource()}
            />
            <Button onClick={addSource} size="sm" className="gap-2">
              <Plus className="size-4" />
              Add
            </Button>
          </div>

          {config.sources.length === 0 ? (
            <p className="text-sm text-muted-foreground">No sources configured. Add a folder path above.</p>
          ) : (
            <div className="grid gap-2">
              {config.sources.map((source, idx) => (
                <div key={source.path + idx} className="flex items-center justify-between rounded-md border p-3">
                  <div className="grid gap-1">
                    <div className="flex items-center gap-2">
                      <FolderOpen className="size-4 text-muted-foreground" />
                      <code className="text-sm">{source.path}</code>
                    </div>
                    <div className="flex gap-2">
                      {source.include && (
                        <Badge variant="outline" className="text-xs">
                          {source.include.length} patterns
                        </Badge>
                      )}
                      {source.index?.includes("vector") && (
                        <Badge variant="secondary" className="text-xs">
                          Vector
                        </Badge>
                      )}
                      {source.index?.includes("fts") && (
                        <Badge variant="outline" className="text-xs">
                          Keyword
                        </Badge>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void removeSource(idx)}
                    className="text-destructive hover:text-destructive"
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {scanResults && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Scan Results</CardTitle>
            <CardDescription>Last scan results.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2">
            {scanResults.map((r) => (
              <div key={r.path} className="flex items-center justify-between rounded-md border p-2">
                <div className="flex items-center gap-2">
                  {r.status === "scanned" ? (
                    <CheckCircle2 className="size-4 text-green-600" />
                  ) : (
                    <AlertCircle className="size-4 text-destructive" />
                  )}
                  <code className="text-sm">{r.path}</code>
                </div>
                <div className="flex items-center gap-3 text-sm">
                  {r.files !== undefined && <Badge variant="outline">{r.files} files</Badge>}
                  {r.error && <span className="text-destructive">{r.error}</span>}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <p className="text-xs text-muted-foreground">
        Tip: Scope large volumes (e.g., NAS) to specific folders. Only .md/.txt/.json/.yaml/.yml/.toml are indexed — no PDF support yet.
      </p>
    </div>
  );
}
