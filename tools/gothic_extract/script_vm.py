from pathlib import Path

import zenkit

from .config import native_path


MISSING_EXTERNALS: set[str] = set()


def make_vm(script_path: Path) -> zenkit.DaedalusVm:
    """Load GOTHIC.DAT into a VM whose unregistered externals are harmless no-ops.

    ZenKit's native default-external handler pops the arguments and pushes a default
    return value itself; the Python callback only gets notified.
    """
    vm = zenkit.DaedalusVm.load(native_path(script_path))
    vm.register_external_default(lambda sym: MISSING_EXTERNALS.add(sym.name))
    return vm
