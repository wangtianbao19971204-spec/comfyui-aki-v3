"""Batch marching squares on CUDA; return the author's CPU polyline interface.

All levels share one grid traversal. Connectivity is assembled from shared edge
identities, so a wall or a masked corner never joins unrelated contour pieces.
"""
import numpy as np


_SOURCE = r'''
__device__ long long edge_key(int a, int b, int x, int y, int w,
                              long long grid, int level) {
    const int ox[4] = {0, 1, 1, 0}, oy[4] = {0, 0, 1, 1};
    int ax=x+ox[a], ay=y+oy[a], bx=x+ox[b], by=y+oy[b];
    long long anchor;
    int slot;
    if (ay==by) { anchor=(long long)ay*w+min(ax,bx); slot=0; }
    else if (ax==bx) { anchor=(long long)min(ay,by)*w+ax; slot=1; }
    else { anchor=(long long)y*w+x; slot=(a+b==2 ? 2 : 3); }
    return ((long long)level*grid+anchor)*4+slot;
}
__device__ void vertex(int a, int b, int x, int y, double level,
                        const double* z, double* dest) {
    const int ox[4] = {0, 1, 1, 0}, oy[4] = {0, 0, 1, 1};
    if (oy[a]>oy[b] || (oy[a]==oy[b] && ox[a]>ox[b])) {
        int t=a; a=b; b=t;
    }
    double f=(level-z[a])/(z[b]-z[a]);
    dest[0]=x+ox[a]+f*(ox[b]-ox[a]);
    dest[1]=y+oy[a]+f*(oy[b]-oy[a]);
}
extern "C" __global__ void contours(
    const double* field, const unsigned char* valid, int h, int w,
    const double* levels, int nlevels, double first, double step,
    int write, long long* counts, const long long* offsets,
    long long* keys, double* points, int* level_ids) {
    long long cell=(long long)blockIdx.x*blockDim.x+threadIdx.x;
    long long ncells=(long long)(h-1)*(w-1), grid=(long long)h*w;
    if (cell>=ncells) return;
    int x=cell%(w-1), y=cell/(w-1);
    long long ids[4]={(long long)y*w+x,(long long)y*w+x+1,
                     (long long)(y+1)*w+x+1,(long long)(y+1)*w+x};
    int polygon[4], nv=0;
    double z[4], lo=1.7976931348623157e308, hi=-1.7976931348623157e308;
    for(int c=0;c<4;++c) {
        z[c]=field[ids[c]];
        if(valid[ids[c]] && isfinite(z[c])) {
            polygon[nv++]=c; lo=fmin(lo,z[c]); hi=fmax(hi,z[c]);
        }
    }
    long long count=0;
    if(nv>=3 && nlevels>0) {
        int begin=max(0,(int)floor((lo-first)/step)-1);
        int end=min(nlevels-1,(int)floor((hi-first)/step)+1);
        for(int li=begin;li<=end;++li) {
            double lv=levels[li];
            int aa[4],bb[4],ne=0;
            for(int c=0;c<nv;++c) {
                int a=polygon[c], b=polygon[(c+1)%nv];
                if((z[a]>lv)!=(z[b]>lv)) { aa[ne]=a; bb[ne++]=b; }
            }
            if(ne!=2 && ne!=4) continue;
            int pair[4]={0,1,2,3};
            if(ne==4) {
                int bits=0;
                for(int c=0;c<4;++c) if(z[c]>lv) bits|=1<<c;
                double middle=(z[0]+z[1]+z[2]+z[3])*0.25;
                bool adjacent=(bits==5 && middle>lv)||(bits==10 && middle<=lv);
                if(!adjacent) { pair[1]=3; pair[2]=1; pair[3]=2; }
            }
            for(int j=0;j<ne;j+=2) {
                if(write) {
                    long long dst=offsets[cell]+count;
                    for(int e=0;e<2;++e) {
                        int k=pair[j+e];
                        keys[dst*2+e]=edge_key(aa[k],bb[k],x,y,w,grid,li);
                        vertex(aa[k],bb[k],x,y,lv,z,points+dst*4+e*2);
                    }
                    level_ids[dst]=li;
                }
                ++count;
            }
        }
    }
    if(!write) counts[cell]=count;
}
'''


