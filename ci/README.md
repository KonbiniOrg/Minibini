# Continuous Integration Flow

Automated workflow for Minibini should allow developers to 
automatically update containers, trigger test runs, and deploy
various branches to somewhere they can be seen in an "offial" 
context.

This document is intended to both define the intended end-state 
and document the current state of play as we work toward the gials
laid out herein.

## Goal State

Using branches and a branch/checkin/push/merge request flow,
we should be able to easily and quickly develop, test, view and 
deploy new features.

Much of the innermost development loop will likely always take place
in local dev environments and docker deployments. The initial 
model envisioned in this document runs like this:

1. Create a feature branch\
\
Create a branch from 'main' in feature/[name of feature branch]\
using something like:\
\
```\
git checkout -b feature/my-cool-branch\
```\

2. Code!\
Make changes to code in the repo
3. use docker-compose to bring up a local environment\
```\
$ docker compose build\
$ docker compose up\
```
