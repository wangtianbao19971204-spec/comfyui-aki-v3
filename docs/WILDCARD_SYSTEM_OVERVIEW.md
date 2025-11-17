# Wildcard System - Complete Overview

**ComfyUI Impact Pack Wildcard System** - Comprehensive documentation for design, implementation, and usage.

---

## 📚 Documentation Index

### Core Documentation
1. **[System Overview](#system-overview)** (This document) - Complete system architecture
2. **[Testing Guide](WILDCARD_TESTING_GUIDE.md)** - Comprehensive testing documentation
3. **[Progressive Loading](../tests/README_PROGRESSIVE_ONDEMAND.md)** - Progressive on-demand loading
4. **[Design Document](DESIGN_WILDCARD_SYSTEM.md)** - Original design specifications
5. **[PRD](PRD_WILDCARD_SYSTEM.md)** - Product requirements

### Quick Links
- **[Quick Start](#quick-start)** - Get started in 5 minutes
- **[API Reference](#api-reference)** - All API endpoints
- **[Configuration](#configuration)** - System configuration
- **[Performance](#performance)** - Performance characteristics
- **[Troubleshooting](#troubleshooting)** - Common issues

---

## System Overview

### What is the Wildcard System?

The wildcard system provides **dynamic text generation** for AI prompts using:
- **Wildcards**: Reusable text snippets (`__wildcard_name__`)
- **Dynamic Prompts**: Runtime options (`{option1|option2}`)
- **Weighted Selection**: Probability control (`{3::high|1::low}`)
- **Transitive References**: Nested wildcards

### Key Features

#### 1. **Progressive On-Demand Loading** ⭐ NEW
- **Metadata scan only** on startup (< 1 minute for 10GB+)
- **Load data on-demand** as wildcards are accessed
- **Memory efficient**: < 100MB initial, grows progressively
- **Scalable**: Supports tens of gigabytes of wildcard data

#### 2. **Automatic Mode Detection**
- **Full Cache Mode**: < 50MB total → Load all data upfront
- **On-Demand Mode**: ≥ 50MB total → Progressive loading

#### 3. **High Performance**
- **Early termination**: Size calculation stops at cache limit
- **Fast startup**: Metadata scan in seconds (vs minutes for full load)
- **Low memory**: Only loaded wildcards consume memory

#### 4. **Feature-Rich Syntax**
- Dynamic prompts, weighted selection, multi-select
- Quantifiers, transitive wildcards, YAML support
- Deterministic (seeded) generation

---

## Quick Start

### 1. Installation

```bash
cd /path/to/ComfyUI/custom_nodes
git clone <impact-pack-repo> comfyui-impact-pack
cd comfyui-impact-pack
pip install -r requirements.txt
```

### 2. Configuration

**Edit** `impact-pack.ini`:
```ini
[default]
wildcard_cache_limit_mb = 50  # Auto on-demand if total size ≥ 50MB
custom_wildcards = /path/to/custom/wildcards
```

### 3. Basic Usage

**Create wildcard file** `wildcards/flowers.txt`:
```
rose
tulip
sunflower
```

**Use in prompt**:
```
a beautiful __flowers__
→ "a beautiful rose"
```

**Dynamic selection**:
```
a {red|blue|yellow} __flowers__
→ "a red tulip"
```

### 4. Check Mode

**Start ComfyUI and check logs**:
```
[Impact Pack] Wildcard total size (45.32 MB) is within cache limit (50.00 MB).
Using full cache mode.
```

or

```
[Impact Pack] Wildcard total size (125.67 MB) exceeds cache limit (50.00 MB).
Using on-demand loading mode (metadata scan only).
```

---

## Architecture

### Two-Phase Loading System

```
┌─────────────────────────────────────────────────────────────┐
│                    Startup (wildcard_load)                   │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Calculate size (with early termination)                  │
│     ├─ Scan files: < 1 second                                │
│     └─ Stop at cache_limit (if exceeded)                     │
│                                                               │
│  2. Determine mode                                           │
│     ├─ size < limit → Full Cache Mode                        │
│     └─ size ≥ limit → On-Demand Mode                         │
│                                                               │
├─────────────────────────────────────────────────────────────┤
│                     Full Cache Mode                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  • Load ALL wildcard data into memory                        │
│  • Fast access (all data pre-loaded)                         │
│  • Higher memory usage                                       │
│  • Best for: < 50MB total wildcard data                      │
│                                                               │
├─────────────────────────────────────────────────────────────┤
│                     On-Demand Mode ⭐ NEW                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Phase 1: YAML Pre-loading (startup)                         │
│  ├─ Scan and load ALL YAML files                             │
│  ├─ Reason: Keys are inside file content, not file path      │
│  └─ Memory: Minimal (YAML files are typically small)         │
│                                                               │
│  Phase 2: TXT On-Demand Loading (runtime)                    │
│  ├─ TXT files: Load data when accessed                       │
│  ├─ File path = key (e.g., "flower.txt" → "__flower__")      │
│  ├─ Cache: loaded_wildcards = {key: data}                    │
│  └─ Memory: grows progressively                              │
│                                                               │
│  ⚠️ YAML Limitation:                                          │
│  YAML wildcards excluded from on-demand loading.             │
│  Keys like "colors/warm" exist inside "colors.yaml" content. │
│  Must parse entire file to discover available keys.          │
│                                                               │
│  Best for: ≥ 50MB (especially 10GB+ of TXT wildcards)        │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User Request
    │
    ▼
┌─────────────────────┐
│  /impact/wildcards  │ ← POST {"text": "__flower__", "seed": 42}
└──────────┬──────────┘
           │
           ▼
    ┌──────────────┐
    │   process()  │
    └──────┬───────┘
           │
           ▼
    ┌─────────────────────┐
    │ get_wildcard_value  │
    └──────┬──────────────┘
           │
           ▼
    ┌─────────────────────────────────┐
    │  On-Demand Mode?                │
    ├─────────────────────────────────┤
    │ Yes → Load from file (if new)   │
    │ No  → Use wildcard_dict         │
    └──────┬──────────────────────────┘
           │
           ▼
    ┌─────────────────────┐
    │ Cache in            │
    │ loaded_wildcards    │
    └──────┬──────────────┘
           │
           ▼
    ┌─────────────────────┐
    │ Return data         │
    └──────────────────────┘
```

---

## API Reference

### GET `/impact/wildcards/list`

Get all **available** wildcards (discovered in metadata scan or loaded in full cache).

**Response**:
```json
{
  "data": [
    "__samples/flower__",
    "__samples/tree__",
    "__dragon__",
    "__colors__"
  ]
}
```

**Behavior**:
- **Full cache**: Returns all loaded wildcards
- **On-demand**: Returns all discovered wildcards (from metadata scan)

---

### GET `/impact/wildcards/list/loaded` ⭐ NEW

Get **actually loaded** wildcards (progressive loading tracking).

**Response**:
```json
{
  "data": [
    "__samples/flower__",
    "__dragon__"
  ],
  "on_demand_mode": true,
  "total_available": 1000
}
```

**Fields**:
- `data`: List of loaded wildcards
- `on_demand_mode`: `true` if on-demand mode active
- `total_available`: Total discovered wildcards

**Behavior**:
- **Full cache**: Same as `/list` (all loaded)
- **On-demand**: Returns only loaded wildcards (**increases progressively**)

**Progressive Example**:
```
Initial:
GET /list/loaded → {"data": [], "total_available": 1000}

After __flower__:
GET /list/loaded → {"data": ["__samples/flower__"], "total_available": 1000}

After __dragon__:
GET /list/loaded → {"data": ["__samples/flower__", "__dragon__", ...], "total_available": 1000}
```

---

### POST `/impact/wildcards`

Process wildcard text and return populated result.

**Request**:
```json
{
  "text": "a {red|blue} __samples/flower__",
  "seed": 42
}
```

**Response**:
```json
{
  "text": "a red rose"
}
```

**Behavior**:
- Processes all wildcards and dynamic prompts
- **Triggers on-demand loading** if wildcard not loaded
- Deterministic with same seed

---

### GET `/impact/wildcards/refresh`

Reload all wildcards (clears cache).

**Response**: `200 OK`

**Behavior**:
- Re-scans wildcard directories
- Clears both `wildcard_dict` and `loaded_wildcards`
- Re-determines full cache vs on-demand mode

---

## Configuration

### impact-pack.ini

```ini
[default]
# Cache limit in MB (default: 50)
wildcard_cache_limit_mb = 50

# Custom wildcards directory (optional)
custom_wildcards = /path/to/custom/wildcards

# Other settings
dependency_version = 24
mmdet_skip = True
sam_editor_cpu = False
disable_gpu_opencv = True
```

### Environment Variables

None currently used.

### Runtime Configuration

**Mode is determined at startup** based on total wildcard size:
```python
if total_size >= cache_limit:
    # On-demand mode
else:
    # Full cache mode
```

**To force on-demand mode** for testing:
```ini
wildcard_cache_limit_mb = 0.5  # Very low limit
```

**To force full cache mode**:
```ini
wildcard_cache_limit_mb = 10000  # Very high limit
```

---

## Performance

### Startup Performance

**Small Dataset (< 50MB)**:
```
Full Cache Mode
├─ Size calculation: 0.1-1 second
├─ Data loading: 1-5 seconds
└─ Total: < 10 seconds
```

**Large Dataset (10GB, 100K files)**:

**Before (Old "On-Demand")**:
```
├─ Size calculation: 10-30 minutes (full scan)
├─ Data loading: 10-30 minutes (LazyLoader setup)
└─ Total: 20-60 minutes ❌
```

**After (True On-Demand)** ⭐:
```
On-Demand Mode
├─ Size calculation: < 1 second (early termination)
├─ Metadata scan: 5-30 seconds (file paths only)
└─ Total: < 1 minute ✅
```

### Runtime Performance

| Operation | Full Cache | On-Demand (Old) | On-Demand (New) |
|-----------|------------|-----------------|-----------------|
| **First access** | Instant | Instant (lazy) | 10-50ms (file load) |
| **Cached access** | Instant | Instant | Instant |
| **Memory growth** | All upfront | All upfront (keys) | **Progressive** ✅ |
| **/list API** | Instant | Instant | Instant |
| **/list/loaded API** | N/A | N/A | **Instant** ✅ |

### Memory Usage

**Full Cache Mode**:
```
Memory = Total wildcard data size
Example: 45MB wildcards → ~45MB memory
```

**On-Demand Mode (Old)**:
```
Memory = All LazyWildcardLoader objects
Example: 100K files → ~500MB-1GB memory ❌
```

**On-Demand Mode (New)** ⭐:
```
Initial: < 100MB (metadata only)
Growth: + size of loaded wildcards
Example:
  - Initial: 50MB (100K file paths)
  - After 10 accesses: 55MB (+5MB data)
  - After 100 accesses: 100MB (+50MB data) ✅
```

### Performance Optimization Tips

1. **Use on-demand mode for large datasets** (≥ 50MB)
2. **Monitor `/list/loaded`** to track memory usage
3. **Organize wildcards** into subdirectories for better file system performance
4. **Use SSD** for faster file I/O
5. **Adjust cache limit** based on your use case:
   - More memory available → Higher limit → Full cache
   - Less memory available → Lower limit → On-demand

---

## Wildcard Syntax

### Basic Wildcards

```
__wildcard_name__        → Random selection from wildcard file
__folder/wildcard__      → Wildcard in subdirectory
```

### Dynamic Prompts

```
{option1|option2|option3}              → Random selection
{red|green|blue} flower                → "red flower"
```

### Weighted Selection

```
{3::common|1::rare}                    → 75% common, 25% rare
{50::very_common|10::uncommon|1::rare} → Probability distribution
```

### Multi-Select

```
{2$$, $$opt1|opt2|opt3}         → Select 2, comma separated
{3$$; $$opt1|opt2|opt3|opt4}    → Select 3, semicolon separated
{2-4$$, $$opt1|opt2|opt3|opt4}  → Select 2 to 4 randomly
```

### Quantifiers

```
3#__wildcard__              → Expand wildcard 3 times
{2$$, $$5#__colors__}       → Select 2 from 5 color expansions
```

### Nested Syntax

```
{red|blue} {__flowers__|__trees__}     → Nested wildcards
{3::{big|small}|tiny} __animals__     → Nested with weights
```

### Transitive Wildcards

**Wildcards can reference other wildcards**:

`dragon.txt`:
```
__dragon/warrior__
__dragon/spirit__
```

`dragon/warrior.txt`:
```
fierce dragon warrior
ancient dragon knight
```

**Usage**:
```
__dragon__
→ __dragon/warrior__
→ "fierce dragon warrior"
```

**Maximum depth**: 100 iterations (verified up to depth 3)

---

## File Formats

### TXT Wildcards

**Format**: One option per line
```
# flowers.txt
rose
tulip
# Comments start with #
sunflower
daisy
```

**Features**:
- Simple list format
- Comments supported (`#`)
- Blank lines ignored

### YAML Wildcards

**Format**: Nested structure
```yaml
# colors.yaml
warm:
  - red
  - orange
  - yellow

cold:
  - blue
  - green
  - purple
```

**Usage**:
```
__colors/warm__  → "red" or "orange" or "yellow"
__colors/cold__  → "blue" or "green" or "purple"
```

**Features**:
- Hierarchical organization
- Multiple levels supported
- String, list, or numeric values

**⚠️ On-Demand Limitation**:
YAML wildcards are **excluded from on-demand mode** and always pre-loaded at startup.

**Reason**: Wildcard keys are embedded inside the file content, not in the file path.

**Example**:
```
TXT file:  "samples/flower.txt" → Key is "__samples/flower__" (path = key) ✅
YAML file: "colors.yaml" contains:
             warm: [red, orange]    → Key is "__colors/warm__"
             cold: [blue, green]    → Key is "__colors/cold__"
```

To discover that `__colors/warm__` exists, we must parse `colors.yaml` completely.
Therefore, YAML files cannot be truly on-demand loaded.

**Impact**: YAML files are pre-loaded at startup in on-demand mode.
This is typically not an issue since YAML files are:
- Few in number (configuration/organizational use)
- Small in size (compared to TXT wildcard collections)

**Solution**: If you want true on-demand loading for large wildcard collections,
convert YAML wildcards to path-based TXT file structure:

```bash
# YAML structure (pre-loaded)
colors.yaml:
  warm: [red, orange, yellow]
  cold: [blue, green, purple]

# Convert to TXT structure (on-demand)
colors/warm.txt:
  red
  orange
  yellow

colors/cold.txt:
  blue
  green
  purple
```

With TXT structure, only accessed wildcards are loaded:
- `__colors/warm__` → loads only `colors/warm.txt`
- `__colors/cold__` → loads only `colors/cold.txt`

---

## Troubleshooting

### On-Demand Mode Not Activating

**Check logs**:
```
[Impact Pack] Wildcard total size (45.32 MB) is within cache limit (50.00 MB).
Using full cache mode.
```

**Solutions**:
1. Lower cache limit: `wildcard_cache_limit_mb = 0.5`
2. Add more wildcards to exceed limit
3. Verify wildcards directory path is correct

---

### High Memory Usage

**Check mode and loaded wildcards**:
```bash
curl http://127.0.0.1:8188/impact/wildcards/list/loaded
```

**Expected**:
- Full cache: Memory ≈ total wildcard size
- On-demand: Memory = metadata + loaded wildcards

**If higher than expected**:
1. Verify on-demand mode is active
2. Check `/list/loaded` count
3. Look for memory leaks in logs
4. Restart server to clear cache

---

### Slow First Access

**Expected in on-demand mode**: 10-50ms to load file

**If slower**:
1. Check disk I/O (SSD recommended)
2. Verify file system is not network-mounted
3. Check wildcard file size (large files take longer)

---

### Results Inconsistent Between Modes

**Should never happen** - if it does:

1. **File a bug report** with:
   - Wildcard text
   - Seed value
   - Full cache result
   - On-demand result
   - Logs

2. **Workaround**: Use full cache mode:
   ```ini
   wildcard_cache_limit_mb = 10000  # High limit
   ```

---

## Migration Guide

### From Old "On-Demand" to True On-Demand

**No code changes required!** System automatically uses new implementation.

**What changed**:
- ✅ Faster startup (< 1 min vs 20-60 min for large datasets)
- ✅ Lower memory (< 100MB vs GB for large datasets)
- ✅ Progressive loading tracking via `/list/loaded`

**What stayed the same**:
- ✅ API endpoints (except new `/list/loaded`)
- ✅ Wildcard syntax
- ✅ Deterministic behavior
- ✅ Full cache mode unchanged

### Upgrading from Previous Versions

1. **Pull latest code**
2. **No config changes needed** (defaults work)
3. **Restart ComfyUI**
4. **Check logs** for mode activation
5. **Test** with `/list/loaded` API

---

## Best Practices

### Organization

**Recommended structure**:
```
wildcards/
├── characters/
│   ├── heroes.txt
│   ├── villains.txt
│   └── npcs.txt
├── locations/
│   ├── cities.txt
│   └── dungeons.txt
├── items/
│   └── weapons.txt
└── colors.yaml
```

**Benefits**:
- Easier to find wildcards
- Better file system performance
- Logical grouping

### Naming

**Good**:
```
__characters/heroes__
__locations/cities__
__items/weapons__
```

**Avoid**:
```
__hero__          # Unclear category
__city-name__     # Inconsistent separator
__WEAPONS__       # Case-sensitive issues
```

**Rules**:
- Use lowercase
- Use `_` or `-` for spaces
- Organize into folders
- Be descriptive

### Performance

**For large datasets (>1GB)**:
1. Use on-demand mode (automatic if > 50MB)
2. Monitor `/list/loaded` to track memory
3. Organize into subdirectories
4. Use SSD for faster I/O
5. Consider splitting very large files

**For small datasets (<50MB)**:
1. Full cache mode is fine (automatic)
2. No special optimizations needed

---

## Advanced Topics

### Custom Wildcard Directories

**Add custom directory**:
```ini
[default]
custom_wildcards = /path/to/custom/wildcards
```

**Both directories are scanned**:
- `wildcards/` (default)
- `/path/to/custom/wildcards` (custom)

**Use case**: Separate user-generated content from bundled wildcards

### Wildcard Inheritance

**Transitive wildcards** enable inheritance:

`base.txt`:
```
__derived1__
__derived2__
```

`derived1.txt`:
```
specific option A
specific option B
```

**Usage**: `__base__` → `__derived1__` → "specific option A"

---

## Development

### Adding New Features

1. **Modify** `modules/impact/wildcards.py`
2. **Add tests** in `tests/`
3. **Update documentation** in `docs/`
4. **Run test suite**: `bash tests/test_*.sh`

### Testing

See **[Testing Guide](WILDCARD_TESTING_GUIDE.md)** for comprehensive testing documentation.

**Quick test**:
```bash
bash tests/test_progressive_ondemand.sh
```

---

## References

### Documentation
- **[Testing Guide](WILDCARD_TESTING_GUIDE.md)** - Complete testing documentation
- **[Progressive Loading](../tests/README_PROGRESSIVE_ONDEMAND.md)** - Progressive on-demand loading
- **[Design Document](DESIGN_WILDCARD_SYSTEM.md)** - Design specifications
- **[PRD](PRD_WILDCARD_SYSTEM.md)** - Product requirements

### Test Documentation
- **[Lazy Load Tests](../tests/README_LAZY_LOAD_TEST.md)** - Lazy loading tests
- **[Sequential Tests](../tests/SEQUENTIAL_LOADING_TESTS.md)** - Sequential/transitive tests
- **[Versatile Prompts](../tests/VERSATILE_PROMPTS.md)** - Versatile prompt tests

### Code
- **Wildcard System**: `modules/impact/wildcards.py`
- **API Server**: `modules/impact/impact_server.py`
- **Tests**: `tests/test_*.{sh,py}`

---

## Changelog

### v3.0 - Progressive On-Demand Loading ⭐ NEW

**Added**:
- ✅ True progressive on-demand loading
- ✅ Early termination size calculation
- ✅ Metadata-only scanning
- ✅ `/impact/wildcards/list/loaded` API endpoint
- ✅ Comprehensive test suite

**Improved**:
- ✅ Startup time: 20-60 min → < 1 min (large datasets)
- ✅ Memory usage: GB → < 100MB (large datasets)
- ✅ Scalability: Supports tens of gigabytes

**Fixed**:
- ✅ Memory bloat in old "on-demand" mode
- ✅ Slow startup for large datasets

### v2.0 - Lazy Loading (Previous)

**Added**:
- LazyWildcardLoader class
- Automatic mode detection
- Cache size limits

### v1.0 - Original

**Added**:
- Basic wildcard system
- Dynamic prompts
- YAML support

---

## Support

### Getting Help

1. **Check documentation** (this file)
2. **Review [Testing Guide](WILDCARD_TESTING_GUIDE.md)**
3. **Check logs** in `/tmp/` or ComfyUI console
4. **File bug report** with:
   - ComfyUI version
   - Impact Pack version
   - Log output
   - Minimal reproduction steps

### Known Issues

None currently.

### Future Enhancements

- LRU cache with automatic eviction
- Background preloading of frequently-used wildcards
- Persistent cache across restarts
- Usage statistics and optimization recommendations
- Compression for infrequently-used wildcards

---

## License

(Include license information here)

---

**Last Updated**: 2024-11-17
**Version**: 3.0 (Progressive On-Demand Loading)
