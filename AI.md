# AI use

**Tools:** Claude Code (Anthropic's CLI agent), in the terminal and driving a browser for console checks.

**What for:** turning the brief into a GitHub project of small issues, then implementing them branch by branch. That covered the code, tests, the simulator and drafts of the docs. I reviewed each plan before any code was written and each pull request before it was merged.

**Caught:** the sensor engine sorted coverage changes that happened at the same instant by their value names instead of the order they were recorded. A sensor that was assigned and connected in one instant read back as `recoverable` and showed `not_checked`. The simulator's `ghost-heartbeat` story caught it, and it was fixed with regression tests (`f6141bb`).
