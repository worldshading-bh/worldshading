# Safe Feature Release From an Advanced Clone

Use this process when a demo, staging server, or development clone contains the feature
we want, but is ahead of production with unrelated work.

The central rule is:

> **Start from the exact live Git revision and add only the selected feature. Never
> merge the advanced clone into live.**

This process was proven when the online payment feature was moved from the advanced
demo to production on 13 August 2026, and reused for the Purchase Plan releases in
August 2026.

## The three workspaces used at World Shading

Do not treat these directories as interchangeable:

| Workspace | Typical location | Purpose |
|---|---|---|
| Advanced clone | `/home/erpadmin/frappe-bench/apps/worldshading` | Develop and test against the clone database. It may be dirty, ahead of GitHub, or have no useful feature branch. |
| Clean release checkout | `/home/hilal/payment-release` | Package only approved files on top of the latest GitHub `main`. All release commits and pushes happen here. |
| Production checkout | `~/frappe-bench/apps/worldshading` on `wserp` | Pull reviewed commits from GitHub. Never use it to package clone history. |

The advanced clone does **not** need to have its work committed, pushed, or placed on a
branch. Its files are the tested source material, not the Git history being released.
The clean release checkout supplies the trustworthy history.

The normal flow is:

```text
tested clone files
    -> copy explicit paths
clean checkout of GitHub main
    -> feature branch -> commit -> push -> pull request
GitHub main
    -> inspect -> fast-forward pull
production
```

---

## 1. Establish the live baseline

On production, use read-only Git commands:

```bash
cd /home/erpadmin/frappe-bench/apps/worldshading
git status
git branch
git log -1 --oneline
git remote -v
```

Record the branch and commit. The production worktree must have no unexplained tracked
changes. Untracked generated files such as `__pycache__` do not normally block a pull,
but must still be reviewed and must never be staged.

Fetch GitHub and compare it with production:

```bash
git fetch origin main
git log --oneline --decorate HEAD..origin/main
git log --oneline --decorate origin/main..HEAD
```

- If both commands show no commits, production and GitHub `main` have the same baseline.
- If GitHub is ahead, identify every already-merged but undeployed commit. A new branch
  from GitHub `main` will include them, so they must be approved as part of the next
  production deployment.
- If production is ahead of GitHub, stop. Do not package a release until the unexplained
  production-only commits are reconciled.

Do not build the release from the advanced clone's branch or history.

## 2. Prepare the clean release checkout

World Shading keeps a reusable clean checkout at `/home/hilal/payment-release`. Update
it from GitHub before creating every feature branch:

```bash
cd /home/hilal/payment-release
git checkout main
git pull --ff-only origin main
git status --short --branch
git log -3 --oneline --decorate
git checkout -b feature/<feature-name>
```

If the clean checkout does not exist, clone the repository once and then follow the
same commands:

```bash
git clone https://github.com/worldshading-bh/worldshading.git /home/hilal/payment-release
```

Never create the release branch from the advanced clone's current branch. A branch on
the clone is optional and does not make its unrelated history safe to release.

## 3. Copy only the feature

Make an explicit list before copying:

- runtime files
- DocType JSON and controllers
- website pages or client assets
- tests
- operational documentation
- exact shared-file changes, such as one hook entry

Copy only those paths from the advanced clone. Use full source and destination paths so
there is no ambiguity. For example:

```bash
cp /home/erpadmin/frappe-bench/apps/worldshading/worldshading/worldshading/report/<report>/<report>.js \
  /home/hilal/payment-release/worldshading/worldshading/report/<report>/<report>.js

cp /home/erpadmin/frappe-bench/apps/worldshading/worldshading/worldshading/report/<report>/<report>.py \
  /home/hilal/payment-release/worldshading/worldshading/report/<report>/<report>.py
```

Merge shared files manually; never copy
an entire `hooks.py`, `patches.txt`, or other shared file over the live version.

Exclude unless specifically required and reviewed:

- unrelated demo work
- credentials and private onboarding files
- `__pycache__`, `.pyc`, logs and generated assets
- vendor documents
- migration patches from the demo's history
- database exports

## 4. Validate before staging

At minimum:

```bash
git status --short
git diff --check
git diff --stat
git diff -- <shared-file>
git ls-files --others --exclude-standard | sort
```

Validate file types using tools compatible with ERPNext v12:

```bash
# JavaScript
node --check path/to/file.js

# Python 3.6
python3.6 -m py_compile path/to/file.py

# JSON
python3.6 -m json.tool path/to/file.json >/dev/null
```

Compare each copied file with its tested source. Matching SHA-256 hashes prove that the
release copy is exact:

```bash
sha256sum <release-file> <tested-clone-file>
```

Also search for secrets and inspect the complete diff. The changed-path list must
contain only the feature and intentional shared-file edits. A large line count is not
itself a problem; an unexplained path is.

## 5. Stage explicit paths

Do not use `git add .` or `git commit -am`.

```bash
git add <approved-feature-path-1>
git add <approved-feature-path-2>
git add <manually-merged-shared-file>
```

Review the Git index, which is exactly what the commit will contain:

```bash
git status --short
git diff --cached --name-only
git diff --cached --stat
git diff --cached --check
```

Stop if any unrelated, generated, vendor, patch, or credential file appears.

## 6. Commit, push and review through a pull request

```bash
git commit -m "feat: <feature summary>"
git push -u origin feature/<feature-name>
```

