import { describe, it, beforeEach, afterEach, expect, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  toast: vi.fn(), reload: vi.fn(), store: vi.fn(),
  state: {
    currentPageType: 'loras',
    loadingManager: { showSimpleLoading: vi.fn(), hide: vi.fn() },
    virtualScroller: { updateSingleItem: vi.fn(() => true) },
  },
  page: { previewVersions: new Map() },
}));

vi.mock('../../../static/js/state/index.js', () => ({
  state: mocks.state, getCurrentPageState: () => mocks.page,
}));
vi.mock('../../../static/js/utils/uiHelpers.js', () => ({ showToast: mocks.toast }));
vi.mock('../../../static/js/utils/i18nHelpers.js', () => ({
  translate: (key, params, fallback) => fallback || key,
}));
vi.mock('../../../static/js/utils/storageHelpers.js', () => ({
  getStorageItem: vi.fn(), getSessionItem: vi.fn(), removeSessionItem: vi.fn(),
  saveMapToStorage: mocks.store,
}));
vi.mock('../../../static/js/api/apiConfig.js', () => ({
  getCompleteApiConfig: () => ({ endpoints: {
    replacePreview: '/api/lm/loras/replace-preview',
    setPreviewFromUrl: '/api/lm/loras/set-preview-from-url',
  } }),
  getCurrentModelType: () => 'loras', isValidModelType: () => true,
  DOWNLOAD_ENDPOINTS: {}, HF_ENDPOINTS: {}, MODEL_SOURCE_ENDPOINTS: {}, WS_ENDPOINTS: {},
}));
vi.mock('../../../static/js/api/modelApiFactory.js', () => ({ resetAndReload: mocks.reload }));
vi.mock('../../../static/js/components/SidebarManager.js', () => ({ sidebarManager: {} }));

import { BaseModelApiClient } from '../../../static/js/api/baseModelApi.js';
class TestClient extends BaseModelApiClient {}
const path = '/models/anima/画风/示例.safetensors';
const preview = { success: true, preview_url: '/preview/示例.webp', preview_nsfw_level: 2 };
let client;

beforeEach(() => {
  vi.clearAllMocks();
  mocks.page.previewVersions.clear();
  mocks.state.currentPageType = 'loras';
  mocks.state.virtualScroller = { updateSingleItem: vi.fn(() => true) };
  mocks.reload.mockResolvedValue(undefined);
  client = new TestClient('loras');
  vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function respond(status, body, contentType = 'application/json') {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300, status,
    headers: { get: () => contentType },
    json: async () => body, text: async () => body,
  }));
}
function upload() {
  return client.uploadPreview(path, new File(['fixture'], '预览.png', { type: 'image/png' }), 2);
}

describe('preview upload response and card refresh', () => {
  it('posts the selected file and updates the card with a cache-busting version', async () => {
    respond(200, preview);
    expect(await upload()).toEqual(preview);
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe('/api/lm/loras/replace-preview');
    expect([...options.body.keys()]).toEqual(['preview_file', 'model_path', 'nsfw_level']);
    expect(options.body.get('model_path')).toBe(path);
    expect(options.body.get('preview_file').name).toBe('预览.png');
    expect(mocks.state.virtualScroller.updateSingleItem).toHaveBeenCalledWith(path, {
      preview_url: preview.preview_url, preview_nsfw_level: 2,
    });
    expect(mocks.page.previewVersions.has(path)).toBe(true);
    expect(mocks.store).toHaveBeenCalledWith('loras_preview_versions', mocks.page.previewVersions);
    expect(mocks.state.loadingManager.hide).toHaveBeenCalledOnce();
  });

  it.each([
    [500, 'Disk write denied', 'text/plain'],
    [400, { success: false, error: 'Unsupported image format' }, 'application/json'],
    [200, { success: false, error: 'Metadata could not be saved' }, 'application/json'],
  ])('shows the server error for status %s without a success toast', async (status, body, type) => {
    respond(status, body, type);
    expect(await upload()).toBe(false);
    const detail = typeof body === 'string' ? body : body.error;
    expect(mocks.toast).toHaveBeenCalledWith(expect.stringContaining(detail), {}, 'error');
    expect(mocks.toast).not.toHaveBeenCalledWith('toast.api.previewUpdated', {}, 'success');
    expect(mocks.page.previewVersions.size).toBe(0);
    expect(mocks.state.virtualScroller.updateSingleItem).not.toHaveBeenCalled();
  });

  it('reports only the HTTP status for an HTML error page', async () => {
    respond(413, '<html>private proxy error</html>', 'text/html');
    expect(await upload()).toBe(false);
    expect(mocks.toast).toHaveBeenCalledWith(expect.stringContaining('HTTP 413'), {}, 'error');
    expect(mocks.toast.mock.calls[0][0]).not.toContain('<html>');
  });

  it('reloads when the saved model has disappeared from the rendered list', async () => {
    respond(200, preview);
    mocks.state.virtualScroller.updateSingleItem.mockReturnValue(false);
    const reload = vi.spyOn(client, 'loadMoreWithVirtualScroll').mockResolvedValue(undefined);
    expect(await upload()).toEqual(preview);
    expect(reload).toHaveBeenCalledWith(true, false);
  });

  it.each(['navigation', 'list rebuild'])('ignores a pending preview reload after %s', async (change) => {
    respond(200, preview);
    const original = mocks.state.virtualScroller;
    original.updateSingleItem.mockReturnValue(false);
    original.refreshWithData = vi.fn();
    let finishFetch;
    vi.spyOn(client, 'fetchModelsPage').mockImplementation(() => new Promise(resolve => { finishFetch = resolve; }));
    const pending = upload();
    await vi.waitFor(() => expect(finishFetch).toBeTypeOf('function'));
    if (change === 'navigation') mocks.state.currentPageType = 'checkpoints';
    mocks.state.virtualScroller = { refreshWithData: vi.fn() };
    finishFetch({ items: [{ file_path: path }], totalItems: 1, hasMore: false });
    expect(await pending).toEqual(preview);
    expect(original.refreshWithData).not.toHaveBeenCalled();
    expect(mocks.state.virtualScroller.refreshWithData).not.toHaveBeenCalled();
  });

  it('does not update a different model page opened while uploading', async () => {
    respond(200, preview);
    mocks.state.currentPageType = 'checkpoints';
    expect(await upload()).toEqual(preview);
    expect(mocks.state.virtualScroller.updateSingleItem).not.toHaveBeenCalled();
    expect(mocks.reload).not.toHaveBeenCalled();
    expect(mocks.page.previewVersions.has(path)).toBe(true);
  });

  it('rejects a success response that has no saved preview URL', async () => {
    respond(200, { success: true });
    expect(await upload()).toBe(false);
    expect(mocks.page.previewVersions.size).toBe(0);
  });

  it('uses the same response checks and refresh for a preview URL', async () => {
    respond(200, preview);
    expect(await client.setPreviewFromUrl(path, 'https://example.com/preview.png', 2)).toEqual(preview);
    expect(mocks.state.virtualScroller.updateSingleItem).toHaveBeenCalledWith(path, {
      preview_url: preview.preview_url, preview_nsfw_level: 2,
    });
  });
});
