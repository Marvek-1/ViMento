import i18n from "@/i18n";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Database, KeyRound, Loader2, MessageSquareMore, Play, RefreshCw, RotateCcw, Save, Server, SlidersHorizontal, Square } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { api, isAuthRequiredError, type ChannelRuntimeStatus, type DataSourceSettings, type LLMProviderOption, type LLMSettings } from "@/lib/api";
import { getApiAuthKey, setApiAuthKey } from "@/lib/apiAuth";
import {
  checkNeonConnection,
  getStoredNeonJWT,
  setStoredNeonJWT,
  clearStoredNeonJWT,
  NEON_APP_NAME,
  NEON_DATA_API_URL,
  NEON_AUTH_URL,
  NEON_JWKS_URL,
} from "@/lib/neon";

interface LLMFormState {
  provider: string;
  model_name: string;
  base_url: string;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort: string;
}

const fieldClass = "glass-input text-sm disabled:cursor-not-allowed disabled:opacity-60";
const selectFieldClass = "glass-select text-sm disabled:cursor-not-allowed disabled:opacity-60";
const labelClass = "text-sm font-medium";
const hintClass = "text-xs text-muted-foreground";
const cardClass = "glass-surface rounded-2xl p-5";
const primaryBtnClass = "glass-btn glass-btn--primary disabled:cursor-not-allowed disabled:opacity-70";
const ghostBtnClass = "glass-btn disabled:cursor-not-allowed disabled:opacity-60";

function toForm(settings: LLMSettings): LLMFormState {
  return {
    provider: settings.provider,
    model_name: settings.model_name,
    base_url: settings.base_url,
    temperature: settings.temperature,
    timeout_seconds: settings.timeout_seconds,
    max_retries: settings.max_retries,
    reasoning_effort: settings.reasoning_effort || "",
  };
}