Open a pull request into `main`. Confirm:

- the base branch is `main`
- the source is the feature branch
- the file count matches the staged review
- shared files contain only the intended small edits
- GitHub reports no unexpected changes or conflicts

Merging the pull request changes GitHub `main`; it does not deploy production.

Keep the feature branch until production has been deployed and tested. The pull request
is permanent release history and must not be deleted. The feature branch may be deleted
after verification.

## 7. Deploy production deliberately

Before any change, document:

1. objective
2. impacted files and data
3. risk level
4. rollback plan

Then:

1. Confirm the live worktree has no unexplained tracked changes.
2. Fetch and inspect `HEAD..origin/main` using the commands below.
3. Take and verify a production backup when schema or data can change.
4. Pull with `git pull --ff-only origin main`.
5. Apply only the reviewed schema/configuration operation.
6. Restart only through the approved production procedure when new Python or hooks
   must be loaded.
7. Verify structure read-only before creating or enabling configuration.
8. Enable risky features one component at a time and perform a controlled test.

Use this standard inspection sequence on production before pulling:

```bash
cd ~/frappe-bench/apps/worldshading
git status --short --branch
git fetch origin main
git log --oneline --decorate HEAD..origin/main
git diff --name-status HEAD..origin/main
git diff --stat HEAD..origin/main
```

The commit IDs and file list must match the merged pull request. Then deploy only by
fast-forward:

```bash
git pull --ff-only origin main
git log -3 --oneline --decorate
git status --short --branch
```

### If production has a tracked local edit

Stop and inspect it:

```bash
git diff -- path/to/file
```

Save a recoverable patch before doing anything else:

```bash
git diff -- path/to/file > /tmp/<feature>-live-before-release.patch
```

If the reviewed GitHub release already contains the same intended change, discard only
that exact local file edit before pulling. Production uses an older Git version, so use:

```bash
git checkout -- path/to/file
```

Do not use `git reset --hard`, and do not discard unrelated tracked changes.

### Decide what must be loaded after the pull

| Release content | Normal follow-up |
|---|---|
| JavaScript only | Hard-refresh the browser; rebuild assets only when the app's asset bundle requires it. |
| Python module | Reload only the approved web/worker processes so they import the new code. Inspect process names first with `sudo supervisorctl status`. |
| Report/DocType JSON | Use a reviewed targeted `reload-doc` only when required. This changes database metadata. |
| Schema, patches, fixtures | Plan backup and migration/configuration explicitly. Never assume a Git pull applies database changes. |

Do not automatically run `bench migrate`, `bench restart`, `bench update`, backups,
cache clearing, or service restarts. Each requires explicit production approval and a
defined rollback.

For a new standard DocType, a reviewed targeted command may be used instead of a full
migration when appropriate:

```bash
bench --site <site> reload-doc <module> doctype <doctype-folder>
```

`reload-doc` still changes database schema. It requires the same care, backup and
verification as any other production schema operation. Skipping `bench migrate` also
means patches do not run; handle their intended work explicitly and ensure a later
migration remains safe.

## 8. Rollback principles

- Record the pre-deployment commit.
- Prefer disabling the new feature before reverting code.
- Revert the release commit rather than resetting production history.
- Preserve business/audit records created by the feature.
- Never restore a pre-deployment database backup after new financial or operational
  transactions without reconciling the lost interval first.
- Keep the feature branch until deployment and verification are complete.

The preferred code rollback is:

1. Use GitHub **Revert** on the merged pull request, creating a new revert pull request.
2. Review and merge the revert.
3. On production, inspect `HEAD..origin/main` again.
4. Pull the revert with `git pull --ff-only origin main`.
5. Reload only the processes required by the reverted file types.

Never move production backward with `git reset --hard`. A revert preserves the release
and rollback audit trail.

## Common mistakes and what they mean

| Message or situation | Meaning and response |
|---|---|
| `Permission denied` after typing a `.js` or `.py` path | The shell tried to execute the file. It is harmless; use `git diff -- <path>` to view it. |
| `git: 'restore' is not a git command` | Production Git is old. Use `git checkout -- <exact-path>` only after saving and reviewing the diff. |
| `main...origin/main [behind 2]` | Usually the feature commit plus its merge commit are waiting. Inspect them before pulling. |
| Untracked `__pycache__` directories | Generated files. Do not stage them. They usually do not block a fast-forward pull. |
| Dirty advanced clone has no branch | Expected and acceptable. Copy explicit tested files into the clean release checkout. |
| Pull request merged but production unchanged | Expected. GitHub merge and production deployment are separate operations. |

## Release checklist

- [ ] Live branch, commit and clean status recorded
- [ ] Clean release clone created from the live baseline
- [ ] Clean release `main` updated from GitHub before branching
- [ ] Dedicated feature branch created
- [ ] Explicit feature file list approved
- [ ] Shared files merged manually
- [ ] Generated files, secrets, vendor files and unrelated work excluded
- [ ] Python/JSON/static checks passed
- [ ] Staged file list reviewed
- [ ] Pull request file count and diff reviewed
- [ ] Production backup verified where required
- [ ] Production pull used `--ff-only`
- [ ] Targeted schema/configuration steps completed
- [ ] Runtime restarted only through the approved procedure
- [ ] Read-only post-deployment verification passed
- [ ] Feature configured disabled first, then tested and enabled incrementally
