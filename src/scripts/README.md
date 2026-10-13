# Ad hoc scripts

Reader: an agent that wrote a script while working, and the retro.

A script a box writes while working (a check, a query, a one-off helper) is
committed here in the same PR, named for what it does, with one comment line
at the top saying why it was needed. Nothing else in the repository depends on
this folder. The retro reads it: a script that keeps being needed should
become an `se` command.
