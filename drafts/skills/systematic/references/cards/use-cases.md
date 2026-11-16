# Use cases

Reader: an agent writing a functional requirement that needs the steps around it.

## When

- A functional record names a response but not what comes before or after it.
- A requirement only makes sense as one step of a longer exchange between a person and SE.
- A failure path is suspected but not written: what happens when a step does not succeed.

## Steps

1. Name the primary actor and the goal they hold, in one line: "The owner lists a draft and
   calls it by name."
2. Write the main success path as numbered steps, one action each, at most nine, actor and system
   taking turns.
3. Under each step that can fail, write its extension: the condition, and what the system does
   then.
4. Write the precondition (what holds before step one) and the guarantee (what holds after the
   last step, success or not).
5. Turn each system step into an event-driven EARS statement, and each extension into an unwanted
   behaviour one.
6. Check each statement against the clarify reference: does the base branch already do it?
7. Keep the use case as the source of its records; it is not itself a requirement.

## Where it goes in SE

Each statement becomes the `statement` key of a record in the requirements reference, with
`kind: functional`. The success path, compressed, can open the work issue's Approach section; the
extensions often become its Acceptance items.

## Source

Alistair Cockburn, "Writing Effective Use Cases", Addison-Wesley, 2000: the actor and goal line,
the main success scenario, extensions and the minimal guarantee.
