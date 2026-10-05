const OPTIONAL_STRING_FIELDS = Object.freeze([
  "query",
  "metric",
  "period",
  "anchorDate",
  "facetKind",
  "facetId",
  "safetyProfile",
]);

export const QUERY_KEY_FIELDS = Object.freeze([
  "source",
  "view",
  "query",
  "metric",
  "period",
  "anchorDate",
  "facetKind",
  "facetId",
  "safetyProfile",
  "pageSize",
  "allowApprox",
]);

function requireObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
}

function normalizeIdentifier(value, field) {
  if (typeof value !== "string" || !value.trim()) {
    throw new TypeError(`${field} must be a non-empty string`);
  }
  return value.trim().toLowerCase();
}

function normalizeOptionalString(value, field) {
  if (value === undefined || value === null) return null;
  if (field === "facetId" && (typeof value === "number" || typeof value === "bigint")) {
    return String(value);
  }
  if (typeof value !== "string") {
    throw new TypeError(`${field} must be a string, number-like facet id, or null`);
  }
  const normalized = value.trim();
  return normalized || null;
}

function normalizePageSize(value) {
  const normalized = value === undefined || value === null ? 20 : Number(value);
  if (!Number.isSafeInteger(normalized) || normalized < 1 || normalized > 200) {
    throw new RangeError("pageSize must be an integer between 1 and 200");
  }
  return normalized;
}

function normalizeAllowApprox(value) {
  if (value === undefined || value === null) return false;
  if (typeof value !== "boolean") {
    throw new TypeError("allowApprox must be a boolean");
  }
  return value;
}

/**
 * Convert persisted query fields to one cross-runtime representation.
 * Optional values are represented by null rather than being omitted so that
 * browser and Python test vectors cannot disagree about undefined fields.
 */
export function normalizeQueryKeyInput(input) {
  requireObject(input, "query input");
  const normalized = {
    source: normalizeIdentifier(input.source, "source"),
    view: normalizeIdentifier(input.view, "view"),
  };
  for (const field of OPTIONAL_STRING_FIELDS) {
    normalized[field] = normalizeOptionalString(input[field], field);
  }
  normalized.pageSize = normalizePageSize(input.pageSize);
  normalized.allowApprox = normalizeAllowApprox(input.allowApprox);
  return normalized;
}

function canonicalizeValue(value, ancestors) {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("canonical JSON rejects non-finite numbers");
    return Object.is(value, -0) ? 0 : value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => item === undefined ? null : canonicalizeValue(item, ancestors));
  }
  if (typeof value !== "object" || value === undefined) {
    throw new TypeError(`canonical JSON cannot encode ${typeof value}`);
  }
  if (ancestors.has(value)) throw new TypeError("canonical JSON rejects circular values");
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError("canonical JSON only accepts plain objects");
  }
  ancestors.add(value);
  try {
    const result = {};
    for (const key of Object.keys(value).sort()) {
      if (value[key] !== undefined) result[key] = canonicalizeValue(value[key], ancestors);
    }
    return result;
  } finally {
    ancestors.delete(value);
  }
}

export function canonicalJson(value) {
  return JSON.stringify(canonicalizeValue(value, new Set()));
}

export function canonicalQueryJson(input) {
  return canonicalJson(normalizeQueryKeyInput(input));
}

const SHA256_CONSTANTS = Object.freeze([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotateRight(value, bits) {
  return (value >>> bits) | (value << (32 - bits));
}

/** Pure-JS fallback for browsers where SubtleCrypto is unavailable on HTTP. */
export function sha256HexPortable(text) {
  if (typeof text !== "string") throw new TypeError("sha256HexPortable input must be a string");
  const bytes = new TextEncoder().encode(text);
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const bitLength = bytes.length * 8;
  const view = new DataView(padded.buffer);
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000), false);
  view.setUint32(paddedLength - 4, bitLength >>> 0, false);

  const hash = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const words = new Uint32Array(64);
  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(offset + index * 4, false);
    }
    for (let index = 16; index < 64; index += 1) {
      const x = words[index - 15];
      const y = words[index - 2];
      const sigma0 = rotateRight(x, 7) ^ rotateRight(x, 18) ^ (x >>> 3);
      const sigma1 = rotateRight(y, 17) ^ rotateRight(y, 19) ^ (y >>> 10);
      words[index] = (words[index - 16] + sigma0 + words[index - 7] + sigma1) >>> 0;
    }

    let [a, b, c, d, e, f, g, h] = hash;
    for (let index = 0; index < 64; index += 1) {
      const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temp1 = (h + sum1 + choose + SHA256_CONSTANTS[index] + words[index]) >>> 0;
      const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (sum0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }
    hash[0] = (hash[0] + a) >>> 0;
    hash[1] = (hash[1] + b) >>> 0;
    hash[2] = (hash[2] + c) >>> 0;
    hash[3] = (hash[3] + d) >>> 0;
    hash[4] = (hash[4] + e) >>> 0;
    hash[5] = (hash[5] + f) >>> 0;
    hash[6] = (hash[6] + g) >>> 0;
    hash[7] = (hash[7] + h) >>> 0;
  }
  return Array.from(hash, (word) => word.toString(16).padStart(8, "0")).join("");
}

export async function sha256Hex(text, { subtle = globalThis.crypto?.subtle } = {}) {
  if (typeof text !== "string") throw new TypeError("sha256Hex input must be a string");
  if (subtle) {
    try {
      const digest = await subtle.digest("SHA-256", new TextEncoder().encode(text));
      return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
    } catch {
      // Some non-secure browser contexts expose crypto but reject subtle calls.
    }
  }
  return sha256HexPortable(text);
}

export async function createCanonicalQueryKey(input) {
  return sha256Hex(canonicalQueryJson(input));
}

function portableUuidV4() {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  if (typeof globalThis.crypto?.getRandomValues !== "function") {
    throw new Error("secure random UUID generation is unavailable in this runtime");
  }
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

export function createClientRequestId(idFactory) {
  const factory = idFactory ?? portableUuidV4;
  if (typeof factory !== "function") throw new TypeError("idFactory must be a function");
  const id = factory();
  if (!isUuidV4(id)) throw new TypeError("clientRequestId must be a UUID v4");
  return id.toLowerCase();
}

export function isUuidV4(value) {
  return typeof value === "string"
    && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}
