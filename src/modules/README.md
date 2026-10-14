# Modules

Reader: an agent writing or moving an SE module.

Each module is one Go package in one folder, `src/modules/<cluster>/<module>`,
holding its logic, the commands it declares to the collector, and its tests. A
cluster is a folder that groups modules on one subject; it holds no code of its
own. The wiring file, `src/index/wiring.yaml`, runs the module as the instance
`<cluster>/<module>`, which owns the names under it.

A module without the I/O flag is a compute module: the battery's
`module-imports` rule holds it to the index contract, the libraries under
`src/lib` and the pure standard library. [spec/index.md](../../spec/index.md)
is the contract.
