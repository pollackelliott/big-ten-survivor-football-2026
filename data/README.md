# Schedule workbook input

For a new football season, upload exactly one Excel workbook to this folder (or provide its repo-relative path when running the workflow).

The initializer expects the same structure as the 2026 commissioner's workbook:

- Sheet name: `P4G5`
- Column A: conference team names
- Row 1, columns B:N: Weeks 1 through 13
- Schedule cells: opponent name, optionally prefixed with `at ` or `vs. `
- Yellow fill (`#FFD966`): power-conference nonconference opponent
- Blue fill (`#4A86E8`): G5 opponent
- Gray fill (`#CCCCCC`): FCS / ineligible opponent
- No classification fill: conference game

Recommended filename: `YYYY <Conference> Football Schedule Grid.xlsx`. The workflow can infer the season year from that filename.

After uploading the workbook, run **Actions → Initialize Football Season → Run workflow**.
