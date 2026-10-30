# Contributing

This is a one-person project, so the most useful contributions are reports.

## Reporting a problem

[Open an issue](https://github.com/chibanaryan/acclaimed_media/issues/new/choose)
for either of these:

- **A bug**: something on the site that is broken or behaves wrongly.
- **A data correction**: a game or album with the wrong year, genre, cover,
  developer or artist, or a published list that is missing or misread.
  Link the page on the site and a source for the right answer.

Security problems go through the private form in [SECURITY.md](../SECURITY.md),
never a public issue.

Replies are best effort.

## Pull requests

Open an issue before you write a pull request, and wait until we have agreed
on the change. Pushing to `main` deploys the site, so I review every change
myself, and a PR that arrives without that conversation may be closed.

For an agreed change:

- Set up as the [README](../README.md) describes, then run `pre-commit install`.
  The hooks run black, flake8 and the test suite on every commit.
- Tests run with `pytest`, and coverage must stay at 100%. A change to caching,
  sessions or other process-wide state should also pass
  `pre-commit run django-tests --hook-stage manual`.
- Edit the `.js` source, never the `.min.js`, then run `scripts/minify_js.sh`
  to rebuild the minified files and bundles.
- Change Python dependencies in the `.in` files and recompile the locks with
  `pip-compile`. Never edit `requirements*.txt` by hand.
- A row template and its JavaScript renderer have to change together. See
  "Home Page Client/Server Rendering Consistency" in [AGENTS.md](../AGENTS.md),
  which also covers the rest of the architecture.

By contributing, you agree that your contribution is licensed under the
project's [MIT License](../LICENSE).

## Code of conduct

Everyone taking part is expected to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
