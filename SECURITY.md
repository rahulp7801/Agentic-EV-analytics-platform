# Security policy

Do not put credentials in issues, pull requests, screenshots, session notes, logs,
or sample configuration. Report vulnerabilities through GitHub's private
vulnerability reporting interface. If a credential is exposed, revoke it at its
provider first; deleting a file or rewriting Git history does not revoke access.

Keep local credentials in ignored `.env` or `.local/secrets/` files. Hosted
credentials belong in GitHub Actions secrets or server-only Vercel environment
variables. Never use `NEXT_PUBLIC_` for database passwords or provider keys.
Use the restricted worker and dashboard database roles, never the owner role.

CI scans the complete tracked source tree and every incoming commit using a
checksum-pinned Gitleaks release. Default rules are extended to catch provider
keys in prose. Findings are redacted; scanner reports and private diagnostics
must not be uploaded as public artifacts. GitHub secret scanning and push
protection provide additional checks, but no scanner detects every secret.

## Public repository audit, 2026-09-11

The audit covered fetched branches and public pull-request heads (345 commits,
1,072 unique file objects), repository issue/PR comments, all 106 retained
workflow log archives, and the one available Actions artifact. Default Gitleaks
rules reported no findings. A private comparison against configured credential
values found the Odds API key in `SESSION_2026_03_27.md`, introduced in commit
`c3b823f`. The new provider-key rule independently detects that exposure.

The current file is redacted. **The historical credential remains exposed and
must be revoked.** The owner has been asked to replace the local and GitHub
secret values. Rotation is not yet verified. Incoming-commit checks prevent new
exposures; they do not claim the old history is clean. History removal requires a
coordinated rewrite and may also require GitHub Support to remove cached views
and pull-request references; forks and external copies cannot be recalled.

No other configured credential matched the audited material, and the default
scanner found no credentials in downloaded public logs/artifacts/comments.
This is evidence about the audited content, not proof that unknown or expired
credentials have never been exposed. Local paths, public CA certificates,
project identifiers and synthetic disposable-CI passwords are not secrets.

The platform is read-only with respect to betting and trading venues. Do not add
order execution or bypass provider access controls as part of a security fix.
