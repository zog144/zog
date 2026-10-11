# Zog releases

## Reviewed revisions and source pins

Components develop on `unstable`; `main` is not changed without release authorization. Release-build assembles explicitly reviewed source revisions and file dispositions, not an arbitrary latest-branch checkout.

## Candidate and acceptance

Source closure, license and notice coverage, path mapping, repeatable export, package structure and tests require review. The stable-ready and unstable-ready classifications are distinct; passing synthetic tests does not prove live installation acceptance.

## Distribution

The public distribution is `zog`. Release-build assembles the approved GitHub source and the sdist and wheel, then publication follows controlled GitHub and PyPI workflows. Do not treat newly committed component guides as published documentation until they are included in a pinned candidate.

## Documentation export

The desired canonical path is `docs/<program>/`, copied unchanged from the component's reviewed source revision. Verify the [documentation index](README.md), all program chapter links and the traceability maps during release candidate validation. Existing manifest paths and dispositions must be regenerated against new source commits; editing path strings alone invalidates source/blob verification.

## Recovery and rollback

Keep historical published artifacts immutable; corrections produce reviewed new candidates. Production deployment is a separate operator authorization from source release publication.
