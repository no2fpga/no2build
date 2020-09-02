Nitro FPGA build system
=======================

This repository contains helpers to build FPGA bitstream using the open-source
toolchain and make use of re-usable cores, automatically track dependencies
between them etc ...

Using it is by no means a requirement to re-use any of the "Nitro" FPGA cores,
it's just a convenience.

For example on how to use this build system, look at the `Makefile` and
`no2core.mk` in the FPGA cores repositories and in the projects of the
`smunaut/ice40-playground` repository.


Limitations
-----------

The current version was just extracted from the `ice40-playground` repository
and as such only supports the ice40 architecture so far. I have a modified
version for ECP5 that was used in the Hack-a-day badge repository but I have
yet to merge the two.


License
-------

All the files in this repository are licensed under the terms of the
BSD 3-Clause "New" or "Revised" License.

See LICENSE file for full text.
