// Proxies /api/* to the Django backend so the browser only talks to one origin.
// API_URL is read per request, so the same image works in Docker and locally.
const API_URL = () => process.env.API_URL ?? "http://localhost:8000";

async function proxy(request: Request, ctx: RouteContext<"/api/[...path]">) {
  const { path } = await ctx.params;
  const url = new URL(request.url);
  const target = `${API_URL()}/api/${path.join("/")}${url.search}`;
  const init: RequestInit = {
    method: request.method,
    headers: { "content-type": request.headers.get("content-type") ?? "application/json" },
    cache: "no-store",
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }
  const upstream = await fetch(target, init);
  const headers = new Headers({ "content-type": upstream.headers.get("content-type") ?? "application/json" });
  // The server clock: the console measures durations against it, not the browser's clock.
  const serverNow = upstream.headers.get("x-server-now");
  if (serverNow) headers.set("x-server-now", serverNow);
  return new Response(upstream.body, { status: upstream.status, headers });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE };
