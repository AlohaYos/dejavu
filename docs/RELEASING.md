# Releasing

How dejavu gets from a git tag to `brew install AlohaYos/tap/dejavu`.

---

## One-time setup

Do these once, in this order. Steps 1–3 must all be done **before** the repository goes
public.

### 1. Revoke the leaked Personal Access Token

SourceTree embedded a PAT in the remote URL in plain text (`https://ghp_xxx@github.com/…`).
Revoke it at <https://github.com/settings/tokens>, then switch the remotes to SSH:

```bash
cd ~/GitHub/dejavu && git remote set-url origin git@github.com:AlohaYos/dejavu.git
cd ~/GitHub/deja   && git remote set-url origin git@github.com:AlohaYos/deja.git
git remote -v      # no ghp_ anywhere
```

### 2. Read the history you are about to publish

Making a repository public exposes **every past commit**, not just the current tree.

```bash
git log --oneline
```

dejavu was created without importing the old repository's `.git`, so this should be two or
three commits. Confirm there is nothing here you would not want a stranger to read.

### 3. Create the tap repository

The formula cannot live in this repository — Homebrew looks for a repository named
`homebrew-<tap>`, and it must be public.

```bash
gh repo create homebrew-tap --public --description "Homebrew formulae for AlohaYos"
```

Naming it `homebrew-tap` (rather than `homebrew-dejavu`) means it can host other tools
later, and users write `AlohaYos/tap/<name>`.

### 4. Create the token that lets the release workflow push to the tap

The release workflow runs in `AlohaYos/dejavu` but has to commit into
`AlohaYos/homebrew-tap`. The default `GITHUB_TOKEN` cannot reach across repositories, so
it needs one of its own.

1. Go to <https://github.com/settings/personal-access-tokens/new> (**fine-grained**, not
   classic)
2. Repository access → **Only select repositories** → `AlohaYos/homebrew-tap`
3. Permissions → Repository permissions → **Contents: Read and write**. Nothing else
4. Copy the token
5. In `AlohaYos/dejavu`: Settings → Secrets and variables → Actions → New repository secret
   - Name: `TAP_TOKEN`
   - Value: the token

Scope it to the one repository and the one permission. A token that can only write to a
tap is a small problem if it leaks; a classic token with `repo` scope is a large one.

### 5. Make dejavu public

```bash
gh repo edit AlohaYos/dejavu --visibility public --accept-visibility-change-consequences
```

(Or in the browser: Settings → Danger Zone → Change repository visibility.)

---

## Cutting a release

```bash
# 1. Bump the version — this file is the single source of truth
vim src/dejavu/__init__.py        # __version__ = "0.2.0"

git commit -am "chore: bump to 0.2.0"
git push

# 2. Tag it. Everything else happens on its own.
git tag v0.2.0
git push origin v0.2.0
```

The tag must match `__version__` exactly (minus the `v`). The workflow checks this first
and fails the release if they disagree — a mismatch would produce a formula that installs
a different version from the one it claims.

What the workflow then does:

```
git push origin v0.2.0
        │
        ▼
  release.yml (macos-latest)
   1. Verify the tag matches __version__
   2. Run the tests
   3. Create the GitHub Release
   4. Download the source tarball, compute its sha256
   5. Copy packaging/dejavu.rb into the tap, rewriting url + sha256
   6. Commit and push to AlohaYos/homebrew-tap
        │
        ▼
  brew update && brew upgrade dejavu
```

### Verify

```bash
brew untap alohayos/tap 2>/dev/null
brew install AlohaYos/tap/dejavu
brew test dejavu          # runs the formula's test block
dejavu --version
```

The formula's `test do` block is not decoration: it initialises a knowledge base and then
searches for a **two-character Japanese word**. The FTS5 trigram tokenizer cannot match
anything shorter than three characters, so that assertion is what proves the LIKE fallback
survived the release. If it ever fails, Japanese search is broken and the formula should
not ship.

---

## Editing the formula

`packaging/dejavu.rb` in **this** repository is the source. The copy in the tap is
generated. Edit it here; the next release overwrites the tap.

Do not hand-edit `url` or `sha256` in `packaging/dejavu.rb` — the workflow rewrites both
lines on every release. The placeholder values in the file are never used.

---

## Deliberate omissions

**No `dejavu update` command.** `brew upgrade dejavu` already does this. A second,
home-grown update path would duplicate Homebrew's job and drift out of sync with it.

**No update check phoning home.** The upstream project (`lk`) contacts GitHub once a day
from its MCP server to see whether a newer version exists. dejavu does not, and should not:
the README tells users there is *no network access at all*, and that claim should stay
literally true rather than nearly true.
