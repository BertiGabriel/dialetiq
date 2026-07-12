# Versioning and Git workflow

This project publishes to two app stores, and the stores impose **irreversible** rules on
version numbers. Getting this wrong blocks a release for days. Hence a document.

## Repository state

Already published and connected:

```
origin  https://github.com/BertiGabriel/dialetiq
```

`main` exists on the remote. There is no "initial upload" left to do.

---

## 1. Branches

| Branch | Role |
|---|---|
| `main` | Always deployable. **Protected**: no direct pushes, PR only, CI must be green. |
| `feat/<scope>` | One feature. Short-lived — days, not weeks. |
| `fix/<scope>` | One fix. |
| `chore/<scope>` | Dependencies, config, infrastructure. |

No `develop`, no GitFlow. With a small team, a long-lived integration branch produces merge
maintenance and conflicts, and buys nothing.

### Protect `main` (once, in the GitHub UI)

**Settings → Rules → Rulesets**, targeting `main`:

- Require a pull request before merging
- Require status checks to pass
- Require review from Code Owners
- Block force pushes and deletions

This is not ceremony. Without it, one `git push --force` on a Tuesday rewrites history and
nobody can tell what was lost.

---

## 2. Commits — Conventional Commits

```
feat(engagement): schedule campaign delivery by tenant timezone
fix(rls): campaign_recipient policy was missing WITH CHECK
chore(deps): update uv.lock
docs(threat-model): document the base-import timing oracle
test(isolation): cover cross-tenant UPDATE on every table
```

Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`, `ci`.

This is not bureaucracy — it is the input that decides the version and generates the
changelog:

| Commit | Version effect |
|---|---|
| `fix:` | *patch* — `1.2.0` → `1.2.1` |
| `feat:` | *minor* — `1.2.1` → `1.3.0` |
| `BREAKING CHANGE:` in the body | *major* — `1.3.0` → `2.0.0` |

---

## 3. Versioning — SemVer, with the tag as the source of truth

```
v0.1.0   v0.2.0   ...   v1.0.0
```

**The git tag is the single source of truth.** We do not hand-write the version into
`pyproject.toml` or `pubspec.yaml`: two places holding the same fact drift on the first
careless day, and then nobody knows which is right. CI reads the tag and injects it.

Everything is `0.x` until the app is live in the stores. SemVer's compatibility promise only
starts at `1.0.0`.

---

## 4. The thing that blocks releases: build numbers

This is the easiest mistake to make and the most expensive to undo.

Apple and Google **reject any build whose number has already been used**, and the number
**can never decrease**. Ship build `999` by accident and every future build must exceed 999,
forever. There is no undo.

So we keep two concepts apart that are routinely conflated:

| Concept | What it is | Source |
|---|---|---|
| **Version name** | What the user sees: `1.4.0` | The SemVer git tag |
| **Build number** | What the store indexes: `137` | **CI-generated, monotonic** |

`pubspec.yaml` holds a placeholder. At build time, CI injects:

```bash
flutter build ipa \
  --build-name=1.4.0 \
  --build-number=${{ github.run_number }}
```

`github.run_number` only increases and never repeats. **This is why the app must be built in
CI, not on a developer's machine** — a local build has no trustworthy counter, and that is
exactly how a duplicate build number gets shipped.

---

## 5. Release flow

1. Develop on a `feat/...` branch; open a PR.
2. **CI must pass** — beyond lint and unit tests, that includes:
   - the **tenant isolation suite** (RLS);
   - the **database configuration assertions** (no application role with `BYPASSRLS`, none a
     member of the owner, RLS forced on every table carrying `tenant_id`);
   - the **`import-linter` contracts** (domain imports no infrastructure; modules do not
     import each other; `platform` imports no module);
   - the **secret scanner** (`gitleaks`).
3. Squash-merge to `main`.
4. Tag:
   ```bash
   git tag -a v0.3.0 -m "Campaign scheduling"
   git push origin v0.3.0
   ```
5. The tag triggers the release pipeline: build the Docker image (tagged with the version),
   deploy to Kubernetes, and build/sign/ship the app to TestFlight and Google's internal
   test track.

No production artifact ever leaves a developer's machine. Everything comes from a tag.

---

## 6. What must never be committed

This is security, not tidiness. **A secret committed to git is in the history forever**, even
if you delete it in the next commit — anyone who cloned has the whole history. The only real
remediation is to revoke the secret and issue a new one.

Never commit:

- `.env` and any environment file
- Signing and push keys: `*.p8` (APNs), `*.p12`, `*.keystore`, `*.jks`
- `google-services.json`, `GoogleService-Info.plist`
- Neon credentials, Firebase service accounts
- **The HMAC pepper** — leaked alongside a database dump, it makes the entire consumer base
  reidentifiable

All of it lives in the secret manager (production) and in **GitHub Environment Secrets**
(CI). Environment-scoped, not repository-scoped: a workflow running on a PR branch then
*cannot* read the APNs key or the Neon credentials, because it does not run in the
production environment. That closes the classic exfiltration path — open a PR that prints
the secrets to the log.

The root `.gitignore` covers these patterns, and `gitleaks` runs in CI as the second line —
because `.gitignore` only protects people who did not use `git add -f`.

---

## 7. Day-to-day

```bash
# Start a feature
git switch -c feat/campaign-scheduling

# Commit
git add -A
git commit -m "feat(engagement): schedule campaign delivery"

# Publish the branch; the push output prints the PR link
git push -u origin feat/campaign-scheduling

# After merge
git switch main && git pull
git branch -d feat/campaign-scheduling
```

The `gh` CLI is optional — `git push` prints the link to open the PR. To create PRs from the
terminal: `brew install gh`.
