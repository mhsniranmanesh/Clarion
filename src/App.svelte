<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { listen, type UnlistenFn } from '@tauri-apps/api/event';

  type Phase = 'idle' | 'recording' | 'transcribing' | 'structuring' | 'done' | 'error';
  type View = 'status' | 'settings' | 'history';

  interface AppConfig {
    openai_api_key: string;
    anthropic_api_key: string;
    preprocess_model: string;
    project_dir: string | null;
    shortcut: string;
    transcription_provider: 'cloud' | 'local';
    whisper_model: string;
    auto_paste: boolean;
    audio_device: string | null;
  }

  interface AudioDevice {
    name: string;
    is_default: boolean;
  }

  interface HistoryEntry {
    original: string;
    structured: string;
    timestamp: number;
  }

  let currentView: View = $state('status');
  let phase = $state<Phase>('idle');
  let error: string = $state('');
  let lastResult: string = $state('');
  let config: AppConfig = $state({
    openai_api_key: '',
    anthropic_api_key: '',
    preprocess_model: 'claude-haiku-4-5-20251001',
    project_dir: null,
    shortcut: 'CmdOrCtrl+Shift+Space',
    transcription_provider: 'cloud',
    whisper_model: 'base',
    auto_paste: true,
    audio_device: null,
  });

  interface ModelStatus {
    id: string;
    name: string;
    size: string;
    description: string;
    downloaded: boolean;
  }

  let history: HistoryEntry[] = $state([]);
  let saveMessage: string = $state('');
  let copiedId: number = $state(-1);
  let models: ModelStatus[] = $state([]);
  let downloadingModelId: string | null = $state(null);
  let audioDevices: AudioDevice[] = $state([]);
  let unlisteners: UnlistenFn[] = [];

  onMount(async () => {
    phase = await invoke<Phase>('get_phase');
    config = await invoke<AppConfig>('get_config');
    models = await invoke<ModelStatus[]>('get_models_status');
    audioDevices = await invoke<AudioDevice[]>('list_audio_devices');

    // First-run: if no API keys configured, go to Settings
    const needsSetup =
      !config.anthropic_api_key &&
      (config.transcription_provider === 'cloud' ? !config.openai_api_key : true);
    if (needsSetup) {
      currentView = 'settings';
    }

    unlisteners.push(
      await listen<Phase>('phase-changed', (event) => {
        phase = event.payload;
        if (phase === 'idle') error = '';
      })
    );

    unlisteners.push(
      await listen<string>('pipeline-error', (event) => {
        error = event.payload;
        phase = 'error';
      })
    );

    unlisteners.push(
      await listen<{ original: string; structured: string }>('pipeline-complete', async (event) => {
        lastResult = event.payload.structured;
        history = await invoke<HistoryEntry[]>('get_history');
      })
    );
  });

  onDestroy(() => {
    unlisteners.forEach((fn) => fn());
  });

  async function downloadModel(modelId: string) {
    downloadingModelId = modelId;
    try {
      await invoke('download_whisper_model', { modelId });
      models = await invoke<ModelStatus[]>('get_models_status');
    } catch (e) {
      error = `Download failed: ${e}`;
    } finally {
      downloadingModelId = null;
    }
  }

  async function deleteModel(modelId: string) {
    try {
      await invoke('delete_whisper_model', { modelId });
      models = await invoke<ModelStatus[]>('get_models_status');
    } catch (e) {
      error = `Delete failed: ${e}`;
    }
  }

  async function refreshModels() {
    models = await invoke<ModelStatus[]>('get_models_status');
  }

  async function refreshAudioDevices() {
    audioDevices = await invoke<AudioDevice[]>('list_audio_devices');
  }

  async function saveConfig() {
    await invoke('update_config', { config });
    saveMessage = 'Saved';
    setTimeout(() => (saveMessage = ''), 2000);
  }

  async function copyFromHistory(text: string, idx: number) {
    await invoke('copy_to_clipboard', { text });
    copiedId = idx;
    setTimeout(() => (copiedId = -1), 1500);
  }

  async function loadHistory() {
    history = await invoke<HistoryEntry[]>('get_history');
  }

  function formatTime(ts: number): string {
    const d = new Date(ts * 1000);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return isToday ? time : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}`;
  }

  function truncate(text: string, len: number): string {
    return text.length > len ? text.slice(0, len) + '...' : text;
  }

  let isProcessing = $derived(phase === 'transcribing' || phase === 'structuring');
</script>

<main>
  <div class="titlebar" data-tauri-drag-region></div>

  <!-- Status View -->
  {#if currentView === 'status'}
    <div class="view status-view">
      <div class="orb-container">
        <div
          class="orb"
          class:orb-idle={phase === 'idle'}
          class:orb-recording={phase === 'recording'}
          class:orb-processing={isProcessing}
          class:orb-done={phase === 'done'}
          class:orb-error={phase === 'error'}
        >
          <div class="orb-glow"></div>
          <div class="orb-inner">
            {#if phase === 'idle'}
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/>
              </svg>
            {:else if phase === 'recording'}
              <div class="wave-bars">
                <span></span><span></span><span></span><span></span><span></span>
              </div>
            {:else if isProcessing}
              <svg class="spinner-icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
                <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
              </svg>
            {:else if phase === 'done'}
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            {:else if phase === 'error'}
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
              </svg>
            {/if}
          </div>
        </div>
      </div>

      <div class="status-text">
        {#if phase === 'idle'}
          <p class="phase-label">Ready</p>
          <p class="phase-hint">
            <span class="key-combo"><kbd>&#8984;</kbd><kbd>&#8679;</kbd><kbd>Space</kbd></span>
            hold to record
          </p>
        {:else if phase === 'recording'}
          <p class="phase-label recording-label">Listening</p>
          <p class="phase-hint">Release to process</p>
        {:else if phase === 'transcribing'}
          <p class="phase-label">Transcribing</p>
          <p class="phase-hint">Converting speech to text...</p>
        {:else if phase === 'structuring'}
          <p class="phase-label">Structuring</p>
          <p class="phase-hint">Building your prompt...</p>
        {:else if phase === 'done'}
          <p class="phase-label done-label">Copied to clipboard</p>
        {:else if phase === 'error'}
          <p class="phase-label error-label">Something went wrong</p>
        {/if}
      </div>

      {#if error}
        <div class="error-banner">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <span>{error}</span>
        </div>
      {/if}

      {#if lastResult && (phase === 'done' || phase === 'idle')}
        <div class="result-card">
          <div class="result-header">
            <span class="result-label">Last output</span>
            <button class="icon-btn" onclick={() => copyFromHistory(lastResult, -2)} title="Copy">
              {#if copiedId === -2}
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
              {:else}
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              {/if}
            </button>
          </div>
          <pre class="result-text">{lastResult}</pre>
        </div>
      {/if}
    </div>

  <!-- History View -->
  {:else if currentView === 'history'}
    <div class="view history-view">
      {#if history.length === 0}
        <div class="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" opacity="0.3">
            <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
          </svg>
          <p>No prompts yet</p>
          <span>Use the shortcut to create your first one</span>
        </div>
      {:else}
        {#each history as entry, i}
          <div class="history-card">
            <div class="history-meta">
              <span class="history-time">{formatTime(entry.timestamp)}</span>
              <button class="icon-btn" onclick={() => copyFromHistory(entry.structured, i)} title="Copy">
                {#if copiedId === i}
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--mint)" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                {:else}
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                {/if}
              </button>
            </div>
            <pre class="history-text">{entry.structured}</pre>
            {#if entry.original}
              <p class="history-original">{truncate(entry.original, 100)}</p>
            {/if}
          </div>
        {/each}
      {/if}
    </div>

  <!-- Settings View -->
  {:else if currentView === 'settings'}
    <div class="view settings-view">
      {#if !config.anthropic_api_key || !config.openai_api_key}
        <div class="welcome-banner">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg>
          <div>
            <p class="welcome-title">Welcome to Clarion</p>
            <p class="welcome-text">Add your API keys below to get started. You'll need an Anthropic key for prompt structuring{#if config.transcription_provider === 'cloud'}, and an OpenAI key for cloud transcription{/if}.</p>
          </div>
        </div>
      {/if}
      <section>
        <h2 class="section-title">API Keys</h2>
        <div class="input-group">
          <label for="openai-key">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
            OpenAI
          </label>
          <input id="openai-key" type="password" bind:value={config.openai_api_key} placeholder="sk-..." spellcheck="false" />
        </div>
        <div class="input-group">
          <label for="anthropic-key">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
            Anthropic
          </label>
          <input id="anthropic-key" type="password" bind:value={config.anthropic_api_key} placeholder="sk-ant-..." spellcheck="false" />
        </div>
      </section>

      <section>
        <h2 class="section-title">Transcription</h2>
        <div class="input-group">
          <!-- svelte-ignore a11y_label_has_associated_control -->
          <label>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>
            Provider
          </label>
          <div class="toggle-group">
            <button class="toggle-btn" class:toggle-active={config.transcription_provider === 'cloud'} onclick={() => (config.transcription_provider = 'cloud')}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>
              Cloud
            </button>
            <button class="toggle-btn" class:toggle-active={config.transcription_provider === 'local'} onclick={() => { config.transcription_provider = 'local'; refreshModels(); }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/></svg>
              Local
            </button>
          </div>
        </div>
        {#if config.transcription_provider === 'local'}
          <div class="model-library">
            {#each models as model}
              {@const isSelected = config.whisper_model === model.id}
              {@const isDownloading = downloadingModelId === model.id}
              <div
                class="model-card"
                class:model-card-selected={isSelected && model.downloaded}
                class:model-card-active={isSelected}
              >
                <div class="model-card-header">
                  <div class="model-card-info">
                    <span class="model-name">{model.name}</span>
                    <span class="model-size">{model.size}</span>
                  </div>
                  {#if model.downloaded}
                    <button
                      class="model-select-btn"
                      class:model-select-active={isSelected}
                      onclick={() => (config.whisper_model = model.id)}
                    >
                      {#if isSelected}
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
                        Active
                      {:else}
                        Use
                      {/if}
                    </button>
                  {:else}
                    <button class="model-dl-btn" disabled={isDownloading} onclick={() => downloadModel(model.id)}>
                      {#if isDownloading}
                        <svg class="spin-anim" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
                      {:else}
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                      {/if}
                      {isDownloading ? 'Downloading...' : 'Download'}
                    </button>
                  {/if}
                </div>
                <p class="model-desc">{model.description}</p>
                {#if model.downloaded && !isSelected}
                  <button class="model-delete-btn" onclick={() => deleteModel(model.id)}>Remove</button>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      </section>

      <section>
        <h2 class="section-title">Audio Input</h2>
        <div class="input-group">
          <label for="audio-device">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg>
            Microphone
          </label>
          <div style="display: flex; gap: 6px; align-items: center;">
            <select id="audio-device" bind:value={config.audio_device} style="flex: 1;" onfocus={refreshAudioDevices}>
              <option value={null}>System default</option>
              {#each audioDevices as device}
                <option value={device.name}>
                  {device.name}{device.is_default ? ' (default)' : ''}
                </option>
              {/each}
            </select>
            <button class="icon-btn" onclick={refreshAudioDevices} title="Refresh devices" style="padding: 6px;">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
            </button>
          </div>
        </div>
      </section>

      <section>
        <h2 class="section-title">Processing</h2>
        <div class="input-group">
          <label for="model">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
            Structuring model
          </label>
          <select id="model" bind:value={config.preprocess_model}>
            <option value="claude-haiku-4-5-20251001">Haiku 4.5 — fast, low cost</option>
            <option value="claude-sonnet-4-6-20250514">Sonnet 4.6 — higher quality</option>
          </select>
        </div>
        <div class="input-group">
          <label for="project-dir">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            Project directory
          </label>
          <input id="project-dir" type="text" bind:value={config.project_dir} placeholder="Optional — for context injection" spellcheck="false" />
        </div>
      </section>

      <section>
        <h2 class="section-title">Behavior</h2>
        <label class="checkbox-row">
          <input type="checkbox" bind:checked={config.auto_paste} />
          <span>Auto-paste into active app after processing</span>
        </label>
      </section>

      <section>
        <h2 class="section-title">Shortcut</h2>
        <div class="shortcut-display">
          <kbd>&#8984;</kbd> + <kbd>&#8679;</kbd> + <kbd>Space</kbd>
        </div>
        <p class="section-hint">Customization coming in a future update</p>
      </section>

      <button class="save-btn" onclick={saveConfig}>
        {#if saveMessage}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          {saveMessage}
        {:else}
          Save settings
        {/if}
      </button>
    </div>
  {/if}

  <!-- Bottom Nav -->
  <nav>
    <button class:active={currentView === 'status'} onclick={() => (currentView = 'status')} title="Status">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
        <path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/>
      </svg>
      <span>Record</span>
    </button>
    <button class:active={currentView === 'history'} onclick={() => { currentView = 'history'; loadHistory(); }} title="History">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
      </svg>
      <span>History</span>
    </button>
    <button class:active={currentView === 'settings'} onclick={() => (currentView = 'settings')} title="Settings">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
      </svg>
      <span>Settings</span>
    </button>
  </nav>
</main>

<style>
  :root {
    --bg: #0c0c14;
    --bg-elevated: #12121e;
    --surface: #1a1a2e;
    --surface-light: #222240;
    --border: #2a2a45;
    --text: #eaeaef;
    --text-secondary: #8888a0;
    --text-muted: #55556a;
    --accent: #6c5ce7;
    --accent-glow: rgba(108, 92, 231, 0.3);
    --mint: #00d2a0;
    --mint-glow: rgba(0, 210, 160, 0.2);
    --red: #ff4757;
    --red-glow: rgba(255, 71, 87, 0.15);
    --amber: #ffa502;
    --amber-glow: rgba(255, 165, 2, 0.15);
    --radius: 12px;
    --radius-sm: 8px;
  }

  :global(*) {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }

  :global(body) {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', system-ui, sans-serif;
    font-size: 13px;
    -webkit-font-smoothing: antialiased;
    overflow: hidden;
  }

  :global(::selection) {
    background: var(--accent);
    color: white;
  }

  :global(::-webkit-scrollbar) {
    width: 6px;
  }
  :global(::-webkit-scrollbar-track) {
    background: transparent;
  }
  :global(::-webkit-scrollbar-thumb) {
    background: var(--border);
    border-radius: 3px;
  }

  main {
    display: flex;
    flex-direction: column;
    height: 100vh;
  }

  .titlebar {
    height: 28px;
    -webkit-app-region: drag;
    flex-shrink: 0;
  }

  /* ── Views ── */
  .view {
    flex: 1;
    overflow-y: auto;
    padding: 0 20px 20px;
  }

  /* ── Status View ── */
  .status-view {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: 16px;
  }

  .orb-container {
    position: relative;
    width: 100px;
    height: 100px;
    margin-bottom: 20px;
  }

  .orb {
    position: relative;
    width: 100%;
    height: 100%;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .orb-glow {
    position: absolute;
    inset: -12px;
    border-radius: 50%;
    opacity: 0;
    transition: opacity 0.4s ease;
  }

  .orb-inner {
    position: relative;
    z-index: 1;
    width: 72px;
    height: 72px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--surface);
    border: 1.5px solid var(--border);
    color: var(--text-secondary);
    transition: all 0.4s ease;
  }

  .orb-idle .orb-inner {
    border-color: var(--border);
  }

  .orb-recording .orb-inner {
    border-color: var(--red);
    color: var(--red);
    box-shadow: 0 0 30px var(--red-glow), inset 0 0 20px var(--red-glow);
  }
  .orb-recording .orb-glow {
    opacity: 1;
    background: radial-gradient(circle, var(--red-glow) 0%, transparent 70%);
    animation: glow-pulse 1.5s ease-in-out infinite;
  }

  .orb-processing .orb-inner {
    border-color: var(--accent);
    color: var(--accent);
    box-shadow: 0 0 30px var(--accent-glow);
  }
  .orb-processing .orb-glow {
    opacity: 1;
    background: radial-gradient(circle, var(--accent-glow) 0%, transparent 70%);
    animation: glow-rotate 2s linear infinite;
  }

  .orb-done .orb-inner {
    border-color: var(--mint);
    color: var(--mint);
    box-shadow: 0 0 25px var(--mint-glow);
  }
  .orb-done .orb-glow {
    opacity: 1;
    background: radial-gradient(circle, var(--mint-glow) 0%, transparent 70%);
  }

  .orb-error .orb-inner {
    border-color: var(--red);
    color: var(--red);
  }

  /* Wave bars animation */
  .wave-bars {
    display: flex;
    align-items: center;
    gap: 3px;
    height: 28px;
  }
  .wave-bars span {
    display: block;
    width: 3px;
    border-radius: 2px;
    background: var(--red);
    animation: wave 0.8s ease-in-out infinite;
  }
  .wave-bars span:nth-child(1) { height: 8px; animation-delay: 0s; }
  .wave-bars span:nth-child(2) { height: 16px; animation-delay: 0.1s; }
  .wave-bars span:nth-child(3) { height: 24px; animation-delay: 0.2s; }
  .wave-bars span:nth-child(4) { height: 16px; animation-delay: 0.3s; }
  .wave-bars span:nth-child(5) { height: 8px; animation-delay: 0.4s; }

  .spinner-icon {
    animation: spin 1s linear infinite;
  }

  .status-text {
    text-align: center;
    margin-bottom: 16px;
  }

  .phase-label {
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.3px;
    margin-bottom: 4px;
  }

  .recording-label { color: var(--red); }
  .done-label { color: var(--mint); }
  .error-label { color: var(--red); }

  .phase-hint {
    color: var(--text-muted);
    font-size: 13px;
  }

  .key-combo {
    display: inline-flex;
    gap: 4px;
    margin-right: 6px;
  }

  .key-combo kbd, .shortcut-display kbd {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 22px;
    height: 22px;
    padding: 0 5px;
    background: var(--surface-light);
    border: 1px solid var(--border);
    border-radius: 5px;
    font-family: inherit;
    font-size: 12px;
    color: var(--text-secondary);
    line-height: 1;
  }

  .error-banner {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    background: var(--red-glow);
    border: 1px solid rgba(255, 71, 87, 0.25);
    border-radius: var(--radius-sm);
    padding: 10px 14px;
    width: 100%;
    max-width: 340px;
    margin-top: 4px;
  }
  .error-banner svg { flex-shrink: 0; margin-top: 1px; color: var(--red); }
  .error-banner span { font-size: 12px; color: var(--red); line-height: 1.4; }

  .result-card {
    width: 100%;
    max-width: 340px;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-top: 16px;
    overflow: hidden;
  }

  .result-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
  }

  .result-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: var(--text-muted);
  }

  .result-text {
    padding: 12px 14px;
    font-size: 12px;
    line-height: 1.6;
    color: var(--text);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 160px;
    overflow-y: auto;
    font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
    background: transparent;
    margin: 0;
    border: 0;
  }

  /* ── History View ── */
  .history-view {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding-top: 8px;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    margin-top: 60px;
    color: var(--text-muted);
  }
  .empty-state p { font-size: 15px; font-weight: 500; }
  .empty-state span { font-size: 12px; }

  .history-card {
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 14px;
    transition: border-color 0.2s;
  }
  .history-card:hover {
    border-color: var(--surface-light);
  }

  .history-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }

  .history-time {
    font-size: 11px;
    color: var(--text-muted);
    font-weight: 500;
    letter-spacing: 0.3px;
  }

  .history-text {
    font-size: 12px;
    line-height: 1.5;
    color: var(--text-secondary);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 100px;
    overflow-y: auto;
    font-family: 'SF Mono', 'Fira Code', monospace;
    margin: 0;
    border: 0;
    background: transparent;
  }

  .history-original {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--border);
    font-style: italic;
  }

  .icon-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.15s;
  }
  .icon-btn:hover {
    border-color: var(--text-muted);
    color: var(--text);
  }

  /* ── Settings View ── */
  .welcome-banner {
    display: flex;
    gap: 12px;
    padding: 14px 16px;
    background: rgba(108, 92, 231, 0.08);
    border: 1px solid rgba(108, 92, 231, 0.2);
    border-radius: var(--radius);
    color: var(--text);
  }
  .welcome-banner svg { flex-shrink: 0; margin-top: 2px; color: var(--accent); }
  .welcome-title { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
  .welcome-text { font-size: 12px; color: var(--text-secondary); line-height: 1.5; }

  .settings-view {
    display: flex;
    flex-direction: column;
    gap: 24px;
    padding-top: 8px;
  }

  section {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .section-title {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--text-muted);
  }

  .section-hint {
    font-size: 11px;
    color: var(--text-muted);
  }

  .input-group {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .input-group label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
  }

  .input-group input,
  .input-group select {
    width: 100%;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: 9px 12px;
    font-size: 13px;
    font-family: inherit;
    outline: none;
    transition: border-color 0.2s;
  }

  .input-group input:focus,
  .input-group select:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-glow);
  }

  .input-group select {
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%238888a0' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 12px center;
    padding-right: 32px;
  }

  .shortcut-display {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 14px;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-muted);
    font-size: 13px;
  }

  .save-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    background: var(--accent);
    border: none;
    color: white;
    padding: 11px 16px;
    border-radius: var(--radius-sm);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }
  .save-btn:hover { opacity: 0.9; transform: translateY(-1px); }
  .save-btn:active { transform: translateY(0); }

  /* Toggle group */
  .toggle-group {
    display: flex;
    gap: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    overflow: hidden;
  }

  .toggle-btn {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 9px 12px;
    background: var(--bg-elevated);
    border: none;
    color: var(--text-muted);
    font-size: 13px;
    font-family: inherit;
    cursor: pointer;
    transition: all 0.2s;
  }

  .toggle-btn:first-child {
    border-right: 1px solid var(--border);
  }

  .toggle-btn:hover {
    color: var(--text-secondary);
  }

  .toggle-active {
    background: var(--accent);
    color: white;
  }
  .toggle-active:hover {
    color: white;
  }

  /* Model library */
  .model-library {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .model-card {
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 10px 12px;
    transition: border-color 0.2s;
  }
  .model-card-active {
    border-color: var(--surface-light);
  }
  .model-card-selected {
    border-color: var(--accent);
    background: rgba(108, 92, 231, 0.06);
  }

  .model-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }

  .model-card-info {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }

  .model-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
  }

  .model-size {
    font-size: 11px;
    color: var(--text-muted);
    background: var(--surface);
    padding: 1px 6px;
    border-radius: 4px;
  }

  .model-desc {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 4px;
    line-height: 1.4;
  }

  .model-select-btn, .model-dl-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    border-radius: 5px;
    font-size: 11px;
    font-weight: 600;
    font-family: inherit;
    cursor: pointer;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-secondary);
    transition: all 0.15s;
    white-space: nowrap;
    min-width: 62px;
    justify-content: center;
  }

  .model-select-btn:hover { border-color: var(--accent); color: var(--accent); }
  .model-select-active {
    background: var(--accent);
    border-color: var(--accent);
    color: white;
  }
  .model-select-active:hover { color: white; }

  .model-dl-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
  .model-dl-btn:disabled { opacity: 0.7; cursor: wait; }

  .model-delete-btn {
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 10px;
    font-family: inherit;
    cursor: pointer;
    padding: 2px 0;
    margin-top: 4px;
    transition: color 0.15s;
  }
  .model-delete-btn:hover { color: var(--red); }

  .spin-anim {
    animation: spin 1s linear infinite;
  }

  /* Checkbox */
  .checkbox-row {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;
    color: var(--text-secondary);
    cursor: pointer;
    padding: 6px 0;
  }

  .checkbox-row input[type="checkbox"] {
    appearance: none;
    width: 18px;
    height: 18px;
    border: 1.5px solid var(--border);
    border-radius: 4px;
    background: var(--bg-elevated);
    cursor: pointer;
    position: relative;
    flex-shrink: 0;
  }
  .checkbox-row input[type="checkbox"]:checked {
    background: var(--accent);
    border-color: var(--accent);
  }
  .checkbox-row input[type="checkbox"]:checked::after {
    content: '';
    position: absolute;
    left: 5px;
    top: 2px;
    width: 5px;
    height: 9px;
    border: solid white;
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
  }

  /* ── Bottom Nav ── */
  nav {
    display: flex;
    border-top: 1px solid var(--border);
    background: var(--bg-elevated);
    flex-shrink: 0;
    padding: 4px 0;
  }

  nav button {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: 8px 0;
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 10px;
    font-weight: 500;
    cursor: pointer;
    transition: color 0.2s;
  }
  nav button:hover { color: var(--text-secondary); }
  nav button.active { color: var(--accent); }
  nav button.active svg { stroke: var(--accent); }

  /* ── Animations ── */
  @keyframes wave {
    0%, 100% { transform: scaleY(0.4); }
    50% { transform: scaleY(1); }
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  @keyframes glow-pulse {
    0%, 100% { opacity: 0.6; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.08); }
  }

  @keyframes glow-rotate {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
</style>
