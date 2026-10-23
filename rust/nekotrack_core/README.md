# Optional native acceleration

This crate is the first Rust/PyO3 pilot for NekoTrack. It accelerates the
matching-block portion of title similarity in TMDB metadata matching while
preserving the existing Python normalization, exact-match and containment rules.

The Rust function implements the same ratio as
difflib.SequenceMatcher(None, left, right, autojunk=False). The Python wrapper
falls back to difflib if the compiled extension cannot be imported. A missing
Rust build must never prevent NekoTrack from starting.

## Build and test on Windows

Run this from the repository root in the same Python environment used for
NekoTrack and its PyInstaller build. It builds, installs, parity-tests and benchmarks the native extension:

```powershell
python -m pip install --upgrade maturin
Push-Location rust\nekotrack_core
maturin build --release --out ..\..\target\wheels
Pop-Location
$wheel = Get-ChildItem target/wheels/nekotrack_core-*.whl | Select-Object -First 1
if (-not $wheel) { throw "Native wheel was not produced." }
python -m pip install $wheel.FullName
python -m unittest discover -s tests -p test_native_acceleration.py -v
python experiments/benchmark_native_similarity.py --pairs 5000 --iterations 9 --json-out "$env:TEMP\nekotrack-native-similarity.json"
```

Building a wheel requires a working Rust stable toolchain. The workflow in
.github/workflows/python-checks.yml also builds and tests this extension on Windows and Linux
with Python 3.11 and 3.14, then uploads benchmark JSON for each environment.

## What the benchmark proves

The comparison isolates 5,000 deterministic title-pair similarity calculations,
checks exact output equivalence, and reports median/p95 times. It does not
claim that 5,000 pairs are processed in one typical app interaction, and it is
not a claim about total startup, API latency, scrolling or the full app.

Keep the native path only if measurements justify its extra build/packaging
cost and end-to-end profiling shows a useful benefit. Do not change matching
scores or provider-selection behavior to manufacture a speedup.

## Packaging

The normal Python requirements intentionally do not force a Rust toolchain on
source users. To include Rust in a PyInstaller build, build and install the wheel
in the same environment before running PyInstaller. Then verify the frozen app
loads the extension rather than silently falling back to Python. NekoTrack still
works with the fallback if the extension is unavailable.
