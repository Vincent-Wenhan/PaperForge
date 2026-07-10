// Placeholder real API. Overwritten by LLM-generated business file.
// TODO: Replace mock with real API calls when ready

export async function getItems() {
  const res = await fetch("/api/items");
  if (!res.ok) throw new Error("Failed to fetch items");
  return res.json();
}
