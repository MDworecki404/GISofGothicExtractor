from pathlib import Path

import zenkit

import struct

from .config import native_path
from .daedalus_scan import set_code_size


MISSING_EXTERNALS: set[str] = set()


def make_vm(script_path: Path) -> zenkit.DaedalusVm:
    """Load GOTHIC.DAT into a VM whose unregistered externals are harmless no-ops.

    ZenKit's native default-external handler pops the arguments and pushes a default
    return value itself; the Python callback only gets notified.
    """
    vm = zenkit.DaedalusVm.load(native_path(script_path))
    vm.register_external_default(lambda sym: MISSING_EXTERNALS.add(sym.name))
    size = bytecode_size(script_path)
    if size:
        set_code_size(vm, size)
    return vm


def bytecode_size(script_path: Path) -> int | None:
    """A compiled .DAT ends with <u32 code size><code>; find the length field that matches the file end."""
    data = Path(script_path).read_bytes()
    n = len(data)
    for p in range(n - 5, 0, -1):
        if struct.unpack_from("<I", data, p)[0] == n - p - 4:
            return n - p - 4
    return None
