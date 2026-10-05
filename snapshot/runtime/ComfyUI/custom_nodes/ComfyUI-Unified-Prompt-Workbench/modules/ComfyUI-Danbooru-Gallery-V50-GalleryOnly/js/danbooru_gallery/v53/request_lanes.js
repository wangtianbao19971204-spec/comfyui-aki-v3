import { createClientRequestId } from "./query_contract.js";

export const REQUEST_LANES = Object.freeze([
  "capabilities",
  "browse",
  "facets",
  "autocomplete",
]);

const RESPONSE_IDENTITY_LANES = new Set(["browse", "facets", "autocomplete"]);

function validateQueryKey(value) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw new TypeError("queryKey must be a 64-character lowercase SHA-256 hex string");
  }
  return value;
}

function responseIdentity(response) {
  if (!response || typeof response !== "object") return null;
  return {
    clientRequestId: response.clientRequestId ?? response.client_request_id,
    queryKey: response.queryKey ?? response.clientQueryKey ?? response.client_query_key,
  };
}

export class RequestLaneCoordinator {
  constructor({
    laneNames = REQUEST_LANES,
    idFactory,
    controllerFactory = () => new AbortController(),
  } = {}) {
    if (!Array.isArray(laneNames) || !laneNames.length || new Set(laneNames).size !== laneNames.length) {
      throw new TypeError("laneNames must be a non-empty array of unique names");
    }
    if (typeof controllerFactory !== "function") throw new TypeError("controllerFactory must be a function");
    this._idFactory = idFactory;
    this._controllerFactory = controllerFactory;
    this._destroyed = false;
    this._lanes = new Map(laneNames.map((name) => [name, {
      controller: null,
      seq: 0,
      clientRequestId: null,
      queryKey: null,
      status: "idle",
    }]));
  }

  _lane(name) {
    const lane = this._lanes.get(name);
    if (!lane) throw new RangeError(`unknown request lane: ${name}`);
    return lane;
  }

  begin(name, queryKey, { clientRequestId, status = "loading" } = {}) {
    if (this._destroyed) throw new Error("request coordinator is destroyed");
    const lane = this._lane(name);
    this.abort(name, "superseded");
    const controller = this._controllerFactory();
    if (!controller?.signal || typeof controller.abort !== "function") {
      throw new TypeError("controllerFactory must return an AbortController-compatible object");
    }
    lane.controller = controller;
    lane.seq += 1;
    lane.clientRequestId = clientRequestId
      ? createClientRequestId(() => clientRequestId)
      : createClientRequestId(this._idFactory);
    lane.queryKey = validateQueryKey(queryKey);
    lane.status = String(status || "loading");
    return Object.freeze({
      lane: name,
      seq: lane.seq,
      clientRequestId: lane.clientRequestId,
      queryKey: lane.queryKey,
      signal: controller.signal,
    });
  }

  canCommit(token, response) {
    if (!token || typeof token !== "object") return false;
    const lane = this._lanes.get(token.lane);
    if (!lane || !lane.controller || lane.controller.signal.aborted) return false;
    if (lane.seq !== token.seq
      || lane.clientRequestId !== token.clientRequestId
      || lane.queryKey !== token.queryKey) return false;
    if (response !== undefined) {
      const identity = responseIdentity(response);
      const hasResponseIdentity = Boolean(identity?.clientRequestId || identity?.queryKey);
      if (hasResponseIdentity || RESPONSE_IDENTITY_LANES.has(token.lane)) {
        if (!identity?.clientRequestId || !identity?.queryKey) return false;
        if (identity.clientRequestId !== lane.clientRequestId || identity.queryKey !== lane.queryKey) return false;
      }
    }
    return true;
  }

  commit(token, response, apply) {
    if (typeof apply !== "function") throw new TypeError("commit apply callback must be a function");
    if (!this.canCommit(token, response)) return false;
    const lane = this._lane(token.lane);
    try {
      apply(response);
      lane.status = "idle";
      return true;
    } catch (error) {
      lane.status = "error";
      throw error;
    } finally {
      lane.controller = null;
    }
  }

  finish(token, status = "idle") {
    if (!this.canCommit(token)) return false;
    const lane = this._lane(token.lane);
    lane.controller = null;
    lane.status = String(status);
    return true;
  }

  abort(name, reason = "aborted") {
    const lane = this._lane(name);
    if (!lane.controller) return false;
    if (!lane.controller.signal.aborted) lane.controller.abort(reason);
    lane.controller = null;
    lane.status = "idle";
    return true;
  }

  abortAll(reason = "aborted") {
    let aborted = 0;
    for (const name of this._lanes.keys()) {
      if (this.abort(name, reason)) aborted += 1;
    }
    return aborted;
  }

  destroy(reason = "node_removed") {
    if (this._destroyed) return;
    this.abortAll(reason);
    this._destroyed = true;
  }

  snapshot() {
    return Object.freeze(Object.fromEntries(Array.from(this._lanes, ([name, lane]) => [name, Object.freeze({
      seq: lane.seq,
      clientRequestId: lane.clientRequestId,
      queryKey: lane.queryKey,
      status: lane.status,
      active: Boolean(lane.controller && !lane.controller.signal.aborted),
    })])));
  }
}
