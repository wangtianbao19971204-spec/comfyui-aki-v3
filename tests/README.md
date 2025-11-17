# ComfyUI Impact Pack - Test Suite

Test suite for ComfyUI Impact Pack custom nodes.

## Test Structure

```
tests/
├── wildcards/           # Wildcard system tests (progressive loading, lazy loading, etc.)
│   └── README.md        # Detailed wildcard test documentation
└── workflows/           # Workflow test files (JSON)
```

## Quick Links

- **[Wildcard Tests](wildcards/README.md)** - Comprehensive wildcard system tests
- **[Workflows](workflows/)** - Test workflow definitions

## Running Tests

### Wildcard Tests

```bash
cd wildcards/

# Run all tests
for test in test_*.sh; do bash "$test"; done

# Run specific test
bash test_progressive_ondemand.sh
```

See [wildcards/README.md](wildcards/README.md) for detailed testing guide.

### Workflow Tests

Workflow test files are located in `workflows/` directory and are used by the wildcard test scripts.

## Documentation

For complete wildcard system documentation, see:
- [Wildcard System Overview](../docs/WILDCARD_SYSTEM_OVERVIEW.md)
- [Wildcard Testing Guide](../docs/WILDCARD_TESTING_GUIDE.md)
