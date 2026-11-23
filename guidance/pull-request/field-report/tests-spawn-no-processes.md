---
name: tests-spawn-no-processes
description: 'Tests start no processes: code under test runs in-process, each door is real in one contract test only. Load it before writing or changing a test.'
---

The person's requirement of 23 Nov:

> A test suite is not supposed to spawn a lot of processes. It's supposed to run via a test
> framework.

- **In-process.** A test calls the code under test through the test framework: a script through
  its `main(argv)`, a hook through its logic. Its output is read with `capsys`, its environment
  and working directory set with `monkeypatch`. A planted pytest suite runs with
  `pytester.runpytest_inprocess`.
- **Doors are faked.** git, `gh`, a shell, a project's suite command and the network are doors:
  each is called for real at most once in the suite, in the one contract test that proves the
  real program behaves as its fake assumes. Every other test uses the fake. In SE that is git's
  `fake_git_door` and the process door's `fake_processes` (`<se>/scripts/process_door.py`).
- **No repository per test.** A test builds its repositories on the fake git door, or shares one
  session-scoped repository built once.
- **One entry-point test.** A script or hook keeps one test that starts the real thing, to prove its
  wiring, marked `@pytest.mark.spawns("entry: <script>")`. A door's contract is marked
  `@pytest.mark.spawns("contract: <door>")`. Any other start carries a reason that says why it
  cannot run in-process, such as shell logic that runs only as a process.
- **The check.** SE's spawn guard, the pytest plugin `<se>/scripts/spawn_guard.py`, counts the
  processes each test starts and fails an unmarked one, naming each call. Its baseline,
  `tests/spawn-baseline.yaml`, lists what is not converted yet and only shrinks: a converted test
  leaves it in its own change.
- **In a Python project.** A project that holds se as a module loads the guard from its
  top-level `conftest.py`, with `<se>/scripts` on `sys.path`:

```python
import spawn_guard


def pytest_addoption(parser, pluginmanager):
    spawn_guard.register(pluginmanager)
```

  `pytest --spawn-baseline=init` writes its first baseline, once.

Not picked: raising time bounds, or leaving folders out of the count. A slow suite is fixed by
starting fewer processes.
