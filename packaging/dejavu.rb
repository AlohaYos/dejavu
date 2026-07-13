# Homebrew formula for dejavu.
#
# This file is the SOURCE that gets copied into the tap repository
# (AlohaYos/homebrew-tap) as Formula/dejavu.rb by .github/workflows/release.yml.
#
# The `url` and `sha256` lines are rewritten automatically on every release.
# Do not hand-edit them here: the workflow overwrites both.
class Dejavu < Formula
  include Language::Python::Virtualenv

  desc "Local knowledge base that gives Claude Code memory across sessions"
  homepage "https://github.com/AlohaYos/dejavu"
  url "https://github.com/AlohaYos/dejavu/archive/refs/tags/v0.2.0.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"

  # Pulls in a Python built against Homebrew's SQLite, which guarantees a version new
  # enough for the FTS5 trigram tokenizer (3.34+). dejavu's Japanese search depends on
  # it, so this dependency is doing real work — it is not just "some Python".
  depends_on "python@3.13"

  def install
    # dejavu has zero runtime dependencies, so there are no `resource` blocks to declare.
    virtualenv_install_with_resources
  end

  test do
    assert_match "dejavu", shell_output("#{bin}/dejavu --version")
    assert_match "dejavu", shell_output("#{bin}/deja --version") # the short alias

    system "git", "init"
    system bin/"dejavu", "init"
    assert_predicate testpath/".dejavu/knowledge.db", :exist?

    system bin/"dejavu", "add", "検索実装のメモ",
           "--body", "3段階検索を行う", "--keywords", "fts5,search"

    # A two-character Japanese query. The trigram tokenizer cannot match anything shorter
    # than three characters, so this only passes if the LIKE fallback is intact.
    assert_match "検索実装", shell_output("#{bin}/dejavu search 検索")
  end
end
