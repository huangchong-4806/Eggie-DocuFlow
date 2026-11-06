"""Build the standalone recovery EXE with the system .NET compiler, offline."""
import os
from pathlib import Path
import subprocess
import sys


def prepare(output):
    if os.name != 'nt':
        raise RuntimeError('The Windows recovery helper must be built on Windows')
    root = Path(__file__).resolve().parents[1]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    system = Path(os.environ['SystemRoot'])
    compiler = next((p for p in [system / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe',
                                system / 'Microsoft.NET/Framework/v4.0.30319/csc.exe'] if p.is_file()), None)
    if compiler is None:
        raise RuntimeError('The system .NET compiler is not available')
    result = output / 'EggieUpdateRestore.exe'
    subprocess.run([str(compiler), '/nologo', '/optimize+', '/platform:anycpu', '/target:exe',
                    '/codepage:65001', '/reference:System.Web.Extensions.dll',
                    '/win32manifest:' + str(root / 'packaging/windows/recovery.manifest'),
                    '/out:' + str(result), str(root / 'packaging/windows/EggieUpdateRestore.cs')], check=True)
    if not result.is_file() or result.stat().st_size == 0:
        raise RuntimeError('Windows recovery helper was not produced')
    return result


if __name__ == '__main__':
    prepare(Path(sys.argv[1]))
