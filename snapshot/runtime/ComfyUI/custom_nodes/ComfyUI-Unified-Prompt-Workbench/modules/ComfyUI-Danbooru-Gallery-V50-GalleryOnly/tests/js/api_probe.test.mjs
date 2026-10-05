import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";

const PROBE_PATH = fileURLToPath(new URL("../api_probe.mjs", import.meta.url));

const phase4CharacterTranslations = Object.freeze({
  "kei_(blue_archive)": "凯伊（蔚蓝档案）",
  "kei_(robot)_(blue_archive)": "凯伊（机器人）（蔚蓝档案）",
  "kei_(student)_(blue_archive)": "凯伊（学生）（蔚蓝档案）",
  "kasane_teto_(utau)": "重音Teto（UTAU）",
  "dan_heng_(imbibitor_lunae)_(honkai:_star_rail)": "丹恒·饮月（崩坏：星穹铁道）",
  "nyaan_(gundam_gquuuuuux)": "尼娅安（机动战士Gundam GQuuuuuuX）",
});

function sendJson(response, status, payload, headers = {}) {
  response.writeHead(status, { "content-type": "application/json", ...headers });
  response.end(JSON.stringify(payload));
}

function requestIdentity(url) {
  return {
    clientRequestId: url.searchParams.get("client_request_id"),
    queryKey: url.searchParams.get("client_query_key"),
  };
}

function successEnvelope(url, { items = [{ id: "fixture-item" }], nextCursor = null, pageKey = "page-1" } = {}) {
  return {
    requestId: "mock-server-request",
    ...requestIdentity(url),
    items,
    pageInfo: {
      nextCursor,
      pageKey,
      hasNext: nextCursor !== null,
    },
    ranking: null,
    provenance: { kind: "test" },
    applied: {},
    warnings: [],
    error: null,
  };
}

function errorEnvelope(url, status, code) {
  return {
    requestId: "mock-server-request",
    ...requestIdentity(url),
    items: [],
    pageInfo: { requestCursor: null, nextCursor: null, pageKey: "error-page", hasNext: null },
    warnings: [],
    error: {
      code,
      httpStatus: status,
      retryable: true,
      retryAfterSeconds: status === 429 ? 2 : null,
      message: `mock ${code}`,
    },
  };
}

