# terminal-code

A small local coding assistant for the terminal. It can chat with an OpenAI model, read files, search a workspace, run commands with confirmation, and save file replacements after showing a diff.

## Setup

PowerShell:

```powershell
$env:OPENAI_API_KEY="sk-..."
```

Optional:

```powershell
$env:OPENAI_MODEL="gpt-5.5"
```

## Run

PowerShell:

```powershell
.\run.ps1 C:\path\to\your\project
```

Git Bash:

```bash
./run.sh /c/path/to/your/project
```

Or:

```powershell
python .\terminal_code.py C:\path\to\your\project
```

## Commands

```text
/help                 Show commands
/read app.py 1:120    Read file lines
/search Todo src      Search inside a folder
/run pytest           Run a command after confirmation
/save app.py          Paste replacement content, preview diff, save
/model gpt-5.5        Change the model
/quit                 Exit
```

The assistant only sees files you read or search during the session. It does not edit files unless you use `/save` and confirm the diff.

## Interface

The terminal flow is the right default for coding work: it is fast, explicit, and easy to use inside a repo. A visual interface is possible and useful once you want persistent sessions, a file tree, side-by-side diffs, and command history. Keep it optional so the CLI stays reliable.
