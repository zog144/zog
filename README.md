# Zog

This is the public source and release repository for the Zog project.

The first aggregate release, **Zog 0.1.0**, is being prepared. The complete source
tree will be supplied by `release-build` after the component migrations to the
`zog.*` Python namespace and aggregate validation are complete. This repository
currently contains only this bootstrap overview; it does not yet contain an
installable Zog package or a released 0.1.0 artifact.

Development and public implementation work belong on **`unstable`**. **`main`**
provides the project overview. The component repositories remain independently
maintained, and release preparation remains separate from this public repository.

The agreed aggregate identity is:

- Python distribution: `zog`
- First aggregate version: `0.1.0`
- Python namespace: `zog.*`
- First-party release license: `BSD-3-Clause OR GPL-3.0-only`, covering eligible
  code, documentation and artwork; third-party terms remain separate.

The reviewed aggregate will include its license texts, notices and source manifest.
Future publication will build and test the canonical source distribution and wheel,
retain those artifacts, and publish the same verified bytes to GitHub Releases and
PyPI. This public repository will own PyPI Trusted Publishing through GitHub OIDC,
using `.github/workflows/publish-pypi.yml` and the `pypi` environment. No publishing
workflow is present in this bootstrap.

Zog is developed by its maintainers in collaboration with ChatGPT, an AI system
from OpenAI. This collaboration includes architecture, implementation, testing,
documentation and code review.
