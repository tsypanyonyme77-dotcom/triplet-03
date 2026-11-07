# Test Book

Scenarios are ours. Taken together they must test all three layers and every interaction between them. Same content as part 4 of the report.

## Coverage

| Interaction | What it shows | Scenarios |
|-------------|---------------|-----------|
| Twin → Brain | The city runs normally and the Brain reacts correctly to real events | _IDs_ |
| Twin → Guardian | The Guardian recognizes healthy and unhealthy data | _IDs_ |
| Brain → Guardian | Trust verdicts change decisions, and decisions stay safe | _IDs_ |
| All three | The whole city works as one system, including when something goes wrong | _IDs_ |

## Scenario template

Copy per scenario. Trigger script: `scenarios/<id>-<name>.sh`. Log: `logs/<id>-*.log`.

### T0: Name

| Field | Value |
|-------|-------|
| ID | T0 |
| Name | |
| Layers involved | Twin, Guardian, City Brain |
| Description | |
| Trigger | One command, e.g. `./scenarios/t0-<name>.sh` |
| Expected: Twin | Concrete, observable output |
| Expected: Guardian | Concrete, observable output (include a time bound) |
| Expected: Brain | Concrete, observable output |
| How to verify | Timeline screen; log file `logs/t0-*.log` |

Expected outputs must be concrete and observable, not "the system behaves correctly".

## Scenarios

_(add them below)_