async function startMockServer({ liveError = null, delaySystemStats = false } = {}) {
  const requests = [];
  const server = createServer((request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    requests.push({
      path: url.pathname,
      cursor: url.searchParams.get("cursor"),
      scenario: String(request.headers["x-gallery-test-scenario"] || "success"),
    });

    if (url.pathname === "/system_stats") {
      if (delaySystemStats) {
        const timer = setTimeout(() => sendJson(response, 200, {}), 1000);
        response.once("close", () => clearTimeout(timer));
      } else {
        sendJson(response, 200, {});
      }
      return;
    }
    if (url.pathname === "/object_info/DanbooruGalleryNode") {
      sendJson(response, 200, { DanbooruGalleryNode: {} });
      return;
    }
    if (url.pathname === "/danbooru_gallery/v2/providers") {
      sendJson(response, 200, {
        providers: [{
          source: "danbooru",
          availability: { state: "available" },
          features: { ranking: [], facets: [] },
        }],
      });
      return;
    }
    if (url.pathname === "/danbooru_gallery/translate_tag") {
      const tag = String(url.searchParams.get("tag") || "");
      sendJson(response, 200, {
        success: true,
        tag,
        translation: tag === "alphonse_mucha" ? null : "fixture translation",
      });
      return;
    }
    if (url.pathname === "/danbooru_gallery/translate_tags_batch") {
      sendJson(response, 200, {
        success: true,
        translations: {
          ...phase4CharacterTranslations,
          hatsune_miku: "初音未来",
          high_res: "高分辨率",
        },
      });
      return;
    }
    if (url.pathname === "/danbooru_gallery/autocomplete_with_translation") {
      const query = String(url.searchParams.get("query") || "");
      if (Object.prototype.hasOwnProperty.call(phase4CharacterTranslations, query)) {
        sendJson(response, 200, [{
          name: query,
          category: 4,
          post_count: 1000,
          translation: phase4CharacterTranslations[query],
        }]);
        return;
      }
      sendJson(response, 200, [{
        name: "highres",
        category: 5,
        post_count: 100,
        translation: "高分辨率",
        matched_alias: "high_res",
      }]);
      return;
    }
    if (url.pathname === "/danbooru_gallery/search_chinese") {
      const query = String(url.searchParams.get("query") || "");
      const reverseTargets = {
        "凯伊": "kei_(blue_archive)",
        "丹恒": "dan_heng_(imbibitor_lunae)_(honkai:_star_rail)",
        "尼娅安": "nyaan_(gundam_gquuuuuux)",
        "重音Teto": "kasane_teto_(utau)",
      };
      const phase4Tag = reverseTargets[query];
      if (phase4Tag) {
        sendJson(response, 200, {
          success: true,
          query,
          results: [{
            tag: phase4Tag,
            translation_cn: phase4CharacterTranslations[phase4Tag],
            match_score: 5,
          }],
        });
        return;
      }
      sendJson(response, 200, {
        success: true,
        query: url.searchParams.get("query"),
        results: [{ tag: "hatsune_miku", translation_cn: "初音未来" }],
      });
      return;
    }
    if (url.pathname === "/danbooru_gallery/tag_catalog/categories") {
      sendJson(response, 200, {
        success: true,
        available: true,
        groups: [{
          id: 1,
          name: "人物",
          item_count: 4,
          subgroups: [{ id: 10, name: "基础", item_count: 4 }],
        }],
        preservation: {
          raw_text_unchanged: true,
          prompt_text_truncated: false,
          site_filters_accept_prompt_phrases: false,
        },
      });
      return;
    }
    if (url.pathname === "/danbooru_gallery/tag_catalog/search") {
      const query = String(url.searchParams.get("query") || "");
      const page = Number(url.searchParams.get("page") || "1");
      if (query === "blue eyes") {
        sendJson(response, 200, {
          success: true,
          available: true,
          page,
          has_more: false,
          next_cursor: null,
          items: [{
            id: 1,
            t_uuid: "uuid-blue",
            kind: "atomic_tag",
            raw_text: "blue eyes",
            gallery_tag: "blue_eyes",
            site_filterable: true,
          }],
        });
        return;
      }
      if (query === "cinematic lighting") {
        const rawText = `masterpiece, ${"very detailed cinematic lighting, ".repeat(6)}end`;
        sendJson(response, 200, {
          success: true,
          available: true,
          page,
          has_more: false,
          next_cursor: null,
          items: [{
            id: 2,
            t_uuid: "uuid-long",
            kind: "prompt_phrase",
            raw_text: rawText,
            gallery_tag: null,
            site_filterable: false,
          }],
        });
        return;
      }
      sendJson(response, 200, {
        success: true,
        available: true,
        page,
        has_more: page === 1,
        next_cursor: page === 1 ? "12" : null,
        items: page === 1
          ? [{ id: 11, kind: "atomic_tag" }, { id: 12, kind: "atomic_tag" }]
          : [{ id: 13, kind: "atomic_tag" }, { id: 14, kind: "atomic_tag" }],
      });
      return;
    }
    if (url.pathname === "/danbooru_gallery/tag_catalog/item") {
      const rawText = `masterpiece, ${"very detailed cinematic lighting, ".repeat(6)}end`;
      sendJson(response, 200, {
        success: true,
        available: true,
        item: { t_uuid: "uuid-long", kind: "prompt_phrase", raw_text: rawText },
        preservation: { raw_text_unchanged: true, prompt_text_truncated: false },
      });
      return;
    }
    if (url.pathname === "/danbooru_gallery/v2/browse") {
      const scenario = String(request.headers["x-gallery-test-scenario"] || "success");
      if (scenario === "empty") {
        sendJson(response, 200, successEnvelope(url, { items: [], pageKey: "empty-page" }));
        return;
      }
      if (scenario === "429") {
        sendJson(response, 429, errorEnvelope(url, 429, "rate_limited"), { "retry-after": "2" });
        return;
      }
      if (liveError) {
        sendJson(response, liveError.status, errorEnvelope(url, liveError.status, liveError.code));
        return;
      }
      const cursor = url.searchParams.get("cursor");
      sendJson(response, 200, successEnvelope(url, cursor
        ? { nextCursor: null, pageKey: "page-2" }
        : { nextCursor: "fixture-next-cursor", pageKey: "page-1" }));
      return;
    }
    sendJson(response, 404, { error: { code: "not_found" } });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  return {
    origin: `http://127.0.0.1:${address.port}`,
    requests,
    async close() {
      server.closeAllConnections?.();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

function runProbe(origin, mode, env = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [PROBE_PATH, origin, mode, "danbooru"], {
      env: { ...process.env, ...env },
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    const deadline = setTimeout(() => {
      child.kill();
      reject(new Error(`api_probe timed out; stderr=${stderr}`));
    }, 5000);
    child.once("close", (code) => {
      clearTimeout(deadline);
      let report;
      try {
        report = JSON.parse(stdout);
      } catch (error) {
        reject(new Error(`api_probe emitted invalid JSON: ${error.message}; stderr=${stderr}; stdout=${stdout}`));
        return;
      }
      resolve({ code, report, stderr });
    });
  });
}

test("fixture probe follows nextCursor and validates a distinct terminal second page", async (t) => {
  const mock = await startMockServer();
  t.after(() => mock.close());

  const result = await runProbe(mock.origin, "fixture");
  assert.equal(result.code, 0, result.stderr);
  const pagination = result.report.results.find(
    (row) => row.site === "danbooru" && row.operation === "pagination_next_cursor",
  );
  assert.equal(pagination?.state, "PASS");
  assert.equal(pagination?.hasNext, false);
  assert.equal(pagination?.pageKeysDiffer, true);
  for (const operation of [
    "artist_translation_mask",
    "translation_batch_categories",
    "phase4_character_translation_batch",
    "phase4_character_autocomplete",
    "phase4_character_reverse_lookup",
    "official_alias_resolution",
    "chinese_reverse_lookup",
    "weilin_catalog_categories",
    "weilin_atomic_gallery_link",
    "weilin_long_prompt_roundtrip",
    "weilin_catalog_pagination",
  ]) {
    assert.equal(
      result.report.results.find((row) => row.operation === operation)?.state,
      "PASS",
      `${operation} delivery assertion failed`,
    );
  }
  assert.ok(mock.requests.some(
    (request) => request.path === "/danbooru_gallery/v2/browse"
      && request.scenario === "success"
      && request.cursor === "fixture-next-cursor",
  ));
});

test("probe aborts an over-time fetch and reports probe_timeout", async (t) => {
  const mock = await startMockServer({ delaySystemStats: true });
  t.after(() => mock.close());

  const started = Date.now();
  const result = await runProbe(mock.origin, "fixture", {
    DANBOORU_GALLERY_PROBE_TIMEOUT_MS: "75",
  });
  assert.equal(result.code, 1);
  assert.equal(result.report.requestTimeoutMs, 75);
  const health = result.report.results.find((row) => row.operation === "system_stats");
  assert.equal(health?.state, "FAIL");
  assert.equal(health?.httpStatus, 0);
  assert.equal(health?.errorCode, "probe_timeout");
  assert.ok(Date.now() - started < 2000, "AbortController timeout did not bound the request");
});

test("live probe treats generic upstream_error as FAIL and pagination_limit 429 as ENV_BLOCKED", async (t) => {
  const upstream = await startMockServer({ liveError: { status: 502, code: "upstream_error" } });
  t.after(() => upstream.close());
  const upstreamResult = await runProbe(upstream.origin, "live");
  assert.equal(upstreamResult.code, 1);
  assert.equal(
    upstreamResult.report.results.find((row) => row.operation === "latest")?.state,
    "FAIL",
  );

  const pagination = await startMockServer({ liveError: { status: 429, code: "pagination_limit" } });
  t.after(() => pagination.close());
  const paginationResult = await runProbe(pagination.origin, "live");
  assert.equal(paginationResult.code, 0, paginationResult.stderr);
  assert.equal(
    paginationResult.report.results.find((row) => row.operation === "latest")?.state,
    "ENV_BLOCKED",
  );
});

test("delivery runner enforces process refresh and listener cleanup in its manifest and exit status", () => {
  const runner = readFileSync(new URL("../run_delivery.ps1", import.meta.url), "utf8");
  assert.match(runner, /\$server\.Refresh\(\)/);
  assert.match(runner, /serverHasExitedAfterCleanup/);
  assert.match(runner, /portReleasedByStartedPid/);
  assert.match(runner, /OwningProcess -eq \[int\]\$server\.Id/);
  assert.match(runner, /cleanupState = if \(\$cleanupSucceeded\) \{ 'PASS' \} else \{ 'FAIL' \}/);
  assert.match(runner, /if \(\$finalState -ne 'PASS'\) \{ exit 1 \}/);
});

test("delivery runner protects live SQLite state with pre/post logical snapshots", () => {
  const runner = readFileSync(new URL("../run_delivery.ps1", import.meta.url), "utf8");
  const protectedFiles = runner
    .split("$protectedPaths = @(", 2)[1]
    .split("\n)", 1)[0];

  assert.match(runner, /New-VerifiedSqliteSnapshot/);
  assert.match(runner, /-Source \$liveTagDb -Destination \$liveTagDbBeforeSnapshot/);
  assert.match(runner, /-Source \$liveTagDb -Destination \$liveTagDbAfterSnapshot/);
  assert.match(runner, /\$liveTagDbLogicalBefore\.sha256 -ne \$liveTagDbLogicalAfter\.sha256/);
  assert.match(runner, /liveTagDatabaseProtection/);
  assert.doesNotMatch(protectedFiles, /\$liveTagDb/);
});
