# Stakeholders

Reader: an agent writing requirements who cannot say whose need a record serves.

## When

- A record's `serves` key names a need but nobody who has it.
- Two demands pull in opposite directions and it is unclear whose weighs more.
- The request comes from one person and the work touches others: users, maintainers, a host.

## Steps

1. List everyone the work touches, in rings: who uses the result, who runs or maintains it, who
   is affected without using it, and who must approve it.
2. Name each one by role, never by personal name: the owner, a worker, a stranger reading the
   docs, the host that loads a skill.
3. Write, for each, the one thing they need from this work, in their words.
4. Mark who is present and who is absent. An absent stakeholder's need is a guess until someone
   who speaks for them confirms it.
5. Where two needs conflict, write both and the conflict; do not settle it here.
6. Fill each record's `serves` key with the need and the role it belongs to.
7. A need nobody on the list has is cut, or asked of the person.

## Where it goes in SE

Each need lands in the `serves` key of a record in the requirements reference. A conflict between
two stakeholders goes to the decision skill as its own decision. The person's own words stay in
the work issue's User requirement (verbatim) section.

## Source

Ian Alexander, "A Taxonomy of Stakeholders", International Journal of Technology and Human
Interaction, 2005: the onion model of rings around the product, and the negative and absent roles.
