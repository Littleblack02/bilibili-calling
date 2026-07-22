import assert from "node:assert/strict";
import test from "node:test";

import worker from "../dist/server/index.js";

const environment = {
  ASSETS: {
    fetch: async () => new Response("Not found", { status: 404 }),
  },
};

const context = {
  waitUntil() {},
  passThroughOnException() {},
};

for (const [path, expectedText] of [
  ["/", "bilibili_calling"],
  ["/demo", "Ontology"],
]) {
  test(`Sites worker renders ${path}`, async () => {
    const response = await worker.fetch(
      new Request(`https://demo.invalid${path}`, { headers: { accept: "text/html" } }),
      environment,
      context,
    );
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
    const html = await response.text();
    assert.match(html, new RegExp(expectedText, "i"));
  });
}
