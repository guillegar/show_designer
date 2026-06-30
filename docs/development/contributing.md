# Contributing 🤝

We welcome contributions! Whether it's bugs, features, or documentation, your help makes Show Designer Pro better.

## Code of Conduct

Be respectful and constructive. This is an inclusive project for everyone.

## How to Report Bugs

### 1. Search existing issues

Visit [GitHub Issues](https://github.com/guillegar/show_designer/issues) to see if your bug is already reported.

### 2. Open a new issue

Click "New Issue" and choose "Bug Report". Fill out:

- **Title**: `[BUG] Concise description`
- **Description**: What went wrong?
- **Steps to reproduce**: How to trigger the bug
- **Expected behavior**: What should happen
- **Actual behavior**: What happens instead
- **System info**: OS, Python version, Show Designer version
- **Logs/Screenshots**: If available

**Example**:

```
[BUG] Clips disappear after save

Steps:
1. Create 3 clips on bar 0
2. Press Ctrl+S to save
3. Close and reopen the show

Expected: Clips are restored
Actual: Only 2 clips remain

System: Windows 11, Python 3.12, v1.9 F2
Logs: (attached)
```

## How to Propose Features

Open a [GitHub Discussion](https://github.com/guillegar/show_designer/discussions) instead of an Issue.

Describe:
- What problem does it solve?
- How should it work?
- Any alternatives you considered?

The maintainer (guille) will decide if it's in-scope.

## How to Contribute Code

### 1. Fork the repository

Click "Fork" on GitHub to create your own copy.

### 2. Clone your fork

```powershell
git clone https://github.com/YOUR-USERNAME/show_designer.git
cd show_designer
```

### 3. Create a branch

```powershell
git checkout -b feature/my-feature
# or
git checkout -b fix/my-bug
```

Branch naming:
- `feature/` for new features
- `fix/` for bug fixes
- `docs/` for documentation
- `test/` for tests

### 4. Install development dependencies

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 5. Make your changes

- Follow existing code style
- Keep lines under 120 characters
- No unused imports
- Comments only where non-obvious

Example:

```python
# ❌ Bad
x = 5  # Set x to 5

# ✅ Good
max_retries = 5

# ✅ Good (comment only when why is non-obvious)
# Use LTP (Highest Priority) to resolve channel conflicts
channel_value = max(active_values)
```

### 6. Write tests

Tests are **required** for new features.

```powershell
# tests/test_my_feature.py

def test_my_feature():
    from src.core import my_module
    result = my_module.my_function()
    assert result == expected
```

Run tests:

```powershell
pytest tests/test_my_feature.py -v
```

Target: >= 60% coverage, ideally >= 92%.

### 7. Test manually in the app

```powershell
python -m server.main
# Try your feature
```

### 8. Commit your changes

Write clear, descriptive commit messages:

```powershell
git add .
git commit -m "feat: add cool new feature

- Implement XYZ functionality
- Add tests for XYZ
- Update documentation"
```

Format:
- Prefix: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`
- First line: under 50 chars
- Body: explain the "why", not the "what"
- Reference issues: `Closes #123`

### 9. Push and open a PR

```powershell
git push origin feature/my-feature
```

Then on GitHub, click "Compare & pull request".

**PR title**: `[FEATURE] Cool new feature` or `[FIX] Bug fix`

**PR description**:

```markdown
## What does this do?
Add XYZ functionality to the timeline editor.

## How to test?
1. Create a new clip
2. Do XYZ
3. Verify the result is correct

## Checklist
- [x] Tests pass (363/363)
- [x] Coverage >= 60%
- [x] Documentation updated
- [x] No console errors
```

### 10. Respond to review feedback

The maintainer will review your PR. Fix any issues and push again:

```powershell
# Make changes
git add .
git commit -m "fix: address review feedback"
git push origin feature/my-feature
```

No force-push needed; we'll squash-merge when ready.

## Code Style

### Python

No strict formatter, but follow these principles:

```python
# Imports
from typing import Optional, List
from src.core.show_engine import ShowEngine

# Functions
def add_clip(
    start_ms: int,
    duration_ms: int,
    effect_id: int,
) -> Clip:
    """Create and add a clip to the timeline.
    
    Args:
        start_ms: Start time in milliseconds
        duration_ms: Duration in milliseconds
        effect_id: ID of the effect
    
    Returns:
        The created Clip object
    """
    # Implementation
    return clip

# Classes
class Timeline:
    """Multi-track timeline for clips."""
    
    def __init__(self):
        self.clips: List[Clip] = []
    
    def add_clip(self, clip: Clip) -> None:
        """Add a clip to the timeline."""
        self.clips.append(clip)
```

### TypeScript (React frontend)

```typescript
// Use TypeScript types
interface Clip {
  id: string;
  startMs: number;
  durationMs: number;
  effectId: number;
}

function Timeline({ clips }: { clips: Clip[] }) {
  return <div>{clips.length} clips</div>;
}
```

## Documentation

Update docs when adding features:

- Add to relevant `docs/*.md` file
- Update table of contents in `mkdocs.yml`
- Include examples if applicable

## Testing Requirements

**All PRs must have**:

- Tests that cover the new/changed code
- All 1043 tests pass: `pytest tests/ -v`
- Coverage >= 60% (target 92%+)

Run before committing:

```powershell
pytest tests/ --cov=src --cov-report=term
```

## Release Process (maintainer only)

When a feature is complete:

1. Commit per phase/feature (checkpoints = git; there is no `versions/` folder)
2. Tag release: `git tag v2.0`
3. Push to GitHub: `git push origin --tags`
4. Update changelog

Contributors don't need to do this—the maintainer handles releases.

## Getting Help

- 📖 Read [Development Setup](setup.md)
- 📖 Read [Architecture Guide](../advanced/architecture.md)
- 💬 [GitHub Discussions](https://github.com/guillegar/show_designer/discussions)
- 📧 Email: guille@example.com

## What's a "good first issue"?

Look for issues labeled `good first issue`. These are:

- Well-defined
- Scoped appropriately
- Suitable for newcomers

Start there to get familiar with the codebase!

---

## Examples of Good Contributions

- Fixing a bug with a test
- Adding a new effect plugin
- Improving documentation
- Writing tests for untested code
- Optimizing performance
- Adding a new MCP tool for Claude

---

**Thank you for contributing to Show Designer Pro!** 🎉✨
