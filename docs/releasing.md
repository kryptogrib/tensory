# Releasing Tensory

## How Versions Work

Tensory uses `hatch-vcs` — version comes from **git tags**, not from a file.

```
git tag v0.2.0  →  version "0.2.0"      (release)
git tag v0.2.1a1 → version "0.2.1a1"    (alpha/pre-release)
no tag          →  version "0.2.1.dev3+gabcdef1"  (dev, NOT uploadable to PyPI)
```

**Rule**: PyPI rejects versions with `+local` segment. Always tag before building.

## Release Checklist

```bash
# 1. Make sure everything is clean
git status                        # no uncommitted changes
uv run pytest tests/ --ignore=tests/test_api.py -q   # all tests pass
uv run pyright tensory/           # type check clean

# 2. Decide version
#    Major:  breaking API changes     → v1.0.0
#    Minor:  new features             → v0.2.0
#    Patch:  bug fixes                → v0.1.2
#    Alpha:  pre-release for testing  → v0.2.0a1

# 3. Tag the release
git tag v0.2.0                    # or whatever version
git push origin v0.2.0            # push tag to GitHub

# 4. Build
rm -rf dist/                      # clean old builds
uv build                          # creates .whl + .tar.gz
ls dist/                          # verify: tensory-0.2.0-py3-none-any.whl

# 5. Test on Test PyPI first (optional but recommended for major releases)
uv publish --publish-url https://test.pypi.org/legacy/
# verify:
uvx --from "tensory[ui]==0.2.0" \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    tensory-dashboard --help

# 6. Publish to production PyPI
uv publish
# enter: username = __token__, password = your PyPI API token

# 7. Verify
uvx --from "tensory[ui]" tensory-dashboard --help
uvx --from "tensory[mcp]" tensory-mcp --help
```

## PyPI Tokens

- **Test PyPI**: https://test.pypi.org/manage/account/token/
- **Production PyPI**: https://pypi.org/manage/account/token/

Store in `~/.pypirc` or pass interactively:
```
username: __token__
password: pypi-AgEN...  (your token)
```

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `uv build` without tag → `0.2.1.dev3+gabcdef1` | Tag first: `git tag v0.2.0` |
| PyPI rejects upload | Version already exists on PyPI. Bump version, new tag |
| `uvx` shows old version | `uv cache clean --force` then retry |
| Old `.whl` files in `dist/` get uploaded | Always `rm -rf dist/` before `uv build` |
| Forgot to push tag | `git push origin v0.2.0` |

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 0.1.1a2 | 2025-03-30 | Test PyPI: dashboard CLI, context formatting |
| 0.1.1a1 | 2025-03-30 | Test PyPI: first test release |
| 0.1.0 | 2025-03-28 | Initial: core library + MCP |
