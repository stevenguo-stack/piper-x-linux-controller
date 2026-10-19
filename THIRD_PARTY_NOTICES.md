# Third-party notices

This controller installs and links to the official AgileX Robotics `pyAgxArm`
Python SDK at runtime.

- Project: `agilexrobotics/pyAgxArm`
- Pinned commit: `2255d88e1fabdf20fcd1eccbc4312b4ce1cfd2d4`
- License: GNU Lesser General Public License v3.0 only (LGPL-3.0-only)
- Source: https://github.com/agilexrobotics/pyAgxArm

The Windows installer also installs AgileX's official CAN backend:

- Project: `agilexrobotics/python-can-agx-cando`
- Pinned commit: `fbd76e5c3e6b6d9b30eeb0610c5b595994d8ad94`
- License declared by the upstream project: MIT
- Source: https://github.com/agilexrobotics/python-can-agx-cando
- The upstream package supplies architecture-specific `cando.dll` and
  `agx_receive.dll`. They are downloaded with the official dependency; this
  controller does not replace or build the vendor DLLs.

The third-party SDK, backend, and DLLs are not copied into this source archive.
They are installed by pip from the official repositories when `install.sh` or
`install_windows.bat` is run. The upstream packages retain their own licenses
and notices.
