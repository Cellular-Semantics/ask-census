#!/usr/bin/env bash
set -euo pipefail

MIN_PYTHON="3.10"
MAX_PYTHON="3.13"

# ---- Helpers ----------------------------------------------------------------

info()  { printf '\033[1;34m[INFO]\033[0m  %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m    %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m  %s\n' "$*"; }
fail()  { printf '\033[1;31m[FAIL]\033[0m  %s\n' "$*"; exit 1; }

# ---- Check Python -----------------------------------------------------------

PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        if "$candidate" -c "
import sys
min_parts = [int(x) for x in '$MIN_PYTHON'.split('.')]
max_parts = [int(x) for x in '$MAX_PYTHON'.split('.')]
cur = (sys.version_info.major, sys.version_info.minor)
if tuple(min_parts) <= cur < tuple(max_parts):
    sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done
[ -n "$PYTHON" ] || fail "No compatible Python found. Install Python >=$MIN_PYTHON and <$MAX_PYTHON (for example, python3.10, python3.11, or python3.12)."

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Found $PYTHON $PY_VERSION"

if "$PYTHON" -c "
import sys
min_parts = [int(x) for x in '$MIN_PYTHON'.split('.')]
max_parts = [int(x) for x in '$MAX_PYTHON'.split('.')]
cur = (sys.version_info.major, sys.version_info.minor)
if not (tuple(min_parts) <= cur < tuple(max_parts)):
    sys.exit(1)
" 2>/dev/null; then
    ok "Python version OK (>=$MIN_PYTHON, <$MAX_PYTHON)"
else
    fail "Python >=$MIN_PYTHON and <$MAX_PYTHON required, found $PY_VERSION"
fi

# ---- Create venv ------------------------------------------------------------

if [ ! -d .venv ]; then
    info "Creating virtual environment..."
    "$PYTHON" -m venv .venv
    ok "Virtual environment created"
else
    info "Virtual environment already exists"
fi

# ---- Install ----------------------------------------------------------------

info "Installing dependencies (editable)..."
.venv/bin/python -m ensurepip --upgrade 2>/dev/null || true
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -e ".[dev]" -q
ok "Dependencies installed"

# ---- Verify imports ----------------------------------------------------------

info "Verifying imports..."
.venv/bin/python -c "
from cxg_query_enhancer import enhance
from gene_resolver import resolve_genes, build_var_value_filter
from bitmap_manifest_join_lib import run_join, load_manifest_from_dict, load_bitmaps_from_dict
from enrich_slice_runner import main
print('  cxg_query_enhancer.enhance ......... OK')
print('  gene_resolver.resolve_genes ........ OK')
print('  gene_resolver.build_var_value_filter OK')
print('  bitmap_manifest_join_lib.run_join .. OK')
print('  enrich_slice_runner.main ........... OK')
"
ok "All imports verified"

# ---- Refresh census field lookups --------------------------------------------

info "Refreshing census field lookups..."
.venv/bin/python src/refresh_census_fields.py
ok "Census field lookups refreshed"

# ---- Check OLS4 MCP ---------------------------------------------------------

info "Checking OLS4 MCP connectivity..."
if command -v curl &>/dev/null; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://www.ebi.ac.uk/ols4/api/mcp" --max-time 10 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "405" ]; then
        ok "OLS4 MCP reachable (HTTP $HTTP_CODE)"
    else
        warn "OLS4 MCP returned HTTP $HTTP_CODE (may still work via MCP protocol)"
    fi
else
    warn "curl not found, skipping OLS4 connectivity check"
fi

# ---- Refresh obsolete-stage lookups -----------------------------------------

info "Refreshing obsolete developmental-stage lookups from Ubergraph..."
if ./data/refresh_obsolete_stages.sh; then
    ok "Obsolete-stage lookups refreshed"
else
    warn "Could not refresh obsolete-stage lookups (network issue?). Using cached files."
fi

# ---- Sync shared config (.claude → .codex) -----------------------------------

info "Syncing shared configs from .claude to .codex..."

# Agents
mkdir -p .codex/agents
for src in .claude/agents/*.md; do
    [ -f "$src" ] || continue
    dest=".codex/agents/$(basename "$src")"
    if [ -f "$dest" ] && diff -q "$src" "$dest" &>/dev/null; then
        continue
    fi
    cp "$src" "$dest"
    ok "  Synced agents/$(basename "$src")"
done

# Skills (mirror entire skill directories)
if [ -d .claude/skills ]; then
    for skill_dir in .claude/skills/*/; do
        [ -d "$skill_dir" ] || continue
        skill_name="$(basename "$skill_dir")"
        dest_dir=".codex/skills/$skill_name"
        mkdir -p "$dest_dir"
        # Sync all files recursively
        rsync -a --delete "$skill_dir" "$dest_dir/"
        ok "  Synced skills/$skill_name/"
    done
fi

# AGENTS.md ← CLAUDE.md
if [ -f CLAUDE.md ]; then
    if ! [ -f AGENTS.md ] || ! diff -q CLAUDE.md AGENTS.md &>/dev/null; then
        cp CLAUDE.md AGENTS.md
        ok "  Synced AGENTS.md"
    fi
fi

# ---- Done --------------------------------------------------------------------

echo ""
ok "Setup complete!"
echo ""
info "Activate the environment:"
echo "  source .venv/bin/activate"
echo ""
info "Usage with Claude Code:"
echo "  claude"
echo "  /cxg-query female T cells in lung tissue"
echo ""
info "Run tests:"
echo "  make test"