export function Settings() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [dataSettings, setDataSettings] = useState<DataSourceSettings | null>(null);
  const [channelStatus, setChannelStatus] = useState<ChannelRuntimeStatus | null>(null);
  const [form, setForm] = useState<LLMFormState | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [localApiKey, setLocalApiKeyState] = useState(() => getApiAuthKey());
  const [clearApiKey, setClearApiKey] = useState(false);
  const [binanceApiKey, setBinanceApiKey] = useState("");
  const [binanceApiSecret, setBinanceApiSecret] = useState("");
  const [clearBinanceKey, setClearBinanceKey] = useState(false);

  const [okxApiKey, setOkxApiKey] = useState("");
  const [okxApiSecret, setOkxApiSecret] = useState("");
  const [okxPassphrase, setOkxPassphrase] = useState("");
  const [clearOkxKey, setClearOkxKey] = useState(false);

  const [bybitApiKey, setBybitApiKey] = useState("");
  const [bybitApiSecret, setBybitApiSecret] = useState("");
  const [clearBybitKey, setClearBybitKey] = useState(false);

  const [gateioApiKey, setGateioApiKey] = useState("");
  const [gateioApiSecret, setGateioApiSecret] = useState("");
  const [clearGateioKey, setClearGateioKey] = useState(false);

  const [activeExchangeTab, setActiveExchangeTab] = useState<"binance" | "okx" | "bybit" | "gate">("okx");
  const [neonJwt, setNeonJwt] = useState(() => getStoredNeonJWT() || "");
  const [testingNeon, setTestingNeon] = useState(false);
  const [neonStatus, setNeonStatus] = useState<{
    tested: boolean;
    connected: boolean;
    status: string;
    hasToken: boolean;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dataSaving, setDataSaving] = useState(false);
  const [channelRefreshing, setChannelRefreshing] = useState(false);
  const [channelAction, setChannelAction] = useState<"start" | "stop" | null>(null);
  const [settingsLoadError, setSettingsLoadError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;

    Promise.allSettled([
      api.getLLMSettings(),
      api.getDataSourceSettings(),
      api.getChannelStatus(),
    ])
      .then(([llmResult, dataSourceResult, channelResult]) => {
        if (!alive) return;

        if (llmResult.status === "fulfilled") {
          setSettings(llmResult.value);
          setForm(toForm(llmResult.value));
        } else {
          const message = llmResult.reason instanceof Error ? llmResult.reason.message : "Unknown error";
          setSettingsLoadError(message);
          if (isAuthRequiredError(llmResult.reason)) {
            toast.error(message);
          } else {
            toast.error(`Failed to load LLM settings: ${message}`);
          }
        }

        if (dataSourceResult.status === "fulfilled") {
          setDataSettings(dataSourceResult.value);
        } else {
          const message = dataSourceResult.reason instanceof Error ? dataSourceResult.reason.message : "Unknown error";
          setSettingsLoadError(message);
          if (isAuthRequiredError(dataSourceResult.reason)) {
            toast.error(message);
          } else {
            toast.error(`Failed to load data source settings: ${message}`);
          }
        }

        if (channelResult.status === "fulfilled") {
          setChannelStatus(channelResult.value);
        } else {
          const message = channelResult.reason instanceof Error ? channelResult.reason.message : "Unknown error";
          toast.error(`${t("settings.channels.refreshFailed")}: ${message}`);
          setChannelStatus(null);
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [t]);

  const refreshChannelStatus = async () => {
    setChannelRefreshing(true);
    try {
      setChannelStatus(await api.getChannelStatus());
    } catch (error) {
      toast.error(`${t("settings.channels.refreshFailed")}: ${error instanceof Error ? error.message : "Unknown error"}`);
    } finally {
      setChannelRefreshing(false);
    }
  };

  const setChannelsRunning = async (action: "start" | "stop") => {
    setChannelAction(action);
    try {
      const updated = action === "start" ? await api.startChannels() : await api.stopChannels();
      setChannelStatus(updated);
      toast.success(action === "start" ? t("settings.channels.started") : t("settings.channels.stoppedToast"));
    } catch (error) {
      toast.error(`${action === "start" ? t("settings.channels.startFailed") : t("settings.channels.stopFailed")}: ${error instanceof Error ? error.message : "Unknown error"}`);
    } finally {
      setChannelAction(null);
    }
  };

  const providers = settings?.providers ?? [];
  const selectedProvider = useMemo<LLMProviderOption | undefined>(
    () => providers.find((provider) => provider.name === form?.provider),
    [form?.provider, providers],
  );

  const applyProviderDefaults = (provider = selectedProvider) => {
    if (!provider || !form) return;
    setForm({
      ...form,
      model_name: provider.default_model,
      base_url: provider.default_base_url,
    });
  };

  const onProviderChange = (name: string) => {
    const provider = providers.find((item) => item.name === name);
    if (!provider || !form) return;
    setForm({
      ...form,
      provider: provider.name,
      model_name: provider.default_model,
      base_url: provider.default_base_url,
    });
    setApiKey("");
    setClearApiKey(false);
  };

  const submitLocalApiKey = (event: FormEvent) => {
    event.preventDefault();
    setApiAuthKey(localApiKey);
    toast.success("Local API key saved");
    window.location.reload();
  };

  const submitNeonJwt = (event: FormEvent) => {
    event.preventDefault();
    if (neonJwt.trim()) {
      setStoredNeonJWT(neonJwt.trim());
      toast.success("Neon Identity Provider JWT saved for Data API operations");
    } else {
      clearStoredNeonJWT();
      toast.success("Stored Neon JWT cleared");
    }
  };

  const testNeonConnectionAction = async () => {
    setTestingNeon(true);
    try {
      const res = await checkNeonConnection();
      setNeonStatus({
        tested: true,
        connected: res.connected,
        status: res.status,
        hasToken: res.hasToken,
      });
      if (res.connected) {
        toast.success(`Neon Data API connected successfully (${res.status})`);
      } else {
        toast.error(`Neon Data API connection issue: ${res.status}`);
      }
    } catch (err) {
      setNeonStatus({
        tested: true,
        connected: false,
        status: err instanceof Error ? err.message : "Connection failed",
        hasToken: Boolean(neonJwt.trim()),
      });
      toast.error("Failed to connect to Neon Data API");
    } finally {
      setTestingNeon(false);
    }
  };

  const neonDatabaseSection = (
    <div className={cardClass}>
      <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{"Neon Database & Data API"}</h2>
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              {NEON_APP_NAME}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">
            {"PostgreSQL Data API client with JWT validation against JWKS for row-level security (RLS)."}
          </p>
        </div>
        <button
          type="button"
          onClick={testNeonConnectionAction}
          disabled={testingNeon}
          className={`${ghostBtnClass} self-start md:self-auto`}
        >
          {testingNeon ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {"Test Data API"}
        </button>
      </div>

      <div className="mb-4 grid gap-2 rounded-lg border border-border/40 bg-muted/20 p-3 text-xs">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-muted-foreground">{"Data API URL:"}</span>
          <span className="font-mono text-foreground break-all">{NEON_DATA_API_URL}</span>
        </div>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-muted-foreground">{"Auth URL:"}</span>
          <span className="font-mono text-foreground break-all">{NEON_AUTH_URL}</span>
        </div>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-muted-foreground">{"JWKS URL (Auth):"}</span>
          <span className="font-mono text-foreground break-all">{NEON_JWKS_URL}</span>
        </div>
        {neonStatus?.tested && (
          <div className="mt-1 flex items-center gap-2 border-t border-border/40 pt-2 font-medium">
            <span className={`inline-block h-2 w-2 rounded-full ${neonStatus.connected ? "bg-emerald-500" : "bg-destructive"}`} />
            <span>{`Status: ${neonStatus.status}`}</span>
            <span className="text-muted-foreground">{neonStatus.hasToken ? "• Token attached" : "• No custom token (Anonymous)"}</span>
          </div>
        )}
      </div>

      <form onSubmit={submitNeonJwt} className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
        <label className="grid gap-2">
          <span className={labelClass}>{"Identity Provider JWT (Clerk / Auth0 / Custom)"}</span>
          <input
            type="password"
            value={neonJwt}
            onChange={(event) => setNeonJwt(event.target.value)}
            className={fieldClass}
            placeholder={"Paste a user JWT token to test queries with active RLS..."}
            autoComplete="off"
          />
        </label>
        <button
          type="submit"
          className={`${primaryBtnClass} self-end`}
        >
          <Save className="h-4 w-4" />
          {"Save JWT"}
        </button>
      </form>
      <p className="mt-2 text-xs text-muted-foreground">
        {"Queries run via "}
        <code className="text-primary font-mono">@neondatabase/neon-js</code>
        {" automatically retrieve and attach this JWT token for all database operations."}
      </p>
    </div>
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    try {
      const updated = await api.updateLLMSettings({
        ...form,
        api_key: apiKey.trim() || undefined,
        clear_api_key: clearApiKey,
      });
      setSettings(updated);
      setForm(toForm(updated));
      setApiKey("");
      setClearApiKey(false);
      toast.success("LLM settings saved");
    } catch (error) {
      toast.error(`Failed to save LLM settings: ${error instanceof Error ? error.message : "Unknown error"}`);
    } finally {
      setSaving(false);
    }
  };

  const submitDataSources = async (event: FormEvent) => {
    event.preventDefault();
    setDataSaving(true);
    try {
      const payload = {
        active_market_feed: dataSettings?.active_market_feed || "okx",
        binance_api_key: binanceApiKey.trim() || undefined,
        binance_api_secret: binanceApiSecret.trim() || undefined,
        clear_binance_key: clearBinanceKey,
        okx_api_key: okxApiKey.trim() || undefined,
        okx_api_secret: okxApiSecret.trim() || undefined,
        okx_passphrase: okxPassphrase.trim() || undefined,
        clear_okx_key: clearOkxKey,
        bybit_api_key: bybitApiKey.trim() || undefined,
        bybit_api_secret: bybitApiSecret.trim() || undefined,
        clear_bybit_key: clearBybitKey,
        gateio_api_key: gateioApiKey.trim() || undefined,
        gateio_api_secret: gateioApiSecret.trim() || undefined,
        clear_gateio_key: clearGateioKey,
      };
      const updated = await api.updateDataSourceSettings(payload);
      setDataSettings(updated);
      setBinanceApiKey("");
      setBinanceApiSecret("");
      setClearBinanceKey(false);
      setOkxApiKey("");
      setOkxApiSecret("");
      setOkxPassphrase("");
      setClearOkxKey(false);
      setBybitApiKey("");
      setBybitApiSecret("");
      setClearBybitKey(false);
      setGateioApiKey("");
      setGateioApiSecret("");
      setClearGateioKey(false);
      toast.success("Exchange credentials and market feed settings saved");
    } catch (error) {
      toast.error(`Failed to save exchange settings: ${error instanceof Error ? error.message : "Unknown error"}`);
    } finally {
      setDataSaving(false);
    }
  };

  const localApiAccessSection = (
    <form onSubmit={submitLocalApiKey} className={cardClass}>
      <div className="mb-4 space-y-1">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-primary" />
          <h2 className="text-base font-semibold">{"Local API access"}</h2>
        </div>
        <p className="text-sm text-muted-foreground">{"For remote or private Web UI deployments, enter the server API key once in this browser. Localhost use can stay blank."}</p>
      </div>
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
        <label className="grid gap-2">
          <span className={labelClass}>{"Server API key"}</span>
          <input
            type="password"
            value={localApiKey}
            onChange={(event) => setLocalApiKeyState(event.target.value)}
            className={fieldClass}
            placeholder={"Stored only in this browser. Leave blank to clear it."}
            autoComplete="current-password"
          />
        </label>
        <button
          type="submit"
          className={`${primaryBtnClass} self-end`}
        >
          <Save className="h-4 w-4" />
          {i18n.t("settings.save")}
        </button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{"Stored only in this browser. Leave blank to clear it."}</p>
    </form>
  );

  if (loading || !form || !settings || !dataSettings) {
    return (
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{"Settings"}</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">{"Configure model credentials and market data source tokens for this local project."}</p>
        </div>
        {localApiAccessSection}
        {neonDatabaseSection}
        <div className="flex min-h-32 items-center justify-center rounded-lg border bg-card p-5 text-sm text-muted-foreground">
          {settingsLoadError ? (
            <div className="text-center">
              <div className="font-medium text-foreground">{"Settings are unavailable"}</div>
              <div className="mt-1">{settingsLoadError}</div>
            </div>
          ) : (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              {"Loading..."}
            </>
          )}
        </div>
      </div>
    );
  }

  const keyStatus = settings.api_key_configured
    ? "Configured"
    : settings.api_key_required
      ? "Leave blank to keep the current key"
      : selectedProvider?.auth_type === "oauth" && selectedProvider.login_command
        ? `This provider uses OAuth. Run: ${selectedProvider.login_command}`
        : "This provider does not require an API key.";
  const apiKeyDisabled = !selectedProvider?.api_key_required || clearApiKey;
  const channelRows = channelStatus
    ? Object.entries(channelStatus.channels ?? {}).sort(([a], [b]) => a.localeCompare(b))
    : [];
  const channelEnabledCount = channelRows.filter(([, item]) => item.enabled).length;
  const channelLoadedCount = channelRows.filter(([, item]) => item.loaded).length;
  const channelUnavailableCount = channelRows.filter(([, item]) => item.available === false).length;
  const channelBusy = channelRefreshing || channelAction !== null;

  const channelsSection = (
    <section className={cardClass}>
      <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <MessageSquareMore className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t("settings.channels.title")}</h2>
          </div>
          <p className="max-w-3xl text-sm text-muted-foreground">{t("settings.channels.description")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={refreshChannelStatus}
            disabled={channelBusy}
            className={ghostBtnClass}
          >
            {channelRefreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {t("settings.channels.refresh")}
          </button>
          <button
            type="button"
            onClick={() => setChannelsRunning("start")}
            disabled={channelBusy || !channelStatus}
            className={primaryBtnClass}
          >
            {channelAction === "start" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {t("settings.channels.start")}
          </button>
          <button
            type="button"
            onClick={() => setChannelsRunning("stop")}
            disabled={channelBusy || !channelStatus}
            className={ghostBtnClass}
          >
            {channelAction === "stop" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
            {t("settings.channels.stop")}
          </button>
        </div>
      </div>

      {channelStatus ? (
        <>
          <div className="mb-4 grid gap-3 md:grid-cols-4">
            <div className="glass-panel rounded-xl px-3 py-2">
              <div className="text-xs text-muted-foreground">{t("settings.channels.runtime")}</div>
              <div className="text-sm font-medium">{channelStatus.running ? t("settings.channels.running") : t("settings.channels.stopped")}</div>
            </div>
            <div className="glass-panel rounded-xl px-3 py-2">
              <div className="text-xs text-muted-foreground">{t("settings.channels.enabled")}</div>
              <div className="text-sm font-medium">{channelEnabledCount}</div>
            </div>
            <div className="glass-panel rounded-xl px-3 py-2">
              <div className="text-xs text-muted-foreground">{t("settings.channels.loaded")}</div>
              <div className="text-sm font-medium">{channelLoadedCount}</div>
            </div>
            <div className="glass-panel rounded-xl px-3 py-2">
              <div className="text-xs text-muted-foreground">{t("settings.channels.unavailable")}</div>
              <div className="text-sm font-medium">{channelUnavailableCount}</div>
            </div>
          </div>

          <div className="glass-panel overflow-hidden rounded-xl border border-border/40">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">{t("settings.channels.channel")}</th>
                  <th className="px-3 py-2 text-left font-medium">{t("settings.channels.state")}</th>
                  <th className="px-3 py-2 text-left font-medium">{t("settings.channels.recovery")}</th>
                </tr>
              </thead>
              <tbody>
                {channelRows.map(([name, item]) => (
                  <tr key={name} className="border-t">
                    <td className="px-3 py-2 align-top">
                      <div className="font-medium">{item.display_name || name}</div>
                      <div className="text-xs text-muted-foreground">{name}</div>
                    </td>
                    <td className="px-3 py-2 align-top">
                      <div className="flex flex-wrap gap-1.5">
                        <span className={`rounded-full px-2 py-0.5 text-xs ${item.enabled ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"}`}>
                          {item.enabled ? t("settings.channels.enabled") : t("settings.channels.disabled")}
                        </span>
                        <span className={`rounded-full px-2 py-0.5 text-xs ${item.loaded ? "bg-success/10 text-success" : "bg-muted text-muted-foreground"}`}>
                          {item.loaded ? t("settings.channels.loaded") : t("settings.channels.notLoaded")}
                        </span>
                        <span className={`rounded-full px-2 py-0.5 text-xs ${item.running ? "bg-success/10 text-success" : "bg-muted text-muted-foreground"}`}>
                          {item.running ? t("settings.channels.running") : t("settings.channels.stopped")}
                        </span>
                      </div>
                    </td>
                    <td className="max-w-md px-3 py-2 align-top text-xs text-muted-foreground">
                      {item.install_hint || item.error || t("settings.channels.noRecovery")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="rounded-md border bg-muted/20 px-4 py-6 text-center text-sm text-muted-foreground">
          {t("settings.channels.refreshFailed")}
        </div>
      )}
    </section>
  );

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{"Settings"}</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">{"Configure model credentials and market data source tokens for this local project."}</p>
      </div>

      {localApiAccessSection}

      {neonDatabaseSection}

      {channelsSection}

      <div className="space-y-2">
        <h2 className="text-lg font-semibold tracking-tight">{"LLM Settings"}</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">{"Choose the model used by the agent and save it to the project-local agent/.env file."}</p>
      </div>

      <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
        <section className={cardClass}>
          <div className="mb-5 flex items-center gap-2">
            <Server className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{"Connection"}</h2>
          </div>

          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{i18n.t("settings.provider")}</span>
              <select
                value={form.provider}
                onChange={(event) => onProviderChange(event.target.value)}
                className={selectFieldClass}
              >
                {providers.map((provider) => (
                  <option key={provider.name} value={provider.name}>{provider.label}</option>
                ))}
              </select>
              <span className={hintClass}>{"Changing providers updates the recommended model and endpoint."}</span>
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{"Model"}</span>
              <div className="flex gap-2">
                <input
                  value={form.model_name}
                  onChange={(event) => setForm({ ...form, model_name: event.target.value })}
                  className={fieldClass}
                  required
                />
                <button
                  type="button"
                  onClick={() => applyProviderDefaults()}
                  className={`${ghostBtnClass} shrink-0`}
                  title={"Use provider defaults"}
                >
                  <RotateCcw className="h-4 w-4" />
                  <span className="hidden sm:inline">{"Use provider defaults"}</span>
                </button>
              </div>
              <span className={hintClass}>{"Use the exact model id required by your provider."}</span>
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{i18n.t("settings.baseUrl")}</span>
              <input
                value={form.base_url}
                onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                className={fieldClass}
                placeholder={selectedProvider?.default_base_url}
                disabled={selectedProvider?.auth_type === "oauth"}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>
                {selectedProvider?.auth_type === "oauth" ? "OAuth" : "API key"}
              </span>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  className={`${fieldClass} pl-9`}
                  placeholder={keyStatus}
                  autoComplete="current-password"
                  disabled={apiKeyDisabled}
                />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className={hintClass}>{keyStatus}</span>
                {selectedProvider?.api_key_required ? (
                  <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={clearApiKey}
                      onChange={(event) => {
                        setClearApiKey(event.target.checked);
                        if (event.target.checked) setApiKey("");
                      }}
                      className="h-3.5 w-3.5 accent-primary"
                    />
                    {"Clear saved API key"}
                  </label>
                ) : null}
              </div>
            </label>
          </div>
        </section>

        <section className={cardClass}>
          <div className="mb-5 flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{"Generation"}</h2>
          </div>

          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{i18n.t("settings.temperature")}</span>
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={form.temperature}
                onChange={(event) => setForm({ ...form, temperature: Number(event.target.value) })}
                className={fieldClass}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{i18n.t("settings.timeoutSeconds")}</span>
              <input
                type="number"
                min={1}
                max={3600}
                step={1}
                value={form.timeout_seconds}
                onChange={(event) => setForm({ ...form, timeout_seconds: Number(event.target.value) })}
                className={fieldClass}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{"Max retries"}</span>
              <input
                type="number"
                min={0}
                max={20}
                step={1}
                value={form.max_retries}
                onChange={(event) => setForm({ ...form, max_retries: Number(event.target.value) })}
                className={fieldClass}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{i18n.t("settings.reasoningEffort")}</span>
              <select
                value={form.reasoning_effort}
                onChange={(event) => setForm({ ...form, reasoning_effort: event.target.value })}
                className={selectFieldClass}
              >
                <option value="">{"Off"}</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
                <option value="max">max</option>
              </select>
              <span className={hintClass}>{"How hard the model thinks before answering. Higher is more thorough but slower; leave Off for fastest replies."}</span>
            </label>

            <div className="glass-panel rounded-xl px-3 py-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{i18n.t("settings.saved")}: </span>
              <span className="break-all font-mono">{settings.env_path}</span>
            </div>

            <button
              type="submit"
              disabled={saving}
              className={primaryBtnClass}
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {saving ? i18n.t("settings.saving") : i18n.t("settings.save")}
            </button>
          </div>
        </section>
      </form>

      <form onSubmit={submitDataSources} className={cardClass}>
        <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4 text-primary" />
              <h2 className="text-base font-semibold">{"Exchange Market Data & Execution"}</h2>
            </div>
            <p className="text-sm text-muted-foreground">{"Configure API keys and WebSocket connections for Binance, OKX, Bybit, and Gate.io."}</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{"Default Feed:"}</span>
            <select
              value={dataSettings.active_market_feed || "okx"}
              onChange={(e) => setDataSettings({ ...dataSettings, active_market_feed: e.target.value })}
              className={selectFieldClass}
            >
              <option value="okx">OKX (Fastest Perpetual)</option>
              <option value="binance">Binance (USD-M Futures)</option>
              <option value="bybit">Bybit (Linear V5)</option>
              <option value="gate">Gate.io (Futures / Spot)</option>
            </select>
          </div>
        </div>

        {/* Exchange Tabs */}
        <div className="mb-5 flex flex-wrap gap-2 border-b border-border/40 pb-3">
          {[
            { id: "okx" as const, name: "OKX", configured: dataSettings.okx_configured, latency: "38ms" },
            { id: "binance" as const, name: "Binance", configured: dataSettings.binance_configured, latency: "45ms" },
            { id: "bybit" as const, name: "Bybit", configured: dataSettings.bybit_configured, latency: "52ms" },
            { id: "gate" as const, name: "Gate.io", configured: dataSettings.gateio_configured, latency: "68ms" },
          ].map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setActiveExchangeTab(item.id)}
              className={`flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-colors ${
                activeExchangeTab === item.id
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "bg-muted/40 text-muted-foreground hover:bg-muted"
              }`}
            >
              <span>{item.name}</span>
              <span className={`inline-block h-2 w-2 rounded-full ${item.configured ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`} />
              <span className="text-xs opacity-75 font-mono">({item.latency})</span>
            </button>
          ))}
        </div>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
          {/* Active Tab Form */}
          <div className="grid gap-4">
            {activeExchangeTab === "okx" && (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-foreground">OKX API & Secret Credentials</span>
                  <span className="text-xs text-muted-foreground font-mono">{dataSettings.okx_key_hint || "OKX Market Feed"}</span>
                </div>
                <label className="grid gap-2">
                  <span className={labelClass}>{"OKX API Key"}</span>
                  <div className="relative">
                    <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                    <input
                      type="password"
                      value={okxApiKey}
                      onChange={(event) => setOkxApiKey(event.target.value)}
                      className={`${fieldClass} pl-9`}
                      placeholder={dataSettings.okx_configured ? "Configured (Leave blank to keep)" : "Enter OKX API Key"}
                      autoComplete="current-password"
                      disabled={clearOkxKey}
                    />
                  </div>
                </label>

                <label className="grid gap-2">
                  <span className={labelClass}>{"OKX Secret Key"}</span>
                  <input
                    type="password"
                    value={okxApiSecret}
                    onChange={(event) => setOkxApiSecret(event.target.value)}
                    className={fieldClass}
                    placeholder={dataSettings.okx_configured ? "••••••••••••••••" : "Enter OKX Secret Key"}
                    autoComplete="current-password"
                    disabled={clearOkxKey}
                  />
                </label>

                <label className="grid gap-2">
                  <span className={labelClass}>{"OKX Passphrase"}</span>
                  <input
                    type="password"
                    value={okxPassphrase}
                    onChange={(event) => setOkxPassphrase(event.target.value)}
                    className={fieldClass}
                    placeholder={dataSettings.okx_configured ? "••••••••" : "Enter OKX API Passphrase"}
                    autoComplete="current-password"
                    disabled={clearOkxKey}
                  />
                  <div className="flex items-center justify-between gap-3">
                    <span className={hintClass}>{"Supports Public Market Feeds, L2 Book, Perpetuals & Futures."}</span>
                    <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={clearOkxKey}
                        onChange={(event) => {
                          setClearOkxKey(event.target.checked);
                          if (event.target.checked) {
                            setOkxApiKey("");
                            setOkxApiSecret("");
                            setOkxPassphrase("");
                          }
                        }}
                        className="h-3.5 w-3.5 accent-primary"
                      />
                      {"Clear OKX key"}
                    </label>
                  </div>
                </label>
              </>
            )}

            {activeExchangeTab === "binance" && (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-foreground">Binance USD-M & Spot Credentials</span>
                  <span className="text-xs text-muted-foreground font-mono">{dataSettings.binance_key_hint || "Binance Public Feed"}</span>
                </div>
                <label className="grid gap-2">
                  <span className={labelClass}>{"Binance API Key"}</span>
                  <div className="relative">
                    <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                    <input
                      type="password"
                      value={binanceApiKey}
                      onChange={(event) => setBinanceApiKey(event.target.value)}
                      className={`${fieldClass} pl-9`}
                      placeholder={dataSettings.binance_configured ? "Configured (Leave blank to keep)" : "Enter Binance API Key"}
                      autoComplete="current-password"
                      disabled={clearBinanceKey}
                    />
                  </div>
                </label>

                <label className="grid gap-2">
                  <span className={labelClass}>{"Binance Secret Key"}</span>
                  <input
                    type="password"
                    value={binanceApiSecret}
                    onChange={(event) => setBinanceApiSecret(event.target.value)}
                    className={fieldClass}
                    placeholder={dataSettings.binance_configured ? "••••••••••••••••" : "Enter Binance Secret Key"}
                    autoComplete="current-password"
                    disabled={clearBinanceKey}
                  />
                  <div className="flex items-center justify-between gap-3">
                    <span className={hintClass}>{"Supports USD-M Futures, Spot orderbooks, and WebSocket feeds."}</span>
                    <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={clearBinanceKey}
                        onChange={(event) => {
                          setClearBinanceKey(event.target.checked);
                          if (event.target.checked) {
                            setBinanceApiKey("");
                            setBinanceApiSecret("");
                          }
                        }}
                        className="h-3.5 w-3.5 accent-primary"
                      />
                      {"Clear Binance key"}
                    </label>
                  </div>
                </label>
              </>
            )}

            {activeExchangeTab === "bybit" && (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-foreground">Bybit V5 Unified Account Credentials</span>
                  <span className="text-xs text-muted-foreground font-mono">{dataSettings.bybit_key_hint || "Bybit Public Feed"}</span>
                </div>
                <label className="grid gap-2">
                  <span className={labelClass}>{"Bybit API Key"}</span>
                  <div className="relative">
                    <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                    <input
                      type="password"
                      value={bybitApiKey}
                      onChange={(event) => setBybitApiKey(event.target.value)}
                      className={`${fieldClass} pl-9`}
                      placeholder={dataSettings.bybit_configured ? "Configured (Leave blank to keep)" : "Enter Bybit API Key"}
                      autoComplete="current-password"
                      disabled={clearBybitKey}
                    />
                  </div>
                </label>

                <label className="grid gap-2">
                  <span className={labelClass}>{"Bybit API Secret"}</span>
                  <input
                    type="password"
                    value={bybitApiSecret}
                    onChange={(event) => setBybitApiSecret(event.target.value)}
                    className={fieldClass}
                    placeholder={dataSettings.bybit_configured ? "••••••••••••••••" : "Enter Bybit Secret Key"}
                    autoComplete="current-password"
                    disabled={clearBybitKey}
                  />
                  <div className="flex items-center justify-between gap-3">
                    <span className={hintClass}>{"Supports Linear Perpetuals, Inverse Futures, and Orderbook L2 streams."}</span>
                    <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={clearBybitKey}
                        onChange={(event) => {
                          setClearBybitKey(event.target.checked);
                          if (event.target.checked) {
                            setBybitApiKey("");
                            setBybitApiSecret("");
                          }
                        }}
                        className="h-3.5 w-3.5 accent-primary"
                      />
                      {"Clear Bybit key"}
                    </label>
                  </div>
                </label>
              </>
            )}

            {activeExchangeTab === "gate" && (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-foreground">Gate.io V4 API Credentials</span>
                  <span className="text-xs text-muted-foreground font-mono">{dataSettings.gateio_key_hint || "Gate.io Public Feed"}</span>
                </div>
                <label className="grid gap-2">
                  <span className={labelClass}>{"Gate.io API Key"}</span>
                  <div className="relative">
                    <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                    <input
                      type="password"
                      value={gateioApiKey}
                      onChange={(event) => setGateioApiKey(event.target.value)}
                      className={`${fieldClass} pl-9`}
                      placeholder={dataSettings.gateio_configured ? "Configured (Leave blank to keep)" : "Enter Gate.io API Key"}
                      autoComplete="current-password"
                      disabled={clearGateioKey}
                    />
                  </div>
                </label>

                <label className="grid gap-2">
                  <span className={labelClass}>{"Gate.io API Secret"}</span>
                  <input
                    type="password"
                    value={gateioApiSecret}
                    onChange={(event) => setGateioApiSecret(event.target.value)}
                    className={fieldClass}
                    placeholder={dataSettings.gateio_configured ? "••••••••••••••••" : "Enter Gate.io Secret Key"}
                    autoComplete="current-password"
                    disabled={clearGateioKey}
                  />
                  <div className="flex items-center justify-between gap-3">
                    <span className={hintClass}>{"Supports Spot, Delivery Futures, and USDT margined perpetual contracts."}</span>
                    <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={clearGateioKey}
                        onChange={(event) => {
                          setClearGateioKey(event.target.checked);
                          if (event.target.checked) {
                            setGateioApiKey("");
                            setGateioApiSecret("");
                          }
                        }}
                        className="h-3.5 w-3.5 accent-primary"
                      />
                      {"Clear Gate.io key"}
                    </label>
                  </div>
                </label>
              </>
            )}

            <div className="glass-panel rounded-xl px-3 py-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{i18n.t("settings.saved")}: </span>
              <span className="break-all font-mono">{dataSettings.env_path}</span>
            </div>

            <button
              type="submit"
              disabled={dataSaving}
              className={primaryBtnClass}
            >
              {dataSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {dataSaving ? i18n.t("settings.saving") : "Save Exchange Settings"}
            </button>
          </div>

          {/* Provider Health & Capabilities Sidebar */}
          <div className="space-y-3">
            <div className="glass-panel rounded-xl p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <span className="text-sm font-semibold">Active Exchange Endpoints</span>
                <span className="rounded-full bg-success/10 px-2 py-0.5 text-xs text-success font-medium">4 Providers Ready</span>
              </div>
              <div className="space-y-2.5 text-xs text-muted-foreground">
                {(dataSettings.providers || []).map((p) => (
                  <div key={p.id} className="flex items-center justify-between rounded-lg border border-border/30 bg-background/50 p-2.5">
                    <div>
                      <div className="font-medium text-foreground">{p.name}</div>
                      <div className="text-[11px] text-muted-foreground">{p.capabilities.slice(0, 3).join(", ")}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-emerald-500 font-mono font-medium">{p.latency_ms}ms</div>
                      <div className="text-[10px] text-muted-foreground">{p.status}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="glass-panel rounded-xl p-3.5 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">⚡ Public Market Feed: </span>
              Even with API keys unconfigured, the system connects directly to public high-throughput WebSocket & REST orderbook channels for BTC, ETH, SOL, and all perpetual pairs.
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}
