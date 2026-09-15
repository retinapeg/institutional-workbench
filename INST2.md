# Side-by-side commands

`inst` stays pinned to stable v0.1.0. `inst2` uses this editable v0.2 checkout.
Both v0.2 entry points call the same existing CLI; no routing or orchestration changes.
The CLI already defaults to the current directory, so no `--repo` is necessary.

Install on this laptop without replacing the stable tool:

```sh
uv tool install --force git+https://github.com/retinapeg/institutional-workbench@v0.1.0
UV_TOOL_DIR="$HOME/.local/share/uv/tools-inst2" UV_TOOL_BIN_DIR="$HOME/.local/share/uv/tools-inst2/bin" uv tool install --editable /Users/leonardaarons-ditson/Documents/Codex/institutional-workbench-v0.2
ln -s "$HOME/.local/share/uv/tools-inst2/bin/inst2" "$HOME/.local/bin/inst2"
```

The final link command intentionally refuses to overwrite an existing command.
For subsequent editable-source changes, no reinstall is needed. Do not install this checkout
into the default uv tool directory: its retained `inst` entry point would conflict with v0.1.

From a clean Git repository:

```sh
inst2 hackathon "TASK"
inst2 engineering "TASK"
inst2 economy "TASK"
inst2 engineering "TASK" --explain-routing
```

No aliases or shell startup-file edits are required. Keep this checkout in place while
using its editable installation. The frozen v0.2.0 tag and main remain unchanged.
