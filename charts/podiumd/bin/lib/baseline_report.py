"""The shared "print one release-baseline.yaml section's own outcome"
three-tier wrapper show-component-baseline-version and show-image-
baseline-version both need identically — factored out here since
duplicating IT was pure boilerplate, unlike what each script's own
resolve-and-print body actually does (a component's Helm chart version
plus every image path it declares, vs. a single <key> <basename> image
pin) — see show_baseline_section's own docstring."""


def show_baseline_section(label, baseline, resolve):
    """Prints "=== {label} baseline ===" (label: "upgrade_docs" or
    "release_table"), then one of three things:
      - `baseline` is None: a one-line "release-baseline.yaml has no
        {label} key — skipping" note (release-baseline.yaml simply
        doesn't have this key at all — not an error).
      - `resolve(baseline)` returns a non-None string: printed as-is,
        indented the same way the "no key" note above is — `resolve`'s
        own return value already carries any "error: " prefix it wants
        (never added a second time here), since a script's own inner
        resolution step (e.g. lib.image_version.resolve_scoped_matches
        raising SystemExit) may already produce one, and a caller
        formatting its own message must too, to keep this ONE shared
        print format either way.
      - `resolve(baseline)` returns None: it has ALREADY printed
        whatever success body it wants itself (this wrapper never
        knows or needs to know that shape) before returning.
    Always ends the section with one blank line, and returns whether
    the section's own state was actually shown (True on success, False
    on skip/error) — the exact bool main() needs to decide whether
    EITHER baseline showed anything at all."""
    print(f"=== {label} baseline ===")
    if baseline is None:
        print(f"  (release-baseline.yaml has no {label} key — skipping)")
        print()
        return False

    error = resolve(baseline)
    if error:
        print(f"  {error}")
        print()
        return False

    print()
    return True
