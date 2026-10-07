**Download:** `R-Board-…-portable.zip` below, unzip it anywhere and run `R Board.exe`. Nothing needs installing.

Windows may say "Windows protected your PC" (the app isn't signed). To skip that, right-click the zip → **Properties** → tick **Unblock** → **OK** before unzipping. Or click **More info**, then **Run anyway**.

**AI features** (kind, mood and style tags, search by meaning, group by content) are a one-time install from inside R Board: **Plugins → Get AI Features**. You don't need to download `R-Board-AI-….zip` yourself; R Board fetches it.

<details><summary>Run from source</summary>

Needs Python 3.11 on Windows 10 or 11.

```
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\rboard.exe
```

Build the portable zip yourself:

```
.venv\Scripts\pip install -r requirements\build.txt
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Python .venv\Scripts\python.exe
```

New release: set `VERSION` in `beeref/constants.py` and `pyproject.toml`, commit, then `git tag -a v<version> -m "patch notes"` and `git push origin v<version>`.

</details>
