// Plain-word labels for the RelayFailover chart.
export const title = "Live relay with a backup source";

export const state = (v) => {
  const other = v.active === "main" ? "backup" : "main";
  if (v.last === 0) return v.healthy[v.active] ? "Starting" : "Waiting to start";
  if (!v.healthy.main && !v.healthy.backup) return "Both sources stalled";
  if (!v.healthy[v.active]) return `Main stalled, switching`.replace("Main", v.active === "main" ? "Main" : "Backup");
  if (v.lastFrom !== v.active) return `Resuming on ${v.active}`;
  return `Playing from ${v.active}`;
};

export const group = (v) =>
  v.healthy.main && v.healthy.backup ? "ok" : !v.healthy.main && !v.healthy.backup ? "down" : "degraded";

export const colors = { ok: "teal", degraded: "orange", down: "pink" };

export const step = (action, from, to) => {
  if (action.startsWith("Fail")) return `a source stops advancing`;
  if (action.startsWith("Recover")) return `a source recovers`;
  return {
    Publish: null,
    Switch: "the relay switches source",
    Start: "the first segment plays",
    PumpSame: "the next segment plays",
    PumpResume: "the matching segment plays",
    Skip: "a segment fails everywhere and is skipped",
  }[action] ?? action;
};
