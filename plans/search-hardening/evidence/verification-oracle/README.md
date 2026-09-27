> To replay without filling the repository with generated fixtures, copy this directory to a new temporary directory first, then run reproduce.py there. Archived logs retain their original paths. No synthetic databases or multi-megabyte fixtures are checked into this evidence directory.

# Independent oracle replay evidence

All fixtures are synthetic. No user service was used; no repository file was modified.

Main replay entry: `python3 reproduce.py` (writes only below this directory). Product source is imported from the absolute repository path in each script; source_hashes.json records the tested files.

Each run has `.stdout.txt`, `.stderr.txt`, and `.result.json` (command/cwd/exit_code).

- `archived-inspect.py`: archived fixture generator has 1011 invalid timestamps. Phrase actual index 1010 is present in snippets [1010,1012,1013], yet the archived hardcoded 2106 check says excluded.
- `archived-probe.*`: the archived probe still reports 11 PASS and exit 0.
- `archived-clusters2.*`: exact archived observer output showing that false exclusion diagnosis.
- `corrected-inspect.py`: temp-only datetime/timedelta fix produces zero invalid timestamps, phrase actual index 2106, snippets [1,2,3], genuinely excluding the later phrase.
- `corrected-clusters2.*`: G2 and stale cursor observations against the corrected synthetic fixture.
- `four-broken-returns.py`: alters source/store identity, excerpt body, metadata status, and errors/partial; probe still reports 11 PASS and exit 0.
- `underscore-unescaped.py`: removes underscore escaping, asserts the replacement is active, prints CONFIRMED_UNDERSCORE_PATTERN '_'; probe still reports 11 PASS and exit 0.

Fixture homes usable by an isolated server:
- Original archived fixture: `archived/home`
- Corrected timestamps: `corrected/home`

These mutations are process-local monkeypatches. They do not alter product source. They demonstrate gaps in the independent oracle harness, not confirmed original product defects. The existing repository tests have stronger identity and literal-LIKE negative controls.
