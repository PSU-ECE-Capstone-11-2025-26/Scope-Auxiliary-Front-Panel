## Technical Setup

### 1. Install System Dependencies

**PyVISA** and a backend (such as **PyVISA-py**) must be installed systemwide first.
Extra setup may be necessary for specific interfaces. See the [PyVISA docs](https://www.pyvisa.org/docs).

### 2. Install uv (recommended)

[uv](https://docs.astral.sh/uv/) is an extremely fast Python package manager.

### 3. Set Up Development Environment

```bash
# Clone the repository
git clone git@github.com:PSU-ECE-Capstone-11-2025-26/afp.git
# change into the software directory
cd afp/software

# Create the virtual environment
uv venv
source .venv/bin/activate # macOS/Linux
# .venv/Scripts/activate.bat # Windows

# Install dependencies
uv sync
```

### 4. Run
```bash
# running directly from source
python -m tek-afp
```

### 5. Tests
```bash
# with venv activated
pytest -n auto

# or using uv (if venv not activated
uv run pytest -n auto
```