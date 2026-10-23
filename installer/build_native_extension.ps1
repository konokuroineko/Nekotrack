$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$CrateRoot = Join-Path $RepoRoot "rust\nekotrack_core"
$WheelDirectory = Join-Path $RepoRoot "target\wheels"
$SimilarityReport = Join-Path $env:TEMP "nekotrack-native-similarity.json"
$RecommendationReport = Join-Path $env:TEMP "nekotrack-recommendation-ranking.json"

Set-Location $RepoRoot

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust stable is not installed or cargo is not on PATH. Install the stable Rust toolchain, reopen PowerShell, and rerun this script."
}

Write-Host "Python environment:"
python -c "import sys; print(sys.executable)"

Write-Host "Installing maturin into the active Python environment..."
python -m pip install --upgrade maturin

New-Item -ItemType Directory -Force -Path $WheelDirectory | Out-Null
Push-Location $CrateRoot
try {
    maturin build --release --out $WheelDirectory
}
finally {
    Pop-Location
}

$Wheel = Get-ChildItem -Path $WheelDirectory -Filter "nekotrack_core-*.whl" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $Wheel) {
    throw "Maturin did not produce a NekoTrack native wheel in $WheelDirectory"
}

Write-Host "Installing native wheel: $($Wheel.Name)"
python -m pip install --force-reinstall $Wheel.FullName
if ($LASTEXITCODE -ne 0) {
    throw "Installing the native wheel failed."
}

Write-Host "Verifying the extension loads in the active Python environment..."
python -c "import native_acceleration as n; print('Backend:', n.BACKEND_NAME); assert n.RUST_AVAILABLE, 'Rust extension failed to load'"
if ($LASTEXITCODE -ne 0) {
    throw "The extension was built but did not load from the active Python environment."
}

Write-Host "Running Rust/Python result-equivalence tests..."
python -m unittest discover -s tests -p test_native_acceleration.py -v
if ($LASTEXITCODE -ne 0) {
    throw "Native similarity parity tests failed."
}

Write-Host "Benchmarking native title similarity..."
python experiments/benchmark_native_similarity.py --pairs 5000 --iterations 9 --json-out $SimilarityReport
if ($LASTEXITCODE -ne 0) {
    throw "Native similarity benchmark failed."
}

Write-Host "Benchmarking optimized Python recommendation ranking..."
python experiments/benchmark_recommendations.py --candidate-sizes 50 250 500 --sources 50 --iterations 7 --json-out $RecommendationReport
if ($LASTEXITCODE -ne 0) {
    throw "Recommendation benchmark failed."
}

Write-Host ""
Write-Host "Rust is available in this Python environment. Benchmark reports:"
Write-Host "  $SimilarityReport"
Write-Host "  $RecommendationReport"
Write-Host "Build the NekoTrack executable from this same Python environment so PyInstaller can bundle the native module."
