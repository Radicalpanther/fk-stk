# Continue Working with Claude Code

This repository was set up with **Claude Code**, an AI-powered development environment that helps you write code, manage projects, and automate workflows.

## What is Claude Code?

Claude Code is an interactive AI assistant that:
- Writes and edits code directly in your repository
- Runs terminal commands and tests
- Helps with git operations, debugging, and refactoring
- Remembers context across sessions using memory files

## How to Continue Where You Left Off

### 1. Start Claude Code
From this directory, run:
```bash
claude
```

### 2. Reference Previous Work
Claude Code automatically loads:
- Git history and current branch status
- Memory files from `.claude-omniroute/projects/.../memory/`
- Recent conversation context (if available)

### 3. Pick Up Work
Simply describe what you want to continue:
- "Continue where we left off"
- "What was I working on last?"
- "Finish implementing [feature]"
- "Review the changes we made"

### 4. Access Session Memory
Memory files are stored in:
```
C:\Users\sanka\.claude-omniroute\projects\C--Users-sanka-fk-stk\memory\
```

Check `MEMORY.md` for an index of saved context.

## This Repository

- **Branch**: `master`
- **Remote**: GitHub (private) - https://github.com/Radicalpanther/fk-stk
- **Contents**: Telegram bot project with configuration files

## Common Commands

- `claude` - Start Claude Code in this directory
- `/help` - See available slash commands
- `/config` - Adjust settings
- `! <command>` - Run a shell command directly in the session

## Security Note

This is a **private repository** because it contains sensitive tokens (Telegram bot credentials). Keep it private and never share tokens publicly.

---

**Last session**: 2026-10-08  
**Set up by**: Claude Code with user Radicalpanther
