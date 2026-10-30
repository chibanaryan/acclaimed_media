# Security policy

## Reporting a vulnerability

Report it privately through GitHub's advisory form:

https://github.com/chibanaryan/acclaimed_media/security/advisories/new

Please do not open a public issue for a security problem. The advisory stays
private until a fix is out.

Include what you found, where (a URL or a file and line), and the steps to
reproduce it. A short proof of concept helps more than a scanner report.

## Scope

In scope:

- The live site, https://acclaimedmedia.org
- The code in this repository

Out of scope:

- The third-party services the site reads data from (IGDB, Wikidata, Discogs,
  MusicBrainz, the Cover Art Archive, HowLongToBeat). Report those to their
  owners.
- Reports that only point out a missing header or best-practice setting, with
  no way to exploit it.

## Testing rules

- No denial-of-service, load testing or automated scanning against the
  production site. It runs on a single small dyno with per-IP rate limits, so
  heavy traffic takes it down for everyone and gets your IP blocked.
- Use only accounts you created yourself.
- Do not read or change other users' data, such as their tracked games and
  albums or their saved filters. If you reach any by accident, stop there and
  say so in the report.

## What to expect

This is a one-person project, so replies are best effort. I aim to acknowledge
a report within a week. Fixes deploy straight from `main`, and I will credit
you in the advisory if you would like that. There is no bug bounty.

## Supported versions

There are no releases. Only the code currently deployed from `main` is
supported.
