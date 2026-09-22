# Third-party source attribution

This directory contains selected upstream source files, copied without content
changes from the revisions in `manifest.json`. Each project retains its original
license. The top-level ProWet MIT license applies to our integration,
not as a replacement for these notices. Upstream READMEs describe the full
projects; training data, most training tools and model weights are **not** bundled.

| Directory | Upstream | Source license |
|---|---|---|
| NetSolP | https://github.com/teevee112/NetSolP-1.0 | BSD-3-Clause; LICENSE |
| RP3Net | https://github.com/RP3Net/RP3Net | MIT; LICENSE |
| TemBERTure | https://github.com/ibmm-unibe-ch/TemBERTure | MIT; LICENSE.md |
| TemStaPro | https://github.com/ievapudz/TemStaPro | MIT; LICENCE.md |
| GATSol | https://github.com/binbinbinv/GATSol | MIT; LICENSE |
| EvoEF2 | https://github.com/tommyhuangthu/EvoEF2 | MIT; LICENSE |

`manifest.json` records repository, commit and SHA-256 for every bundled file.
External Git-tracked assets use Git blob SHA-1 (header + contents), not plain
file SHA-1. They are fetched into the user's installation prefix, never this tree.
EvoEF2 library tables are also downloaded, not bundled.

Pro4S is fetched directly into the installation prefix at a fixed commit. Its
root repository lacks an explicit license; the Apache-2.0 license under MaSIF
does not license all Pro4S code. Public availability does not establish unrestricted
use or redistribution rights. Confirm terms with the authors for your intended use.
We do not redistribute Pro4S. ESM SDK 3.1.1 is installed from PyPI without
redistributing or changing its license. Check that version's Cambrian terms and
the terms for each chosen weight; newer upstream MIT statements do not by
themselves relicense every older artifact. Access-controlled HF downloads require
upstream authorization. The installer does not accept terms on your behalf.

The source licenses do not automatically cover external weights or native tools.
MSMS's Bioconda package is labeled **Free for academic use**; APBS is BSD-3-Clause,
PyMesh and other dependencies retain their own licenses. Those binaries are
obtained by conda/pip from upstream channels, not stored in this repository.
