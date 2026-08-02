# Project Daybreak v1.0.2 Package

This GitHub-ready package contains the refined source repository, regenerated schemas and fixtures, migrations, documentation, CI/security workflows, systemd deployment assets, and verified Python distributions under `dist/`.

Start with:

1. `README.md`
2. `docs/audit/Project_Daybreak_v1.0.2_Elite_Review.md`
3. `docs/releases/v1.0.2/VERIFICATION_REPORT.md`
4. `SECURITY.md`
5. `docs/OPERATIONS.md`

Verify the outer download before extraction:

```bash
sha256sum -c Project_Daybreak_GitHub_Ready_v1_0_2.zip.sha256
```

After extraction:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[recorder,evaluator,test,dev]'
make quality
```

Do not connect this release to live funds. Use a dedicated Alpaca paper account and complete the target-environment acceptance campaign before assigning paper production-candidate status.
