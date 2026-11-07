# Standard Development and Release Workflow

All development, bug fixes, and feature additions in this repository adhere to the following 5-step development and release lifecycle. PRs to `staging` can be automatically merged once local tests pass; merging from `staging` to `main` strictly requires explicit human approval after manual testing.

## 5-Step Lifecycle

```
1. Feature/Fix Branch (from staging)
       ↓
2. Local Tests, Commit, Push & Create PR to staging
       ↓
3. Auto-merge PR into staging branch (verified)
       ↓
4. Deploy / Verify staging → [HALT: Wait for Manual Testing] ⏸️
       ↓ (After user confirms manual testing passed)
5. Merge staging into main
```

---

### Step 1: Branch
- Always base new feature or bugfix branches on the latest `staging` branch:
  ```bash
  git checkout staging && git pull origin staging
  git checkout -b <type>/<description> # e.g. feat/xyz, fix/abc, chore/123
  ```
- Make necessary changes and run all relevant tests locally before committing.

---

### Step 2 & 3: Push, Create PR, and Merge to Staging
- Push the branch to remote:
  ```bash
  git push -u origin <type>/<description>
  ```
- Create a Pull Request targeting `staging` via GitHub CLI:
  ```bash
  gh pr create --base staging --head <type>/<description> --title "..." --body "..."
  ```
- Once local tests and checks pass, automatically merge the PR into `staging`:
  ```bash
  gh pr merge <pr_number_or_url> --merge
  ```
- Ensure `origin/staging` is updated.

---

### Step 4: Wait for Manual Testing on Staging
- **CRITICAL HALT**: Notify the user that changes are merged to `staging` and deployed.
- **STOP and wait** for the user to conduct manual verification/testing on the staging environment ("等人工测试staging"). Do NOT proceed to `main` until explicit user sign-off is given.

---

### Step 5: Merge Staging to Main
- Only after the user explicitly confirms that manual testing has passed ("人工测试通过" / "可以上线/合入 main"):
  ```bash
  git checkout main
  git pull origin main
  git merge staging --ff-only
  git push origin main
  ```
