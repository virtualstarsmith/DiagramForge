"""pytest configuration for DiagramForge.

The main purpose here is to make coverage trace the *subprocess* runs of the
CLI scripts (doctor.py, icon_search.py, prepare_fonts.py, spec_graph.py,
mermaid_import.py) so their executed lines count toward the coverage figure.
coverage.py only auto-traces child processes when a sitecustomize hook starts
it; we install one by pointing COVERAGE_PROCESS_START at the project
.coveragerc and registering a sitecustomize module on sys.path.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Enable subprocess coverage tracing. coverage.start() in the child reads
# COVERAGE_PROCESS_START to find this config.
# Generate the coverage config with an ABSOLUTE source path: several CLI tests
# run their subprocess with cwd=<tempdir>, and a relative `source = scripts`
# matches nothing there, so the child's shard would be discarded as empty.
_cov_cfg = ROOT / ".coveragerc"
_cov_cfg.write_text(
    "[run]\n"
    "parallel = True\n"
    f"source = {(ROOT / 'scripts').as_posix()}\n"
    "branch = False\n"
    "\n"
    "[report]\n"
    "exclude_lines =\n"
    "    pragma: no cover\n"
    "    raise NotImplementedError\n"
    "    if __name__ == .__main__.:\n"
    "show_missing = True\n",
    encoding="utf-8",
)
os.environ["COVERAGE_PROCESS_START"] = str(_cov_cfg)

# Anchor the coverage data file to the project root. Several CLI tests run
# their subprocess with cwd=<tempdir>; without an absolute COVERAGE_FILE the
# child's .coverage.* shard would land in that tempdir and be lost at cleanup.
os.environ["COVERAGE_FILE"] = str(ROOT / ".coverage")

# Make the scripts/ dir importable for subprocesses that load sibling modules
# via importlib (some tests construct a fresh interpreter for isolation).
scripts_dir = str(ROOT / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

# Install a sitecustomize that starts coverage in any child python process.
# We write it to a temp dir on first import and prepend that dir to PYTHONPATH
# for children spawned by the suite.
_sitecustomize_dir = ROOT / ".pytest_cache" / "subprocess_cov"
_sitecustomize_dir.mkdir(parents=True, exist_ok=True)
_sitecustomize_file = _sitecustomize_dir / "sitecustomize.py"
if not _sitecustomize_file.exists():
    _sitecustomize_file.write_text(
        "import os\n"
        "if os.environ.get('COVERAGE_PROCESS_START'):\n"
        "    try:\n"
        "        import coverage\n"
        "        coverage.process_startup()\n"
        "    except Exception:\n"
        "        pass\n",
        encoding="utf-8",
    )
pythonpath = os.environ.get("PYTHONPATH", "")
if str(_sitecustomize_dir) not in pythonpath:
    os.environ["PYTHONPATH"] = (
        str(_sitecustomize_dir) + os.pathsep + pythonpath if pythonpath else str(_sitecustomize_dir)
    )
