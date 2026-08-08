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

# Nothing here would break the function, but every megabyte is cold start.
JUNK = ("*.dist-info", "*.egg-info", "__pycache__", "bin", "*.pyc")


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
