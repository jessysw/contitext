"""Keep generated integrations usable after a Homebrew Cellar upgrade."""
from pathlib import Path
import sys


def integration_python() -> str:
    """Use the current formula's verified opt link; leave other installs alone.

    Never resolve the returned executable: the opt symlink is what survives an
    upgrade. An unlinked keg or an opt link to another installation is not used.
    """
    executable = Path(sys.executable)
    try:
        environment = Path(sys.prefix).resolve(strict=True)
        keg = environment.parent
        cellar = keg.parent.parent
        if environment.name != "libexec" or keg.parent.name != "contitext" or cellar.name != "Cellar":
            return sys.executable
        opt = cellar.parent / "opt" / "contitext"
        candidate = opt / "libexec" / "bin" / "python"
        if opt.is_symlink() and opt.resolve(strict=True) == keg and candidate.samefile(executable):
            return str(candidate)
    except (OSError, RuntimeError):
        pass
    return sys.executable
