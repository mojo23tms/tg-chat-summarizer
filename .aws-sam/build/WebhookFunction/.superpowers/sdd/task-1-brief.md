### Task 1: Project scaffold and config

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Create: `tests/test_config.py`
- Create: `.gitignore`
- Create: `data/.gitkeep`

**Interfaces:**
- Consumes: nothing.
- Produces: `config` module exposing `DB_PATH: str`, `TELEGRAM_TOKEN: str`, `LLM_BACKEND: str`, `GEMINI_API_KEY: str`, `GROQ_API_KEY: str`, `DEFAULT_COUNT: int = 30`, `MAX_COUNT: int = 200`, `DISK_HEADROOM: float = 0.10`, and `DEFAULTS: dict` with keys `style`, `filter_level`, `language`.

- [ ] **Step 1: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
data/*.db
.env
```

- [ ] **Step 2: Create `requirements.txt`**

```
python-telegram-bot==21.6
google-generativeai==0.8.3
pytest==8.3.3
```

- [ ] **Step 3: Create `data/.gitkeep`** (empty file so the data dir exists in git)

- [ ] **Step 4: Write the failing test**

`tests/test_config.py`:
```python
import config


def test_defaults_present():
    assert config.DEFAULT_COUNT == 30
    assert config.MAX_COUNT == 200
    assert config.DISK_HEADROOM == 0.10
    assert set(config.DEFAULTS) == {"style", "filter_level", "language"}
    assert config.DEFAULTS["filter_level"] == "clean"
    assert config.DEFAULTS["language"] == "auto"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 6: Create `config.py`**

```python
import os

DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
LLM_BACKEND = os.environ.get("LLM_BACKEND", "gemini")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

DEFAULT_COUNT = 30
MAX_COUNT = 200
DISK_HEADROOM = 0.10  # keep at least 10% of the volume free

DEFAULTS = {
    "style": "concise, neutral bullet points",
    "filter_level": "clean",
    "language": "auto",
}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add requirements.txt config.py tests/test_config.py .gitignore data/.gitkeep
git commit -m "chore: scaffold project and config"
```

---

