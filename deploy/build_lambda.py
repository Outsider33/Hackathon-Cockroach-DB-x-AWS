"""Build dist/function.zip -- the deployment package for the Lambda.

    py -3.12 deploy/build_lambda.py

Everything in the package is pure Python (pg8000, scramp, asn1crypto), which is
why it can be built on Windows and run on Amazon Linux without a container or a
manylinux wheel. That was the reason for choosing pg8000 over psycopg2 in the
first place, and this script is where the choice pays off.

boto3 is NOT vendored: the Lambda runtime already ships it, and it is only
needed at all if EMBED_BACKEND is set to bedrock.
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "dist" / "build"
ZIP = ROOT / "dist" / "function.zip"

# The .dist-info directories are NOT junk, whatever their name suggests. scramp,
# which pg8000 pulls in for SCRAM authentication, reads its own version through
# importlib.metadata at import time, and metadata lives in .dist-info. Deleting
# them produced a function that could not even be imported:
#
#   Unable to import module 'handler': No package metadata was found for scramp
#
# Measured on 2026-08-09 on the deployed function, after this script had claimed
# in a comment that nothing it deleted would break anything. They weigh a few
# kilobytes; the cold start argument never applied to them.
JUNK = ("__pycache__", "bin", "*.pyc")


def main():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet",
         "--target", str(BUILD), "pg8000"],
        check=True,
    )

    for pattern in JUNK:
        for path in BUILD.glob(pattern):
            shutil.rmtree(path) if path.is_dir() else path.unlink()

    shutil.copy(ROOT / "api" / "handler.py", BUILD / "handler.py")

    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(BUILD.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(BUILD))

    size = ZIP.stat().st_size
    print(f"{ZIP}  {size / 1024:.0f} KiB")
    if size > 50 * 1024 * 1024:
        sys.exit("over the 50 MiB direct-upload limit -- push through S3 instead")


if __name__ == "__main__":
    main()
