# Libraries

Reader: an agent that finds code two modules share.

A library is one pure Go package under `src/lib`, held to the same imports as
a compute module (the battery's `module-imports` rule). At least two modules
under `src/modules` import it: the battery's `library-users` rule refuses one
with fewer. Code one module alone uses stays in that module.
[spec/index.md](../../spec/index.md) says where each part of the index lives.