def _trace(partner, segment_levels):
    """Trace degree-two edge graphs without rounding floating-point coordinates."""
    n = len(segment_levels)
    visited = np.zeros(n, np.uint8)
    vertices = np.empty(3 * n + 1, np.int64)
    offsets = np.empty(n + 1, np.int64)
    levels = np.empty(n, np.int32)
    used = 0
    paths = 0
    for phase in range(2):
        for start in range(2 * n):
            if visited[start // 2] or (phase == 0 and partner[start] >= 0):
                continue
            offsets[paths] = used
            levels[paths] = segment_levels[start // 2]
            vertices[used] = start
            used += 1
            current = start
            while not visited[current // 2]:
                visited[current // 2] = 1
                opposite = current ^ 1
                vertices[used] = opposite
                used += 1
                following = partner[opposite]
                if following < 0:
                    break
                current = following
            paths += 1
    offsets[paths] = used
    return vertices[:used], offsets[:paths + 1], levels[:paths]


_tracer = None


def _assemble(keys, points, level_ids, nlevels):
    global _tracer
    count = len(level_ids)
    result = [[] for _ in range(nlevels)]
    if not count:
        return result
    flat = keys.reshape(-1)
    order = np.argsort(flat, kind='stable')
    equal = flat[order[:-1]] == flat[order[1:]]
    if np.any(equal[:-1] & equal[1:]):
        raise ValueError('Contour edge has more than two owners')
    partner = np.full(2 * count, -1, np.int64)
    left, right = order[:-1][equal], order[1:][equal]
    partner[left], partner[right] = right, left
    if _tracer is None:
        try:
            import numba
            # Keep compilation in process; plugin source directories may be
            # read-only and must not acquire runtime cache artifacts.
            _tracer = numba.njit(cache=False)(_trace)
        except ImportError:
            _tracer = _trace
    indices, offsets, path_levels = _tracer(partner, level_ids)
    xy = points.reshape(-1, 2)
    for k, level in enumerate(path_levels):
        result[level].append(xy[indices[offsets[k]:offsets[k + 1]]])
    return result


class Contours:
    def __init__(self, field, valid, levels, cp):
        self.levels = np.asarray(levels, np.float64)
        self._lines = [[] for _ in levels]
        if len(levels) < 2:
            # The upstream phase solver normally has hundreds of levels. Use
            # its exact degenerate-grid behavior for a zero/one-level request.
            import contourpy
            gen = contourpy.contour_generator(z=np.ma.array(field, mask=~valid))
            self._lines = [gen.lines(float(level)) for level in levels]
            return
        h, w = field.shape
        cells = (h - 1) * (w - 1)
        if cells <= 0:
            return
        z = cp.asarray(field, dtype=cp.float64, order='C')
        mask = cp.asarray(valid, dtype=cp.uint8, order='C')
        lev = cp.asarray(self.levels)
        counts = cp.empty(cells, cp.int64)
        offsets = cp.empty(cells, cp.int64)
        unused = cp.empty(1, cp.int64)
        unused_points = cp.empty(1, cp.float64)
        unused_levels = cp.empty(1, cp.int32)
        kernel = cp.RawKernel(_SOURCE, 'contours', options=('--std=c++17',))
        launch = ((cells + 255) // 256,), (256,)
        prefix = (z, mask, np.int32(h), np.int32(w), lev, np.int32(len(levels)),
                  np.float64(levels[0]), np.float64(levels[1] - levels[0]))
        kernel(*launch, prefix + (np.int32(0), counts, offsets, unused, unused_points, unused_levels))
        cumulative = cp.cumsum(counts)
        total = int(cumulative[-1].get())
        if total > max(1024, 16 * cells):
            raise ValueError('Contour segment budget exceeded')
        offsets[0] = 0
        offsets[1:] = cumulative[:-1]
        keys = cp.empty((total, 2), cp.int64)
        points = cp.empty((total, 2, 2), cp.float64)
        level_ids = cp.empty(total, cp.int32)
        kernel(*launch, prefix + (np.int32(1), counts, offsets, keys, points, level_ids))
        self._lines = _assemble(keys.get(), points.get(), level_ids.get(), len(levels))

    def lines(self, level):
        k = int(np.searchsorted(self.levels, level))
        if k >= len(self.levels) or self.levels[k] != level:
            raise ValueError('Contour level differs from the validated batch')
        return self._lines[k]
