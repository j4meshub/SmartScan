export function defaultApiBase(locationLike = location, baseUri = document.baseURI) {
  if (["localhost", "127.0.0.1"].includes(locationLike.hostname)) {
    return "http://localhost:8000";
  }
  return new URL("api", baseUri).href.replace(/\/$/, "");
}
