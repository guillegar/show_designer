# Testing Guide 🧪

Show Designer Pro has **363 tests** with **92.6% coverage**. Maintaining high test quality is essential.

## Running Tests

### All Tests

```powershell
pytest tests/ -v
# Output: 363 passed in ~4-5s
```

### Specific Test File

```powershell
pytest tests/test_timeline_model.py -v
```

### Specific Test

```powershell
pytest tests/test_timeline_model.py::test_add_clip -v
```

### With Coverage

```powershell
pytest tests/ --cov=src --cov-report=html --cov-report=term
# Generates htmlcov/index.html
```

### Watch Mode

```powershell
pip install pytest-watch
ptw tests/
# Reruns on file change
```

## Writing Tests

### Test Structure

```python
# tests/test_my_feature.py

import pytest
from src.core.show_engine import ShowEngine
from src.core.timeline_model import Clip

class TestMyFeature:
    """Test my cool feature."""
    
    @pytest.fixture
    def engine(self):
        """Provide a ShowEngine instance."""
        return ShowEngine()
    
    def test_my_feature_basic(self, engine):
        """Test basic functionality."""
        result = engine.some_method()
        assert result == expected_value
    
    @pytest.mark.parametrize("input,expected", [
        (1, 2),
        (2, 4),
        (3, 6),
    ])
    def test_my_feature_parametrized(self, input, expected):
        """Test with multiple inputs."""
        assert input * 2 == expected
```

### Using Fixtures

Fixtures provide setup/teardown for tests. Define in `conftest.py`:

```python
# conftest.py

@pytest.fixture
def timeline():
    """Fresh timeline for each test."""
    from src.core.timeline_model import Timeline
    return Timeline()

@pytest.fixture
def rig():
    """Fresh rig with fixtures."""
    from src.core.fixtures import FixtureRig
    rig = FixtureRig()
    rig.add_fixture("bar_0", "wled_strip_93", universe=0)
    return rig
```

Then use in tests:

```python
def test_timeline_with_rig(timeline, rig):
    # Both are set up automatically
    ...
```

### Mocking

For external dependencies (network, files):

```python
from unittest.mock import Mock, patch

def test_with_mock():
    with patch('src.io.outputs.router.OutputRouter.send') as mock_send:
        # Code that calls OutputRouter.send()
        mock_send.assert_called_once()
```

### Assertions

```python
assert value == expected
assert value > 5
assert "text" in string
assert list_value == [1, 2, 3]
assert error_was_raised  # pytest.raises(ValueError)

# Better:
assert value == expected, f"Expected {expected}, got {value}"
```

## Test Organization

```
tests/
├── test_analyzer_service.py     # Audio analysis
├── test_channel_effects.py       # Channel effects (DMX)
├── test_curation.py              # Audio curation
├── test_dispatcher.py            # Web/MCP dispatcher
├── test_drag_create_channel.py   # UI channel clip creation
├── test_effects_render.py        # Pixel effects rendering
├── test_exporter.py              # Export formats
├── test_gdtf_loader.py           # GDTF fixture loading
├── test_generation_tools.py      # MCP generation tools
├── test_mcp_analyzer.py          # MCP analyzer tools
├── test_output_router.py         # DMX output routing
├── test_plugin_system.py         # Custom plugins
├── test_project_manager.py       # Multi-project
├── test_session.py               # Headless session
├── test_universe_assembler.py    # DMX universe assembly
├── test_web.py                   # Web API
├── conftest.py                   # Shared fixtures
└── fixtures/                     # Test data (GDTF, JSON, etc.)
```

## Coverage Goals

| Component | Current | Target |
|-----------|---------|--------|
| **src/core/** | 92% | 95%+ |
| **src/io/** | 90% | 95%+ |
| **src/mcp/** | 88% | 95%+ |
| **src/analysis/** | 91% | 95%+ |
| **Overall** | 92.6% | 95%+ |

## Adding Tests for New Features

When you add a feature:

1. **Write tests first** (TDD):
   ```powershell
   # tests/test_my_feature.py
   def test_my_feature():
       assert my_feature() == expected
   ```

2. **Implement the feature**:
   ```python
   # src/core/...
   def my_feature():
       ...
   ```

3. **Run tests**:
   ```powershell
   pytest tests/test_my_feature.py -v
   ```

4. **Check coverage**:
   ```powershell
   pytest tests/ --cov=src --cov-report=term
   # Should be >= 60%, ideally >= 92%
   ```

## Performance Tests

Some tests are computationally expensive (e.g., rendering 100+ clips):

```python
import time

@pytest.mark.slow
def test_large_timeline_performance():
    """Test rendering 1000 clips."""
    start = time.time()
    # ... code ...
    elapsed = time.time() - start
    assert elapsed < 1.0, "Should render in <1 second"
```

Run only fast tests:

```powershell
pytest tests/ -m "not slow" -v
```

## Integration Tests

Some tests verify end-to-end behavior:

```python
def test_create_and_play_show():
    """Full workflow: create clip → play → verify output."""
    engine = ShowEngine()
    engine.add_clip(start_ms=0, effect_id=1)
    engine.play()
    # Check DMX output, 3D viewer state, etc.
    assert engine.is_playing()
```

## Debugging Tests

### Print Output

```python
def test_debug():
    value = compute_something()
    print(f"Debug: {value}")  # Shows in console with -s
    assert value == expected
```

Run with output:

```powershell
pytest tests/test_my_test.py -s -v
```

### Use a Debugger

```python
def test_with_breakpoint():
    value = compute_something()
    breakpoint()  # Pauses here
    assert value == expected
```

Run with debugger:

```powershell
pytest tests/test_my_test.py -s --pdb
```

## CI/CD Tests

GitHub Actions runs all tests on push. Check `.github/workflows/ci.yml`.

Before pushing, run locally:

```powershell
pytest tests/ -v --cov=src --cov-report=term
```

All tests must pass, coverage must be >= 60%.

---

## Test Data

Test fixtures (audio files, GDTF files, etc.) are in `tests/fixtures/`.

Example:

```python
import pytest

def test_load_gdtf():
    from src.io.loaders.gdtf_profile import load_gdtf
    profile = load_gdtf("tests/fixtures/test_wash_4ch.gdtf")
    assert profile.name == "test_wash_4ch"
```

---

## Continuous Integration

Every commit triggers tests via GitHub Actions. Check `.github/workflows/ci.yml` for:

- Python version matrix
- Coverage thresholds
- Lint checks (if configured)

---

## FAQ

**Q: Test is flaky (sometimes fails)** 
A: Check for timing issues, random state, file I/O. Use `@pytest.mark.flaky(reruns=3)` temporarily, but fix the root cause.

**Q: Coverage dropped**
A: New code must have tests. Run `pytest --cov --cov-report=html` and check `htmlcov/index.html`.

**Q: How do I test async code?**
A: Use `pytest-asyncio`:
```python
@pytest.mark.asyncio
async def test_async_function():
    result = await async_function()
    assert result == expected
```

**Q: Should I mock external APIs?**
A: Yes. Mock network calls, file I/O, and external services. Keep tests fast and deterministic.

---

## Resources

- [Pytest docs](https://docs.pytest.org/)
- [Pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- [Coverage.py](https://coverage.readthedocs.io/)

---

**Happy testing!** 🧪✨
