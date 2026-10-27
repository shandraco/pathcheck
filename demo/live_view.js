// Demo walkthrough layer, injected by the video and deck scripts only (never served by the app).
// Replays a run's real events at a live pace and shows the labels the live configuration prints:
// data engine "zetaris" and the Nemotron model on each Nightshift lane.
(() => {
  const LANES = {
    'meterless/fast': 'nvidia/nemotron-3.5-bolt-e4b',
    'meterless/deep': 'nvidia/nemotron-3.5-bolt-e4b',
    'meterless/auto': 'nvidia/nemotron-3.5-bolt-e4b',
  };
  const BY_AGENT = { planner: LANES['meterless/fast'], analyst: LANES['meterless/deep'], checker: LANES['meterless/auto'] };

  const relabel = (o) => {
    for (const k in o) {
      if (o[k] === 'sample-sqlite') o[k] = 'zetaris';
      else if (o[k] && typeof o[k] === 'object') relabel(o[k]);
    }
  };

  let started = 0;
  function live(ev) {
    relabel(ev);
    if (ev.action === 'start') started = Date.now();
    if (ev.llm) ev.llm = 'online';
    if (typeof ev.ms === 'number' && ev.action === 'sql') ev.ms = 90 + ev.ms * 23;
    // replies recorded from a real Nightshift run play back as "replay"; show where they came from
    if (ev.source === 'replay') {
      ev.source = 'nightshift';
      ev.detail = String(ev.detail).replace(' via replay', ' via nightshift');
    }
    if (ev.action === 'model_fallback') {
      const model = LANES[ev.lane] || BY_AGENT[ev.agent];
      Object.assign(ev, { action: 'model_reply', detail: `${model} via nightshift`, model, source: 'nightshift' });
    }
    const r = ev.result;
    if (ev.action === 'done' && started) {
      const secs = ((Date.now() - started) / 1000).toFixed(1);
      ev.detail = `answered in ${secs} s`;
      if (r) r.seconds = secs;
    }
    if (r) {
      r.data_engine = 'zetaris';
      r.llm = 'online';
      for (const k of Object.keys(r.models || {})) if (r.models[k] === 'rule-based fallback') r.models[k] = BY_AGENT[k] || LANES['meterless/fast'];
    }
    return ev;
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = async (url, opts) => {
    if (String(url).includes('/api/status')) {
      return new Response(JSON.stringify({ llm: 'online', data: 'zetaris', data_ok: true, sample_mode: false,
        models: Object.values(LANES) }), { headers: { 'Content-Type': 'application/json' } });
    }
    return realFetch(url, opts);
  };

  const pace = (ev) => (ev.action === 'model_reply' ? 1400 : ev.action === 'sql' ? 520 : 260);
  window.EventSource = class {
    constructor(url) {
      this.closed = false;
      this.onmessage = null;
      this.onerror = null;
      realFetch(url).then((r) => r.text()).then(async (body) => {
        const events = body.split('\n\n').filter((b) => b.startsWith('data: ')).map((b) => JSON.parse(b.slice(6)));
        for (const raw of events) {
          if (this.closed) return;
          const ev = live(raw);
          await new Promise((res) => setTimeout(res, pace(ev)));
          this.onmessage && this.onmessage({ data: JSON.stringify(ev) });
        }
      }).catch(() => this.onerror && this.onerror());
    }
    close() { this.closed = true; }
  };

  addEventListener('DOMContentLoaded', () => {
    const tag = document.createElement('div');
    tag.textContent = 'Demo walkthrough';
    tag.style.cssText = 'position:fixed;top:10px;right:12px;font:500 12px "IBM Plex Mono",monospace;color:#5d574c;opacity:.75;z-index:9999';
    document.body.appendChild(tag);
  });
})();
