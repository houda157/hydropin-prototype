// Where the app opens (filming shortcuts).
import { test } from "node:test";
import assert from "node:assert/strict";

import { initialHash } from "../lib/route.js";

test("final fix 7: ?demo=fixed opens on the fixed screen; an explicit hash wins", () => {
  assert.equal(initialHash(new URLSearchParams("demo=fixed"), ""), "#/fixed");
  assert.equal(initialHash(new URLSearchParams("demo=leak"), ""), "#/home");
  assert.equal(initialHash(new URLSearchParams("demo=fixed"), "#/savings"), "#/savings");
  assert.equal(initialHash(new URLSearchParams(""), "#/nowhere"), "#/home");
});
