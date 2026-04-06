- when running sub-agents or running in a git worktree, don't assume the live stack/dev stack is available.
Docker containers might run in the root worktree, from a different branch, or at the user's discretion.
- when running smoke tests or verifying code against the dev stack, always coordinate with the user.
