# be kind, please rewind

a very simple, gui-based, local file versioning tool that automatically or manually takes snapshots of your important files, so you can rewind to any point in time. <br>
<br>
meant for non-power users. think of it as a more user-friendly and simple git without a terminal.<br>

## features
- track individual files or entire folders
- automatic snapshots on file change or at timed intervals (30s, 1m, 5m)
- manual snapshot creation with optional notes
- side-by-side diff viewer for text files
- image previewer for common image formats
- restore snapshots either by overwriting the current file or saving as a new copy
- add/edit notes for each snapshot to remember important changes
- rename snapshots with custom names for better organization
- exclude specific files or patterns using a `.bkprignore` file
- runs in the system tray for background operation
- contextual status bar for at-a-glance information
- import/export snapshots for a single file as a zip archive
- pause tracking alltogether

### snapshot naming
  snapshots are created with a blank name by default, only showing a timestamp. you can give them a custom, memorable name (e.g., "working-feature") at any time by right-clicking. the original timestamp is always preserved and attached to the name, ensuring every snapshot remains unique and sortable, but your custom name will be shown in the list for clarity.

## how to run
you know the drill. make sure you're using python 3.11 since this wasn't tested on any other version.
1. clone thy repo
2. `pip install -m requirements.txt`
3. run it (`python app.py`)

## boring stuff
icons are not my own, they're from [here](https://fonts.google.com/icons?selected=Material+Symbols+Outlined:fast_rewind:FILL@0;wght@400;GRAD@0;opsz@24&icon.query=fast+rewind&icon.size=24&icon.color=%235985E1). <br>
gemini 2.5 pro _helped out a bit_ in this project, in the following lines: <br>
817 - 854

## todo (with priority out of 5)
- full-text search within snapshots (4)