// Frontend configuration for the Queuer app.
// When the HTML is served by FastAPI, an empty API_BASE uses the same origin.
// Example API request:
//   /admin/login
//
// If your API is hosted separately, change API_BASE to:
//   "http://localhost:8000"

const QueuerConfig = {
  API_BASE: "",
  TOKEN_KEY: "queuer_access_token",

  // Turns an API error body into one readable sentence.
  errorText(data, fallback) {
    const d = data && data.detail;
    if (!d) return fallback;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      const text = d.map(e => {
        const field = (e.loc || []).slice(1).join(".");
        const msg = String(e.msg || "").replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      }).filter(Boolean).join(" ");
      return text || fallback;
    }
    return fallback;
  },

  api(path) {
    const base = this.API_BASE.replace(/\/$/, "");
    return `${base}${path}`;
  }
};
